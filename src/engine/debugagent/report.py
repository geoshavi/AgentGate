"""The Debug Agent's final report: three kinds of claim, kept apart.

The Coding Agent's report keeps two status fields separate because "the agent
says it is done" and "AgentGate says it is correct" are different claims. A
debug run has a third, and mixing any of them is how a demo ends up believing a
model's narration over its own ledger:

    observed    what the harness ran and watched -- exit codes, the mutation
                ledger, the reproduction before and after, the suite
    claimed     what a model asserted -- the root cause text, the fix summary
    agentgate   what verification concluded -- OK/UNVERIFIED, defects, gates

They are three nested objects rather than three prefixes on a flat record, so
the separation survives serialisation: a reader of ``report.json`` cannot pick
up ``claimed.root_cause.summary`` under the impression it was measured, and a
renderer cannot accidentally promote a sentence into a verdict.

Nothing in this module decides anything. ``status`` arrives already computed by
``app.py`` from two booleans -- the proof gate and AgentGate -- and there is no
code path here that can change it.

One field crosses the boundary and is called out where it lives: the
``confidence`` inside ``claimed.root_cause`` is *computed by the harness* from
the captured traceback, never accepted from the model. It sits inside the
claimed block because it qualifies a claim, not because it is one.
"""

import json
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any

from engine.codeagent.state import Phase, SessionStatus
from engine.codeagent.verify import VerificationOutcome
from engine.debugagent.fix import FixOutcome, ProofStatus
from engine.debugagent.repro import FrozenRepro, ReproOutcome
from engine.debugagent.rootcause import DiagnosisOutcome

# What a section says when its phase was never reached. Distinct from UNPROVEN,
# which means the commands ran and disagreed with the model.
NOT_REACHED = "NOT_REACHED"


@dataclass(frozen=True)
class DebugRun:
    """Everything one debug run produced, before it is shaped into a report.

    Assembled by ``app.py`` as the phases complete. Phase outcomes are ``None``
    when that phase was never reached -- absent rather than empty, so a report
    can never show "diagnosis found nothing" for a run that aborted before
    diagnosis existed.
    """

    task_id: str
    workspace: str
    task_text: str
    repro: FrozenRepro
    suite: FrozenRepro
    status: SessionStatus
    reason: str
    phase: Phase
    repro_outcome: ReproOutcome | None = None
    diagnosis: DiagnosisOutcome | None = None
    fix: FixOutcome | None = None
    verification: VerificationOutcome | None = None
    files_changed: list[str] = field(default_factory=list)
    files_inspected: list[str] = field(default_factory=list)
    elapsed_ms: int = 0
    tokens_spent: int = 0
    spend: Decimal = Decimal(0)
    run_id: int | None = None


@dataclass(frozen=True)
class ObservedFacts:
    """Things the harness ran and watched. No sentence here came from a model.

    ``repro_before`` is the reproduction that opened the gate, failing by
    definition. ``repro_after`` and ``suite_after`` are None when the proof gate
    never ran them -- a fabricated record would imply a command that never
    executed.
    """

    reproduced: bool
    repro_status: str
    evidence: dict[str, Any] | None
    repro_before: dict[str, Any] | None
    repro_after: dict[str, Any] | None
    suite_after: dict[str, Any] | None
    proof_status: str  # PROVEN | UNPROVEN | ABORTED | NOT_REACHED
    proof_stage: str
    proof_reason: str
    # From the workspace ledger, never from what a model said it changed.
    files_changed: list[str] = field(default_factory=list)
    files_inspected: list[str] = field(default_factory=list)
    commands_run: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    repair_rounds: int = 0
    fix_session_status: str = ""
    turns_used: int = 0
    tool_calls: int = 0


@dataclass(frozen=True)
class ModelClaims:
    """Assertions. Every field here is something a model said.

    The one exception is ``root_cause["confidence"]``, which D2 computes from
    the captured traceback and which is discarded if the model supplies it. It
    lives here because it qualifies a claim, not because it is one.

    ``fix_summary`` is the fixing session's own closing sentence. It is reported
    because a reader wants to know what the agent thought it did, and it is
    reported *here* because it has no bearing on the verdict: a session ending
    "fixed the bug" while the reproduction still fails is UNPROVEN.
    """

    root_cause: dict[str, Any] | None
    diagnosis_status: str
    diagnosis_attempts: int
    diagnosis_errors: list[str] = field(default_factory=list)
    fix_summary: str = ""


@dataclass(frozen=True)
class AgentGateResult:
    """AgentGate's verdict, unchanged and un-reinterpreted.

    ``ran`` separates "verification produced a verdict" from "verification was
    never asked" -- both can be UNVERIFIED, and only the first carries evidence.
    ``status`` is None when the run never reached verification at all.
    """

    ran: bool
    status: str | None
    reason: str
    defects: list[dict[str, Any]] = field(default_factory=list)
    automated_gates: list[dict[str, Any]] = field(default_factory=list)
    schema_errors: list[str] = field(default_factory=list)
    snapshot_files: int = 0
    snapshot_bytes: int = 0


