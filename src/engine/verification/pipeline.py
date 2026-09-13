import sqlite3
from collections.abc import Callable
from pathlib import Path

from engine.runtime.budget import BudgetController
from engine.runtime.gateway import LLMGateway
from engine.state.models import VerificationResult
from engine.verification import admissibility, verdict
from engine.verification.automated import automated_defects, run_automated_gates
from engine.verification.evidence_mining import (
    mine_return_value_evidence,
    mine_trigger_evidence,
)
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
    shadow_adjudicate: bool = False,
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
    defect is first offered the same mined evidence the shadow path computes
    (see ``_authoritative_defects`` / ``_with_mined_evidence`` -- identical
    precedence, identical fail-closed-on-ambiguity rule, no second
    implementation of Route A/B), then annotated with
    ``admissible_to_block``; a deterministic contradiction can drop one out
    of the blocking set. Nothing is removed from ``merged["defects"]`` --
    only evidence keys (e.g. ``minimal_trigger``) are added to entries where
    mining found something -- so reporting and retry feedback still show
    every defect. Note the ordering: schema errors and automated-gate
    failures are still evaluated first inside ``gate``, so neither can be
    rescued by admissibility.

    ``shadow_adjudicate`` is the *observation-only* counterpart, and is a
    deliberately separate flag rather than a mode of ``adjudicate``. It computes
    the same adjudication records but leaves ``merged["defects"]`` untouched, so
    nothing it concludes can reach ``verdict._has_blocking``; the records travel
    out under the separate ``merged["shadow_adjudications"]`` key. The
    authoritative verdict is byte-identical to ``shadow_adjudicate=False`` on the
    same inputs -- that equivalence is what the flag exists to preserve, and it
    is pinned by tests/test_shadow_adjudication.py.

    Each shadow record is additionally offered a ``minimal_trigger`` mined by
    ``evidence_mining`` from the defect's own existing free text, on a
    throwaway copy built solely for that one record -- see
    ``_select_mined_evidence`` / ``_with_mined_evidence``. Two independent
    routes are tried, in a frozen order (judge-supplied evidence, then
    declared-parameter-type, then declared-return-type;
    COMBINED_CONTRACT_EVIDENCE_MINING_SHADOW_REGISTRATION.md section 3), and
    an unexpected match from both routes at once fails closed rather than
    picking one. This can change what the *shadow* record concludes; it
    changes nothing about ``merged["defects"]`` or the authoritative verdict,
    in shadow mode or otherwise.

    The two flags are mutually exclusive. One annotates the dict the gate reads
    and the other must not; silently ordering them would make it impossible to
    tell from a call site whether admissibility was authoritative.
    """
    if adjudicate and shadow_adjudicate:
        raise ValueError(
            "adjudicate and shadow_adjudicate are mutually exclusive -- "
            "adjudicate makes admissibility authoritative, shadow_adjudicate "
            "records it without effect. Pass exactly one."
        )

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
        merged = {
            **merged,
            "defects": _authoritative_defects(merged, task_text, code_snapshot),
        }
        merged = admissibility.annotate(merged, task_text, code_snapshot)
    elif shadow_adjudicate:
        merged = {
            **merged,
            "shadow_adjudications": _shadow_adjudications(merged, task_text, code_snapshot),
        }
    status = verdict.gate(merged, automated_passed, schema_errors)

    return status, merged, automated_results


def _shadow_adjudications(merged: dict, task_text: str, code_snapshot: str) -> list[dict]:
    """Build sidecar adjudication records without touching a single defect.

    Every defect is recorded, not only the blocking ones, so the shadow data can
    answer questions about evidence availability across the whole population --
    non-blocking defects come back with ``admissible_to_block = None``.

    A failure here is bookkeeping, never verification: if building a record
    raises, that record is dropped and the run continues. Shadow observation must
    not be able to fail a case that would otherwise have been decided.
    """
    records = (
        _shadow_record(defect, task_text, code_snapshot)
        for defect in merged.get("defects", []) or []
        if isinstance(defect, dict)
    )
    return [record for record in records if record is not None]


# Source labels _select_mined_evidence can return -- kept as module-level
# constants so tests and any future diagnostic consumer name them the same
# way the registration does, rather than re-typing string literals.
_SOURCE_JUDGE_SUPPLIED = "judge-supplied"
_SOURCE_ROUTE_A = "route-a"
_SOURCE_ROUTE_B = "route-b"
_SOURCE_AMBIGUOUS = "ambiguous"
_SOURCE_NONE = "none"


def _select_mined_evidence(
    defect: dict, task_text: str, code_snapshot: str
) -> tuple[dict, str]:
    """Decide what evidence, if any, a shadow-only copy of ``defect`` should
    carry, and where it came from.

    Returns ``(evidence, source)``. ``evidence`` is the empty dict unless
    ``source`` is ``"route-a"`` or ``"route-b"`` -- judge-supplied evidence is
    already on ``defect`` and needs nothing added, and an ambiguous
    dual-match fails closed with no evidence applied at all, exactly like no
    match.

    Frozen precedence
    (COMBINED_CONTRACT_EVIDENCE_MINING_SHADOW_REGISTRATION.md section 3):
    judge-supplied ``minimal_trigger`` > Route A (declared-parameter-type,
    ``mine_trigger_evidence``) > Route B (declared-return-type,
    ``mine_return_value_evidence``) > no evidence. If Route A and Route B
    both independently produce evidence for the same defect -- never observed
    in the full v6 historical replay, but not assumed impossible -- neither
    is used: the registration's own STOP rule treats any such overlap as a
    REJECT signal for the whole experiment, so silently picking one here
    would hide exactly the condition that rule exists to catch.
    """
    if defect.get("minimal_trigger"):
        return {}, _SOURCE_JUDGE_SUPPLIED

    route_a = mine_trigger_evidence(defect, task_text, code_snapshot)
    route_b = mine_return_value_evidence(defect, task_text, code_snapshot)

    if route_a and route_b:
        return {}, _SOURCE_AMBIGUOUS
    if route_a:
        return route_a, _SOURCE_ROUTE_A
    if route_b:
        return route_b, _SOURCE_ROUTE_B
    return {}, _SOURCE_NONE


def _with_mined_evidence(defect: dict, task_text: str, code_snapshot: str) -> dict:
    """A copy of ``defect``, augmented with evidence selected by
    ``_select_mined_evidence``'s frozen precedence.

    Never mutates ``defect``. Used by both the shadow path (building a
    throwaway copy for one sidecar record) and the authoritative path
    (building the actual defect that reaches ``admissibility.annotate``) --
    the mining and precedence logic is identical either way; only what the
    caller does with the result differs.
    """
    evidence, _source = _select_mined_evidence(defect, task_text, code_snapshot)
    return {**defect, **evidence} if evidence else defect


def _authoritative_defects(merged: dict, task_text: str, code_snapshot: str) -> list:
    """The real defect list ``admissibility.annotate`` should adjudicate,
    each entry offered the same mined evidence the shadow path computes.

    Mirrors ``_shadow_adjudications``'s iteration exactly, but the result
    replaces ``merged["defects"]`` instead of feeding a sidecar -- this is
    what makes adjudication authoritative rather than observational. A
    defect mining fails to augment (any exception) is passed through
    unmodified rather than dropped: unlike shadow bookkeeping, this list
    still has to reach ``verdict.gate`` complete.
    """
    defects = []
    for defect in merged.get("defects", []) or []:
        if not isinstance(defect, dict):
            defects.append(defect)
            continue
        try:
            defects.append(_with_mined_evidence(defect, task_text, code_snapshot))
        except Exception:  # noqa: BLE001 -- mining must never drop a real defect
            defects.append(defect)
    return defects


def _shadow_record(defect: dict, task_text: str, code_snapshot: str) -> dict | None:
    try:
        shadow_defect = _with_mined_evidence(defect, task_text, code_snapshot)
        return admissibility.adjudication_record(
            shadow_defect, defect.get("lens") or "automated", task_text, code_snapshot
        )
    except Exception:  # noqa: BLE001 -- shadow bookkeeping never breaks a verdict
        return None


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
