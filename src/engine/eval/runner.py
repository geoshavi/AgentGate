"""In-process evaluation harness: calls verification.pipeline.run_verification
directly -- the same function api.py's review_code() calls -- never
review_code() itself and never HTTP, so it can supply a real DB connection
and attribute every judge call's metrics to a specific eval case.
review_code() hardcodes conn=None (api.py is deliberately stateless), which
would make cost/latency aggregation impossible; run_verification() has no
such restriction.

Budget is fixed for the whole benchmark (BENCHMARK_MAX_TOKENS,
BENCHMARK_PLANNED_BUDGET) rather than sourced from Config, so the
benchmark's ceiling doesn't silently drift with an operator's local env
vars -- these are confirmed values, not configurable.

One failing case must never abort the benchmark: run_case() catches any
exception from run_verification() (BudgetExceededError, network errors,
...), records it on the case's error field, and the run continues. Such
cases are excluded from accuracy denominators but their partial cost still
counts toward total_cost -- see _aggregate().
"""

import shutil
import sqlite3
import subprocess
from decimal import Decimal
from pathlib import Path

from engine.config import Config
from engine.eval.dataset import (
    BENCHMARK_NAME,
    BENCHMARK_VERSION,
    CASES,
    DATASET_VERSION,
    EvalCase,
)
from engine.runtime.budget import BudgetController, estimate_cost
from engine.runtime.gateway import LLMGateway
from engine.state import db
from engine.state.models import (
    AgentExecutionMetric,
    EvalCaseLensResult,
    EvalCaseResult,
    EvalCaseSchemaFailure,
    EvalRun,
    VerificationResult,
)
from engine.verification.judge import LENSES
from engine.verification.pipeline import run_verification

EVAL_ROOT = Path(".engine/eval")

# Confirmed values -- see the Phase 2 design report's §7. Not Config fields:
# a benchmark's ceiling must not silently vary by environment.
BENCHMARK_MAX_TOKENS = 400_000
BENCHMARK_PLANNED_BUDGET = Decimal("3.00")

# Assumptions behind the --dry-run cost estimate, matching verification/judge.py's
# hardcoded max_tokens=1600 per lens call and the Phase 2 report's worst-case
# input-token assumption for small benchmark snippets. This value only feeds
# estimate_benchmark_cost(); it must be kept equal to the cap judge.py actually
# enforces, or --dry-run understates the ceiling it exists to check.
JUDGE_MAX_OUTPUT_TOKENS = 1600
ASSUMED_INPUT_TOKENS_PER_CALL = 2000
LENSES_PER_CASE = 3


def get_git_commit_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    if result.returncode != 0:
        return "unknown"
    return result.stdout.strip()


def estimate_benchmark_cost(num_cases: int, judge_model: str) -> Decimal:
    """Worst-case cost estimate for ``num_cases`` cases, used by --dry-run.
    Reuses runtime.budget.estimate_cost (the same function that computes
    real costs) instead of duplicating pricing math, so this estimate stays
    consistent with actual enforcement if PRICE_TABLE is ever updated.
    """
    calls = num_cases * LENSES_PER_CASE
    per_call = estimate_cost(
        judge_model,
        input_tokens=ASSUMED_INPUT_TOKENS_PER_CALL,
        output_tokens=JUDGE_MAX_OUTPUT_TOKENS,
    )
    return per_call * calls


def select_cases(category: str | None) -> list[EvalCase]:
    if category is None:
        return list(CASES)
    return [c for c in CASES if c.category == category]