@dataclass(frozen=True)
class UsageTotals:
    """What the run cost.

    ``model_calls`` and the token fields count the *agent* phases -- diagnosis
    and fixing -- from each phase's own per-call accounting. Judge lens calls
    are not included there, because neither phase can see them.
    ``tokens_spent`` and ``spend`` come from the shared BudgetController and do
    cover the whole run, judges included. They are different measurements of
    different things and are reported as such rather than reconciled into one
    number that would be wrong for both.
    """

    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    tokens_spent: int = 0
    spend: str = "0"
    elapsed_ms: int = 0


@dataclass(frozen=True)
class DebugReport:
    task_id: str
    run_id: int | None
    workspace: str
    reported_bug: str
    repro_command: list[str]
    suite_command: list[str]

    # The deterministic verdict. PASSED requires the proof gate AND AgentGate;
    # see app.py, the only place that computes it.
    status: str
    reason: str
    phase_reached: str

    observed: ObservedFacts
    claimed: ModelClaims
    agentgate: AgentGateResult
    usage: UsageTotals

    @property
    def passed(self) -> bool:
        return self.status == SessionStatus.PASSED.value

    @property
    def proven(self) -> bool:
        return self.observed.proof_status == ProofStatus.PROVEN.value

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)


def build_debug_report(run: DebugRun) -> DebugReport:
    """Shape a finished run into the report. Computes no verdict."""
    fix = run.fix
    proof = fix.proof if fix is not None else None
    evidence = run.repro_outcome.evidence if run.repro_outcome is not None else None

    return DebugReport(
        task_id=run.task_id,
        run_id=run.run_id,
        workspace=run.workspace,
        reported_bug=run.task_text,
        repro_command=run.repro.as_list(),
        suite_command=run.suite.as_list(),
        status=run.status.value,
        reason=run.reason,
        phase_reached=run.phase.value,
        observed=ObservedFacts(
            reproduced=bool(run.repro_outcome and run.repro_outcome.reproduced),
            repro_status=run.repro_outcome.status.value if run.repro_outcome else NOT_REACHED,
            evidence=evidence.as_dict() if evidence is not None else None,
            repro_before=_repro_before(evidence),
            repro_after=_command(proof.repro_after) if proof is not None else None,
            suite_after=_command(proof.suite_after) if proof is not None else None,
            proof_status=fix.status.value if fix is not None else NOT_REACHED,
            proof_stage=proof.stage if proof is not None else NOT_REACHED,
            proof_reason=fix.reason if fix is not None else "the fix phase was not reached",
            files_changed=list(run.files_changed),
            files_inspected=list(run.files_inspected),
            commands_run=list(fix.commands_run) if fix is not None else [],
            tool_results=list(fix.tool_results) if fix is not None else [],
            repair_rounds=fix.repairs_used if fix is not None else 0,
            fix_session_status=fix.session_status.value if fix is not None else "",
            turns_used=fix.turns_used if fix is not None else 0,
            tool_calls=fix.tool_calls if fix is not None else 0,
        ),
        claimed=ModelClaims(
            root_cause=_root_cause(run),
            diagnosis_status=run.diagnosis.status.value if run.diagnosis else NOT_REACHED,
            diagnosis_attempts=run.diagnosis.attempts if run.diagnosis else 0,
            diagnosis_errors=list(run.diagnosis.errors) if run.diagnosis else [],
            fix_summary=fix.final_summary if fix is not None else "",
        ),
        agentgate=_agentgate(run.verification),
        usage=_usage(run),
    )


def _repro_before(evidence: Any) -> dict[str, Any] | None:
    """The failing reproduction, from the evidence D1 captured.

    Rebuilt from ``FailureEvidence`` rather than a ``CommandRun`` because the
    gate records the observation, not the process handle -- and the fields a
    reader needs (argv, exit code, timeout, duration) are all on it.
    """
    if evidence is None:
        return None
    return {
        "argv": list(evidence.argv),
        "exit_code": evidence.exit_code,
        "timed_out": evidence.timed_out,
        "duration_ms": evidence.duration_ms,
    }


def _command(record: Any) -> dict[str, Any] | None:
    if record is None:
        return None
    return {
        "argv": list(record.argv),
        "exit_code": record.exit_code,
        "timed_out": record.timed_out,
        "duration_ms": record.duration_ms,
    }


def _root_cause(run: DebugRun) -> dict[str, Any] | None:
    """Prefer the fix phase's copy: it is the one that was actually worked from."""
    if run.fix is not None and run.fix.root_cause is not None:
        return run.fix.root_cause.as_dict()
    if run.diagnosis is not None and run.diagnosis.root_cause is not None:
        return run.diagnosis.root_cause.as_dict()
    return None


