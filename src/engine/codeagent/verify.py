"""The seam between the Coding Agent and AgentGate verification.

This module calls ``verification.pipeline.run_verification`` **unchanged**: same
signature, no new parameters, no hooks, no wrapper around the judge. All three
lenses, the automated gates, the judge's own retry, and ``verdict.gate``'s sole
ownership of the OK/UNVERIFIED decision are exactly what they were. Nothing here
recomputes a verdict, and nothing here can produce ``PASSED`` except by reading
``run_verification`` returning ``"OK"``.

Two things live on this side of the seam because the other side must not change:

**The snapshot pre-check.** ``read_code_snapshot`` inlines every ``*.py`` under
the workspace into every judge prompt, unbounded. On a real repository that is
a context explosion. Since ``pipeline.py`` is measured-path, the bound belongs
to the caller: measure the same glob first, and above the limit decline to
verify at all. Declining is the only honest option -- truncating the source
would produce a verdict about a program that does not exist, and a verdict on
partial code is worse than no verdict because it looks like one.

**Defect sanitising.** ``enforce_critic_schema`` rejects *missing* defect keys
but not *extra* ones, so a defect dict can legally arrive carrying fields the
schema never described -- including model prose. Everything this module stores
or renders back to the agent is filtered to ``rubric.DEFECT_KEYS`` first. This
does not change any verdict: the severities ``verdict.gate`` saw are the ones it
was given, and filtering happens strictly downstream of the decision.

The repair loop is verification-*driven*: it runs only on real defects from a
verdict that actually happened. When verification could not run -- oversized
snapshot, no changes, verifier failure -- there is no evidence to repair
against, so the run ends UNVERIFIED rather than looping the agent against
nothing.
"""

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

from engine.codeagent.limits import DEFAULT_LIMITS, Limits
from engine.codeagent.log import SessionLog
from engine.codeagent.plan import PlanOutcome
from engine.codeagent.policy import DEFAULT_POLICY, CommandPolicy
from engine.codeagent.session import CodingSession
from engine.codeagent.state import SessionStatus, TaskState
from engine.codeagent.tools.base import Tool
from engine.codeagent.workspace import Workspace
from engine.runtime.budget import BudgetController, BudgetExceededError
from engine.runtime.gateway import LLMGateway
from engine.state.models import VerificationResult
from engine.verification.pipeline import build_retry_feedback, run_verification
from engine.verification.rubric import DEFECT_KEYS

OK = "OK"
UNVERIFIED = "UNVERIFIED"

# Mirrors the per-file header read_code_snapshot writes:
# f"# --- {relative} ---\n{content}", joined by a blank line.
_SNAPSHOT_HEADER_OVERHEAD = 12


@dataclass(frozen=True)
class SnapshotScope:
    """What verification would inline, measured before it is asked to.

    ``total_bytes`` is an over-estimate for non-ASCII source (on-disk bytes vs.
    the characters ``read_text`` yields), which is the safe direction to be
    wrong in for a ceiling.
    """

    files: list[str]
    total_bytes: int
    limit: int

    @property
    def within_limit(self) -> bool:
        return self.total_bytes <= self.limit

    @property
    def is_empty(self) -> bool:
        return not self.files


def snapshot_scope(workspace: Workspace, limits: Limits = DEFAULT_LIMITS) -> SnapshotScope:
    """Measure the snapshot ``read_code_snapshot`` would build.

    Deliberately uses the identical glob (``rglob("*.py")``, sorted) so the
    measurement describes exactly the payload, not an approximation of it. If
    that glob ever changes in pipeline.py this function must change with it --
    which is why it is one line and named after the thing it mirrors.
    """
    files: list[str] = []
    total = 0
    for path in sorted(workspace.root.rglob("*.py")):
        if not path.is_file():
            continue
        relative = path.relative_to(workspace.root).as_posix()
        try:
            total += path.stat().st_size + len(relative) + _SNAPSHOT_HEADER_OVERHEAD
        except OSError:
            continue
        files.append(relative)
    return SnapshotScope(files=files, total_bytes=total, limit=limits.max_snapshot_bytes)