def _write_case_files(workspace: Path, files: dict[str, str]) -> None:
    """Deliberately not orchestrator.agents.common.write_files(): that
    function's entire purpose is guarding against a malicious/malformed
    path from LLM-generated output trying to escape the workspace via
    '..' traversal. Eval case file paths come from the hand-authored
    dataset, not from an LLM, so that threat model doesn't apply here --
    and importing it would pull orchestrator/agents/ into eval/'s
    dependency graph, which the architecture rules forbid (eval/ may only
    depend on verification/, runtime/, state/).
    """
    for relative_path, content in files.items():
        target = workspace / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def _build_lens_results(
    metrics: list[AgentExecutionMetric], merged: dict | None
) -> list[EvalCaseLensResult]:
    """One row per canonical lens (LENSES), always -- including lenses that
    ran and found nothing, so "found nothing" and "never got called" are
    distinguishable later. ``merged`` is None exactly when run_verification()
    raised before returning (run_case()'s except block) -- see the
    limitation documented in judge.run_judge_gates: a lens whose own call
    shows status == "ok" in ``metrics`` can still have unknowable
    defect_count/schema_valid, because a LATER lens's exception discarded
    the parsed critics before merge() ever ran.
    """
    by_lens = {m.agent_name.removeprefix("judge:"): m for m in metrics if m.agent_name.startswith("judge:")}

    defect_counts: dict[str, int] = {}
    schema_errors: list[str] = []
    if merged is not None:
        for d in merged.get("defects", []):
            lens = d.get("lens")
            if lens:
                defect_counts[lens] = defect_counts.get(lens, 0) + 1
        schema_errors = merged.get("schema_errors", [])

    results: list[EvalCaseLensResult] = []
    for lens in LENSES:
        metric = by_lens.get(lens)
        if metric is None:
            results.append(EvalCaseLensResult(lens=lens, call_status="not_run", defect_count=None, schema_valid=None))
        elif metric.status == "error":
            results.append(
                EvalCaseLensResult(
                    lens=lens, call_status="error", defect_count=None, schema_valid=None, error=metric.error
                )
            )
        elif merged is None:
            results.append(EvalCaseLensResult(lens=lens, call_status="ok", defect_count=None, schema_valid=None))
        else:
            schema_valid = not any(err.startswith(f"judge:{lens}:") for err in schema_errors)
            results.append(
                EvalCaseLensResult(
                    lens=lens,
                    call_status="ok",
                    defect_count=defect_counts.get(lens, 0),
                    schema_valid=schema_valid,
                )
            )
    return results


def run_case(
    case: EvalCase,
    *,
    gateway: LLMGateway,
    budget: BudgetController,
    judge_model: str,
    conn: sqlite3.Connection,
    run_id: int,
    eval_run_id: int,
    timeout_seconds: float | None = None,
) -> EvalCaseResult:
    # Deterministic, not random: reproducible for debugging, and unique
    # across every eval run ever (eval_run_id is a fresh autoincrement each
    # time) -- this exact string is also what gets passed as task_id to
    # run_verification(), so agent_execution_metrics rows for this case are
    # found later by an explicit (run_id, task_id) match, never inference.
    task_id = f"eval-{eval_run_id}-{case.eval_case_id}"

    EVAL_ROOT.mkdir(parents=True, exist_ok=True)
    workspace = EVAL_ROOT / task_id
    workspace.mkdir(parents=True, exist_ok=True)

    error: str | None = None
    actual_verdict = "UNVERIFIED"
    detected_categories: list[str] = []
    # None/[] until run_verification() actually returns -- if it raises
    # partway through, these stay at their initial values (same all-or-
    # nothing loss as detected_categories above: the exception unwinds
    # past the point where any of these were ever assigned).
    merged: dict | None = None
    automated_results: list[VerificationResult] = []
    # Populated via callback as each lens fails, not from run_verification()'s
    # return value -- so unlike `merged`/detected_categories above, a LATER
    # lens's exception does not discard failures already captured from
    # earlier lenses in the same case.
    schema_failures: list[EvalCaseSchemaFailure] = []

    def _collect_schema_failure(lens_name: str, raw_response: str, errors: list[str]) -> None:
        schema_failures.append(
            EvalCaseSchemaFailure(
                lens=lens_name, error_detail="\n".join(errors), raw_response=raw_response or ""
            )
        )

    try:
        _write_case_files(workspace, case.files)
        status, merged, automated_results = run_verification(
            workspace,
            gateway,
            budget,
            judge_model,
            case.task_text,
            run_id=run_id,
            task_id=task_id,
            conn=conn,
            timeout_seconds=timeout_seconds,
            on_schema_failure=_collect_schema_failure,
        )
        actual_verdict = status
        detected_categories = sorted(
            {d.get("category") for d in merged.get("defects", []) if d.get("category")}
        )
    except Exception as exc:  # noqa: BLE001 - one bad case must never abort the other 39
        error = f"{type(exc).__name__}: {exc}"
    finally:
        shutil.rmtree(workspace, ignore_errors=True)

    # SUM of whatever metric rows exist for this task_id -- if error is set,
    # this may reflect only the lenses that completed before the failure,
    # not a full 3-lens measurement. Still real cost that was spent.
    metrics = db.get_agent_execution_metrics_by_task(conn, run_id, task_id)
    cost = sum((m.actual_spend for m in metrics if m.actual_spend is not None), start=Decimal(0))
    latency_ms = sum(m.latency_ms for m in metrics)

    passed = error is None and actual_verdict == case.expected_verdict

    return EvalCaseResult(
        eval_run_id=eval_run_id,
        eval_case_id=case.eval_case_id,
        task_id=task_id,
        expected_verdict=case.expected_verdict,
        actual_verdict=actual_verdict,
        expected_defect_category=case.expected_defect_category,
        detected_defect_categories=detected_categories,
        latency_ms=latency_ms,
        cost=cost,
        passed=passed,
        error=error,
        defects=merged.get("defects", []) if merged is not None else [],
        lens_results=_build_lens_results(metrics, merged),
        automated_gate_results=automated_results,
        schema_failures=schema_failures,
    )