def _agentgate(outcome: VerificationOutcome | None) -> AgentGateResult:
    if outcome is None:
        return AgentGateResult(
            ran=False, status=None, reason="AgentGate verification was not reached"
        )
    return AgentGateResult(
        ran=outcome.ran,
        status=outcome.status,
        reason=outcome.reason,
        defects=list(outcome.defects),
        automated_gates=[
            {"gate": result.gate_name, "passed": result.passed, "detail": result.detail}
            for result in outcome.automated_gates
        ],
        schema_errors=list(outcome.schema_errors),
        snapshot_files=len(outcome.scope.files) if outcome.scope else 0,
        snapshot_bytes=outcome.scope.total_bytes if outcome.scope else 0,
    )


def _usage(run: DebugRun) -> UsageTotals:
    phases: list[DiagnosisOutcome | FixOutcome] = [
        phase for phase in (run.diagnosis, run.fix) if phase is not None
    ]
    return UsageTotals(
        model_calls=sum(phase.model_calls for phase in phases),
        input_tokens=sum(phase.input_tokens for phase in phases),
        output_tokens=sum(phase.output_tokens for phase in phases),
        thinking_tokens=sum(phase.thinking_tokens for phase in phases),
        tokens_spent=run.tokens_spent,
        spend=str(run.spend),
        elapsed_ms=run.elapsed_ms,
    )


def render_debug_report(report: DebugReport) -> str:
    """Terminal rendering, ordered so measured facts come before claims.

    The observed block leads, then AgentGate, then -- clearly labelled -- what a
    model said. A reader skimming the top of this output cannot come away with a
    model's sentence as the headline.
    """
    observed = report.observed
    gate = report.agentgate

    lines = [
        f"session   {report.task_id}    workspace {report.workspace}",
        f"repro     {' '.join(report.repro_command)}",
        f"suite     {' '.join(report.suite_command)}",
        "",
        "-- observed (commands, exit codes, ledger) --",
    ]
    before = observed.repro_before
    lines.append(
        f"reproduce {observed.repro_status}"
        + (f"   exit {before['exit_code']}" if before is not None else "")
    )
    if observed.evidence is not None and observed.evidence.get("summary"):
        lines.append(f"          {observed.evidence['summary']}")
    lines.append(f"proof     {observed.proof_status}  ({observed.proof_reason})")
    if observed.repro_after is not None:
        lines.append(f"  repro   exit {observed.repro_after['exit_code']}")
    if observed.suite_after is not None:
        lines.append(f"  suite   exit {observed.suite_after['exit_code']}")
    lines.append(
        f"changed   {', '.join(observed.files_changed) or '(none)'}"
        f"   [{len(observed.files_changed)} file(s), from the ledger]"
    )
    lines.append(
        f"work      {observed.turns_used} turn(s), {observed.tool_calls} tool call(s), "
        f"{observed.repair_rounds} repair round(s), {len(observed.commands_run)} command(s)"
    )

    lines += ["", "-- AgentGate verification --"]
    lines.append(f"gate      {gate.status or 'NOT REACHED'}  ({gate.reason})")
    for entry in gate.automated_gates:
        if not entry["passed"]:
            lines.append(f"  gate    {entry['gate']} FAILED")
    for defect in gate.defects:
        lines.append(
            f"  defect  [{defect.get('category')}/{defect.get('severity')}] "
            f"{defect.get('location')}: {defect.get('fix')}"
        )
    for error in gate.schema_errors:
        lines.append(f"  schema  {error}")

    lines += ["", "-- claimed by the model (not evidence) --"]
    cause = report.claimed.root_cause
    if cause is None:
        lines.append(f"cause     none ({report.claimed.diagnosis_status})")
    else:
        lines.append(f"cause     {cause['summary']}")
        lines.append(f"          at {cause['primary_file']}:{cause['primary_line']}")
        lines.append(f"          mechanism: {cause['mechanism']}")
        lines.append(f"          fix: {cause['proposed_fix']}")
        lines.append(f"confidence {cause['confidence']}  (computed from the traceback)")
    if report.claimed.fix_summary:
        lines.append(f"agent     \"{report.claimed.fix_summary}\"")

    usage = report.usage
    lines += [
        "",
        f"verdict   {'PASSED' if report.passed else report.status}   {report.reason}",
        (
            f"usage     {usage.model_calls} model call(s), {usage.tokens_spent} tokens, "
            f"${usage.spend}, {usage.elapsed_ms} ms"
        ),
    ]
    return "\n".join(lines)


__all__ = [
    "NOT_REACHED",
    "AgentGateResult",
    "DebugReport",
    "DebugRun",
    "ModelClaims",
    "ObservedFacts",
    "UsageTotals",
    "build_debug_report",
    "render_debug_report",
]
