import sqlite3
from collections.abc import Callable
from pathlib import Path

from engine.runtime.budget import BudgetController
from engine.runtime.gateway import LLMGateway
from engine.state.models import VerificationResult
from engine.verification import admissibility, verdict
from engine.verification.automated import automated_defects, run_automated_gates
from engine.verification.judge import run_judge_gates


def read_code_snapshot(workspace: Path) -> str:
    parts = []
    for path in sorted(workspace.rglob("*.py")):
        content = path.read_text(encoding="utf-8")
        parts.append(f"# --- {path.relative_to(workspace)} ---\n{content}")
    return "\n\n".join(parts) if parts else "(no code produced)"


def run_verification(
    workspace: Path,
    gateway: LLMGateway,
    budget: BudgetController,
    judge_model: str,
    task_text: str,
    *,
    run_id: int | None,
    task_id: str,
    conn: sqlite3.Connection | None,
    timeout_seconds: float | None = None,
    on_schema_failure: Callable[[str, str, list[str]], None] | None = None,
    adjudicate: bool = False,
) -> tuple[str, dict, list[VerificationResult]]:
    """Run the automated + LLM-judge lenses and return the deterministic verdict.

    The LLM judges only ever produce structured defects; ``verdict.gate`` (pure
    Python, no model call) is the sole function allowed to decide pass/fail.
    Returns (status, merged_critic, automated_results).

    ``on_schema_failure`` is an optional diagnostics hook (lens_name,
    raw_response, errors) -> None, forwarded to run_judge_gates unchanged.
    None by default -- production callers (api.py, orchestrator/engine.py)
    never pass it, so their behavior is unaffected; only eval/runner.py does.

    ``adjudicate`` is off by default and no caller passes it yet. When off,
    ``merged`` carries no admissibility keys and ``verdict.gate`` behaves
    exactly as it did before the adjudication layer existed. When on, each
    blocking defect is annotated with ``admissible_to_block``; a deterministic
    contradiction can drop one out of the blocking set, but nothing is removed
    from ``merged["defects"]``, so reporting and retry feedback are unchanged.
    Note the ordering: schema errors and automated-gate failures are still
    evaluated first inside ``gate``, so neither can be rescued by admissibility.
    """
    automated_results = run_automated_gates(workspace)
    automated_passed = all(r.passed for r in automated_results)
    script_defects = automated_defects(automated_results)

    code_snapshot = read_code_snapshot(workspace)
    critic_outputs, schema_errors = run_judge_gates(
        gateway,
        budget,
        judge_model,
        task_text,
        code_snapshot,
        run_id=run_id,
        task_id=task_id,
        conn=conn,
        timeout_seconds=timeout_seconds,
        on_schema_failure=on_schema_failure,
    )

    merged = verdict.merge(critic_outputs, script_defects)
    if schema_errors:
        merged = {**merged, "schema_errors": schema_errors}
    if adjudicate:
        merged = admissibility.annotate(merged, task_text, code_snapshot)
    status = verdict.gate(merged, automated_passed, schema_errors)

    return status, merged, automated_results


def build_retry_feedback(merged: dict) -> str:
    lines: list[str] = []

    for d in merged.get("defects", []):
        lines.append(
            f"\n[{d.get('category')}/{d.get('severity')} @ {d.get('location')}]\n{d.get('fix')}"
        )

    for err in merged.get("schema_errors", []):
        lines.append(f"\n[review-schema-error]\n{err}")

    if not lines:
        return ""
    return "The previous attempt failed verification. Fix these issues:" + "".join(lines)