@dataclass(frozen=True)
class VerificationOutcome:
    """The result of one verification attempt.

    ``ran`` separates "the verifier produced a verdict" from "the verifier was
    never asked". Both can be UNVERIFIED, but only the first carries evidence,
    and only the first can drive a repair.
    """

    status: str
    reason: str
    ran: bool = False
    defects: list[dict[str, Any]] = field(default_factory=list)
    schema_errors: list[str] = field(default_factory=list)
    automated_gates: list[VerificationResult] = field(default_factory=list)
    scope: SnapshotScope | None = None

    @property
    def passed(self) -> bool:
        return self.status == OK

    @property
    def repairable(self) -> bool:
        """A repair needs something to repair against."""
        return self.ran and not self.passed and bool(self.defects or self.schema_errors)


def sanitize_defects(defects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only the five keys the defect schema defines.

    Strictly downstream of ``verdict.gate``: the verdict was already decided
    from the severities as supplied. This governs what the agent is shown and
    what the report stores, and exists because the schema permits extra keys
    that could carry model prose.
    """
    return [
        {key: defect[key] for key in sorted(DEFECT_KEYS) if key in defect}
        for defect in defects
        if isinstance(defect, dict)
    ]


def verify_workspace(
    *,
    workspace: Workspace,
    task_text: str,
    gateway: LLMGateway,
    budget: BudgetController,
    judge_model: str,
    task_id: str,
    run_id: int | None = None,
    conn: sqlite3.Connection | None = None,
    limits: Limits = DEFAULT_LIMITS,
    changed_files: list[str] | None = None,
    log: SessionLog | None = None,
    verifier: Callable[..., tuple[str, dict, list[VerificationResult]]] = run_verification,
) -> VerificationOutcome:
    """Pre-check, then hand the workspace to AgentGate unchanged.

    ``changed_files`` is the workspace ledger -- a record of writes that
    happened. The model's own claim about what it changed is never consulted
    here; it is an assertion, and the point of verification is not to take
    assertions.

    ``verifier`` defaults to the real pipeline and exists so control-flow tests
    can drive every branch without a provider. Production callers never pass it.
    """
    sink = log if log is not None else SessionLog()
    scope = snapshot_scope(workspace, limits)

    if changed_files is not None and not changed_files:
        # Verification never runs. The agent declared itself finished having
        # written nothing, which the existing engine also treats as a blocking
        # outcome (manager.py's _no_code_verdict). Asking three judges to
        # review a repository the agent did not touch would attribute someone
        # else's code to this run.
        return _declined(
            sink, scope, "the agent changed no files; there is nothing to verify"
        )

    if scope.is_empty:
        return _declined(sink, scope, "the workspace contains no Python files to verify")

    if not scope.within_limit:
        return _declined(
            sink,
            scope,
            f"workspace snapshot is {scope.total_bytes} B across {len(scope.files)} files, "
            f"over max_snapshot_bytes ({scope.limit}); refusing to verify rather than "
            "verify truncated source",
        )

    sink.emit(
        "verification_start",
        0,
        files=len(scope.files),
        snapshot_bytes=scope.total_bytes,
        changed_files=changed_files or [],
    )

    try:
        status, merged, automated = verifier(
            workspace.root,
            gateway,
            budget,
            judge_model,
            task_text,
            run_id=run_id,
            task_id=task_id,
            conn=conn,
            timeout_seconds=limits.command_timeout_seconds,
        )
    except BudgetExceededError as exc:
        return _failed_closed(sink, scope, f"budget exhausted during verification: {exc}")
    except Exception as exc:  # noqa: BLE001 - fail closed, never pass on a broken verifier
        return _failed_closed(
            sink, scope, f"verification failed: {type(exc).__name__}: {exc}"
        )

    defects = sanitize_defects(merged.get("defects", []) or [])
    schema_errors = list(merged.get("schema_errors", []) or [])
    reason = (
        "AgentGate verification passed"
        if status == OK
        else _blocked_reason(defects, schema_errors, automated)
    )
    sink.emit(
        "verification_result",
        0,
        status=status,
        defects=len(defects),
        schema_errors=len(schema_errors),
        gates={result.gate_name: result.passed for result in automated},
    )
    return VerificationOutcome(
        status=status,
        reason=reason,
        ran=True,
        defects=defects,
        schema_errors=schema_errors,
        automated_gates=list(automated),
        scope=scope,
    )


def _declined(sink: SessionLog, scope: SnapshotScope, reason: str) -> VerificationOutcome:
    sink.emit("verification_declined", 0, reason=reason, snapshot_bytes=scope.total_bytes)
    return VerificationOutcome(status=UNVERIFIED, reason=reason, ran=False, scope=scope)


def _failed_closed(sink: SessionLog, scope: SnapshotScope, reason: str) -> VerificationOutcome:
    sink.emit("verification_error", 0, reason=reason)
    return VerificationOutcome(status=UNVERIFIED, reason=reason, ran=False, scope=scope)


def _blocked_reason(
    defects: list[dict[str, Any]], schema_errors: list[str], automated: list[VerificationResult]
) -> str:
    parts: list[str] = []
    blocking = [d for d in defects if d.get("severity") in ("CRITICAL", "HIGH")]
    if blocking:
        parts.append(f"{len(blocking)} blocking defect(s)")
    failed_gates = [result.gate_name for result in automated if not result.passed]
    if failed_gates:
        parts.append(f"failed gate(s): {', '.join(failed_gates)}")
    if schema_errors:
        parts.append(f"{len(schema_errors)} malformed judge response(s)")
    return "AgentGate verification blocked: " + ("; ".join(parts) or "verdict was not OK")


def render_repair_feedback(outcome: VerificationOutcome) -> str:
    """Structured verification evidence, as the agent's next instruction.

    Built by ``pipeline.build_retry_feedback`` -- the same renderer the legacy
    retry loop uses, so repair feedback has one implementation rather than two.
    It reads only category, severity, location and fix, and it is handed
    already-sanitised defects, so nothing outside the defect schema can reach
    the agent. No judge prose, no lens identity, no reasoning.
    """
    merged = {"defects": outcome.defects, "schema_errors": outcome.schema_errors}
    return build_retry_feedback(merged)


# -- the verified run -------------------------------------------------------


@dataclass(frozen=True)
class VerifiedRun:
    """One task: an agent session, a verdict, and any repair rounds between.

    ``agent_status`` is what the agent did; ``status`` is what AgentGate
    concluded. They are separate fields because they are separate claims, and
    collapsing them is exactly the error this whole layer exists to prevent.
    """

    status: SessionStatus
    agent_status: SessionStatus
    states: list[TaskState]
    verification: VerificationOutcome | None
    repairs_used: int = 0

    @property
    def final_state(self) -> TaskState:
        return self.states[-1]

    @property
    def reason(self) -> str:
        """Why the run ended, at run level.

        The verification outcome's reason when there was one; otherwise the
        agent's own, which is the case where it aborted before there was
        anything to verify.
        """
        if self.verification is not None:
            return self.verification.reason
        return self.final_state.stop_reason or ""


def run_verified_session(
    *,
    task_text: str,
    workspace: Workspace,
    gateway: LLMGateway,
    budget: BudgetController,
    model: str,
    judge_model: str,
    task_id: str,
    run_id: int | None = None,
    conn: sqlite3.Connection | None = None,
    limits: Limits = DEFAULT_LIMITS,
    policy: CommandPolicy = DEFAULT_POLICY,
    tools: dict[str, Tool] | None = None,
    log: SessionLog | None = None,
    clock: Callable[[], float] = time.monotonic,
    planning: PlanOutcome | None = None,
    verifier: Callable[..., tuple[str, dict, list[VerificationResult]]] = run_verification,
) -> VerifiedRun:
    """Run the agent, verify its work, and repair against real defects.

    The workspace is never reset between rounds: a repair continues from the
    accumulated diff, which is the whole point of an editing agent and the
    reason this loop could not be a fifth entry in the legacy AGENT_REGISTRY
    (manager.py wipes the workspace before every attempt).

    Turn and time allowances are shared across rounds rather than granted afresh
    to each, so repairs cannot extend a session past its own bounds. The budget
    is shared for free -- one BudgetController serves every round and every
    judge call.
    """
    sink = log if log is not None else SessionLog()
    started = clock()
    states: list[TaskState] = []

    session = CodingSession(
        task_text=task_text,
        workspace=workspace,
        gateway=gateway,
        budget=budget,
        model=model,
        task_id=task_id,
        run_id=run_id,
        conn=conn,
        limits=limits,
        policy=policy,
        tools=tools,
        log=sink,
        clock=clock,
        planning=planning,
    )
    state = session.run()
    states.append(state)

    if state.status is not SessionStatus.COMPLETED_UNVERIFIED:
        # The agent never got to the point of claiming it was done, so there is
        # nothing to verify. Its own terminal status stands.
        return VerifiedRun(
            status=state.status, agent_status=state.status, states=states, verification=None
        )

    agent_status = state.status
    outcome = _verify(
        workspace, task_text, gateway, budget, judge_model, task_id, run_id, conn,
        limits, state, sink, verifier,
    )
    repairs = 0

    while not outcome.passed and outcome.repairable and repairs < limits.max_repair_rounds:
        remaining_turns = limits.max_turns - sum(s.usage.turns_used for s in states)
        remaining_seconds = limits.session_timeout_seconds - (clock() - started)
        if remaining_turns <= 0 or remaining_seconds <= 0:
            outcome = replace(
                outcome,
                reason=f"{outcome.reason}; no turn or time allowance left for a repair round",
            )
            break

        repairs += 1
        sink.emit("repair_start", 0, round=repairs, defects=len(outcome.defects))
        repair_session = CodingSession(
            task_text=task_text,
            workspace=workspace,  # same instance: the ledger and the diff survive
            gateway=gateway,
            budget=budget,
            model=model,
            task_id=task_id,
            run_id=run_id,
            conn=conn,
            limits=replace(
                limits, max_turns=remaining_turns, session_timeout_seconds=remaining_seconds
            ),
            policy=policy,
            tools=tools,
            log=sink,
            clock=clock,
            planning=planning,
            repair_feedback=render_repair_feedback(outcome),
        )
        state = repair_session.run()
        states.append(state)

        if state.status is not SessionStatus.COMPLETED_UNVERIFIED:
            # The repair round hit a bound or failed. The last real verdict
            # stands; re-verifying an abandoned round would not improve it.
            outcome = replace(
                outcome,
                reason=f"{outcome.reason}; repair round {repairs} ended "
                f"{state.status.value}: {state.stop_reason}",
            )
            break

        outcome = _verify(
            workspace, task_text, gateway, budget, judge_model, task_id, run_id, conn,
            limits, state, sink, verifier,
        )

    if not outcome.passed and outcome.repairable and 1 <= limits.max_repair_rounds <= repairs:
        outcome = replace(
            outcome, reason=f"{outcome.reason}; repair budget exhausted after {repairs} round(s)"
        )

    final_status = SessionStatus.PASSED if outcome.passed else SessionStatus.UNVERIFIED
    _record(states[-1], outcome, repairs)
    sink.emit(
        "run_result",
        0,
        agent_status=agent_status.value,
        status=final_status.value,
        reason=outcome.reason,
        repairs_used=repairs,
    )
    return VerifiedRun(
        status=final_status,
        agent_status=agent_status,
        states=states,
        verification=outcome,
        repairs_used=repairs,
    )


def _verify(
    workspace: Workspace,
    task_text: str,
    gateway: LLMGateway,
    budget: BudgetController,
    judge_model: str,
    task_id: str,
    run_id: int | None,
    conn: sqlite3.Connection | None,
    limits: Limits,
    state: TaskState,
    sink: SessionLog,
    verifier: Callable[..., tuple[str, dict, list[VerificationResult]]],
) -> VerificationOutcome:
    return verify_workspace(
        workspace=workspace,
        task_text=task_text,
        gateway=gateway,
        budget=budget,
        judge_model=judge_model,
        task_id=task_id,
        run_id=run_id,
        conn=conn,
        limits=limits,
        changed_files=state.files_changed,
        log=sink,
        verifier=verifier,
    )


def _record(state: TaskState, outcome: VerificationOutcome, repairs: int) -> None:
    """Attach the run-level verdict to the final round's state.

    Deliberately does NOT overwrite ``status`` or ``stop_reason``: those belong
    to the round, and a repair round that ended ABORTED_PROTOCOL must keep
    saying so. The run-level verdict lives on ``VerifiedRun`` instead, which is
    why the two are separate objects. Only fields the round left unset are
    filled in here.
    """
    state.verification_status = outcome.status
    state.verification_defects = outcome.defects
    state.usage.repairs_used = repairs