def _aggregate(cases: list[EvalCase], results: list[EvalCaseResult]) -> dict:
    """total_cost/average_cost sum over ALL results, including error rows --
    partial cost is still real cost. correct_verdicts/false_pass/
    false_unverified/category_accuracy only ever consider non-error rows --
    a case the harness couldn't even complete says nothing about whether
    the judge would have gotten the verdict right.
    """
    category_by_case_id = {c.eval_case_id: c.category for c in cases}
    non_error = [r for r in results if r.error is None]

    correct_verdicts = sum(1 for r in non_error if r.actual_verdict == r.expected_verdict)
    false_pass = sum(
        1 for r in non_error if r.expected_verdict == "UNVERIFIED" and r.actual_verdict == "OK"
    )
    false_unverified = sum(
        1 for r in non_error if r.expected_verdict == "OK" and r.actual_verdict == "UNVERIFIED"
    )

    by_category: dict[str, list[EvalCaseResult]] = {}
    for r in non_error:
        by_category.setdefault(category_by_case_id[r.eval_case_id], []).append(r)
    category_accuracy = {
        cat: sum(1 for r in rs if r.actual_verdict == r.expected_verdict) / len(rs)
        for cat, rs in by_category.items()
    }

    total_cost = sum((r.cost for r in results), start=Decimal(0))
    average_cost = total_cost / len(results) if results else Decimal(0)
    average_latency = sum(r.latency_ms for r in results) // len(results) if results else 0

    return {
        "total_cases": len(results),
        "correct_verdicts": correct_verdicts,
        "false_pass": false_pass,
        "false_unverified": false_unverified,
        "category_accuracy": category_accuracy,
        "average_cost": average_cost,
        "average_latency": average_latency,
        "total_cost": total_cost,
    }


def run_benchmark(
    *,
    config: Config,
    provider_name: str,
    judge_model: str,
    category: str | None = None,
) -> tuple[EvalRun, list[EvalCaseResult]]:
    cases = select_cases(category)
    gateway = LLMGateway.from_config(provider_name, config)
    budget = BudgetController(max_tokens=BENCHMARK_MAX_TOKENS, planned_budget=BENCHMARK_PLANNED_BUDGET)
    git_commit_sha = get_git_commit_sha()

    with db.connect(config.db_path) as conn:
        run_id = db.create_run(conn, f"eval:{BENCHMARK_NAME}", provider_name, judge_model)
        eval_run_id = db.create_eval_run(
            conn, git_commit_sha, BENCHMARK_NAME, BENCHMARK_VERSION, DATASET_VERSION
        )
        conn.commit()

        results: list[EvalCaseResult] = []
        for case in cases:
            result = run_case(
                case,
                gateway=gateway,
                budget=budget,
                judge_model=judge_model,
                conn=conn,
                run_id=run_id,
                eval_run_id=eval_run_id,
            )
            eval_case_result_id = db.record_eval_case_result(conn, result)
            db.record_eval_case_defects(conn, eval_case_result_id, result.defects)
            db.record_eval_case_lens_results(conn, eval_case_result_id, result.lens_results)
            db.record_eval_case_automated_gates(conn, eval_case_result_id, result.automated_gate_results)
            db.record_eval_case_schema_failures(conn, eval_case_result_id, result.schema_failures)
            conn.commit()
            results.append(result)

        db.finish_eval_run(conn, eval_run_id, **_aggregate(cases, results))
        db.finish_run(conn, run_id, "passed", len(results))
        conn.commit()

        eval_run = db.get_eval_run(conn, eval_run_id)
        assert eval_run is not None

    return eval_run, results
