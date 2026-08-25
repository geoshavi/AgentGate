"""The final report.

One job, and it is a reporting job rather than a deciding one: assemble what
happened into a structure a person or a later tool can read. Nothing here
computes a verdict, and nothing here can turn a blocked run into a passing one.

The report keeps **two** status fields on purpose:

    agent_status     what the agent did      -- COMPLETED_UNVERIFIED, ABORTED_*
    status           what AgentGate found    -- PASSED, UNVERIFIED

The agent saying "done" is a claim about effort. ``PASSED`` is a claim about
correctness, and only ``verdict.gate`` can make it. Collapsing the two into one
"status" field is the single most tempting simplification here and the one that
would quietly undo the point of the verification layer, so they stay separate
all the way out to JSON.

Totals are summed across every round of a run -- the first session plus each
repair -- because a reader asking "what did this task cost" means the task, not
its last attempt. Per-round detail stays available in ``rounds``.
"""

import json
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any

from engine.codeagent.state import SessionStatus, TaskState
from engine.codeagent.verify import VerifiedRun


@dataclass(frozen=True)
class RoundSummary:
    """One session within a run: the original attempt, or one repair."""

    index: int
    status: str
    stop_reason: str | None
    turns_used: int
    tool_calls: int
    parse_errors: int
    files_changed: list[str]


@dataclass(frozen=True)
class FinalReport:
    task_id: str
    user_goal: str
    workspace: str

    # The two claims, kept apart. See the module docstring.
    status: str  # PASSED | UNVERIFIED -- AgentGate's conclusion
    agent_status: str  # what the agent itself reached
    stop_reason: str

    # Verification evidence.
    verification_ran: bool
    verification_status: str | None
    verification_reason: str
    defects: list[dict[str, Any]] = field(default_factory=list)
    automated_gates: list[dict[str, Any]] = field(default_factory=list)
    schema_errors: list[str] = field(default_factory=list)
    snapshot_files: int = 0
    snapshot_bytes: int = 0

    # What the agent actually did, from the workspace ledger.
    files_changed: list[str] = field(default_factory=list)
    files_inspected: list[str] = field(default_factory=list)
    commands_run: list[dict[str, Any]] = field(default_factory=list)
    test_results: list[dict[str, Any]] = field(default_factory=list)

    # Planning.
    plan: dict[str, Any] | None = None
    planning_status: str | None = None
    planning_attempts: int = 0
    planning_errors: list[str] = field(default_factory=list)

    # Usage, summed across rounds.
    turns_used: int = 0
    tool_calls: int = 0
    parse_errors: int = 0
    repairs_used: int = 0
    tokens_spent: int = 0
    spend: str = "0"

    # Inputs that shaped the run: not a measured fact about the program, not a
    # claim by the model, and not a verdict -- so recorded apart from all three.
    # For C2 only the skills section is populated; later capabilities add
    # siblings rather than reshaping this.
    context_sources: dict[str, Any] = field(default_factory=dict)

    rounds: list[RoundSummary] = field(default_factory=list)
    limits: dict[str, object] = field(default_factory=dict)
    summary: str = ""

    @property
    def passed(self) -> bool:
        return self.status == SessionStatus.PASSED.value

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)


def _context_sources(run: VerifiedRun) -> dict[str, Any]:
    """What entered the model's context besides the workspace and its own turns.

    Names, counts and digests -- never content. A skill body is bounded on the
    way into context precisely so it does not have to be bounded again on the way
    into a report, and storing it here would turn a run record into a transcript.

    ``digests`` maps each disclosed key (``skill`` or ``skill/reference``) to the
    sha256 of the source as read at snapshot, which is what lets a reader say
    exactly which bytes the model saw even when the file on disk has since
    changed. That case is real: a skill root may sit inside the workspace.

    Static fields come from the final state -- discovery happened once, so every
    round carries the same values -- while events accumulate across rounds, the
    way commands_run already does.
    """
    final = run.final_state
    events = [event for state in run.states for event in state.skill_events]
    # The last round that detected anything wins: detection is an observation of
    # the workspace as it then stood, and a repair round re-running it is a fresh
    # answer rather than a second opinion. None throughout means it never ran.
    detection = next(
        (state.test_detection for state in reversed(run.states) if state.test_detection),
        None,
    )
    return {
        "test_detection": detection,
        "skills": {
            "advertised": list(final.advertised_skills),
            "loaded": [name for state in run.states for name in state.loaded_skills],
            "references": [
                key for state in run.states for key in state.loaded_skill_references
            ],
            "chars": sum(state.skill_chars for state in run.states),
            "events": events,
            "errors": list(final.skill_discovery_errors),
            "shadowed": list(final.skill_shadowed),
            "roots": list(final.skill_roots),
            "mutations": list(final.skill_source_mutations),
            "digests": {
                event["name"]
                if event["reference"] is None
                else f"{event['name']}/{event['reference']}": event["digest"]
                for event in events
                if event["digest"]
            },
        }
    }


def build_report(run: VerifiedRun) -> FinalReport:
    final = run.final_state
    outcome = run.verification

    # The ledger on the final state is cumulative across rounds -- the same
    # Workspace instance served every one of them, which is exactly why a
    # repair continues from the accumulated diff instead of a clean tree.
    return FinalReport(
        task_id=final.task_id,
        user_goal=final.user_goal,
        workspace=final.workspace,
        status=run.status.value,
        agent_status=run.agent_status.value,
        stop_reason=run.reason,
        verification_ran=bool(outcome and outcome.ran),
        verification_status=outcome.status if outcome else None,
        verification_reason=outcome.reason if outcome else "verification was not reached",
        defects=list(outcome.defects) if outcome else [],
        automated_gates=[
            {"gate": result.gate_name, "passed": result.passed, "detail": result.detail}
            for result in (outcome.automated_gates if outcome else [])
        ],
        schema_errors=list(outcome.schema_errors) if outcome else [],
        snapshot_files=len(outcome.scope.files) if outcome and outcome.scope else 0,
        snapshot_bytes=outcome.scope.total_bytes if outcome and outcome.scope else 0,
        files_changed=list(final.files_changed),
        files_inspected=list(final.files_inspected),
        commands_run=[asdict(command) for state in run.states for command in state.commands_run],
        test_results=[asdict(test) for state in run.states for test in state.test_results],
        context_sources=_context_sources(run),
        plan=final.plan,
        planning_status=final.planning_status,
        planning_attempts=final.usage.planning_attempts,
        planning_errors=list(final.planning_errors),
        turns_used=sum(state.usage.turns_used for state in run.states),
        tool_calls=sum(state.usage.tool_calls for state in run.states),
        parse_errors=sum(state.usage.parse_errors for state in run.states),
        repairs_used=run.repairs_used,
        tokens_spent=max(state.usage.tokens_spent for state in run.states),
        spend=str(_total_spend(run.states)),
        rounds=[_summarize(index, state) for index, state in enumerate(run.states)],
        limits=dict(final.limits),
        summary=final.final_summary or "",
    )


def _total_spend(states: list[TaskState]) -> Decimal:
    """Budget totals are cumulative on one shared BudgetController, so the last
    round already holds the run total -- taking a max rather than a sum avoids
    counting the same dollars once per round."""
    return max((state.usage.spend for state in states), default=Decimal(0))


def _summarize(index: int, state: TaskState) -> RoundSummary:
    return RoundSummary(
        index=index,
        status=state.status.value,
        stop_reason=state.stop_reason,
        turns_used=state.usage.turns_used,
        tool_calls=state.usage.tool_calls,
        parse_errors=state.usage.parse_errors,
        files_changed=list(state.files_changed),
    )


def render_report(report: FinalReport) -> str:
    """Terminal rendering. Leads with the distinction that matters: what the
    agent claimed versus what was verified."""
    verdict = "PASSED" if report.passed else "NOT VERIFIED"
    lines = [
        f"task      {report.task_id}",
        f"agent     {report.agent_status}",
        f"verdict   {verdict}  ({report.verification_reason})",
    ]
    if report.plan is not None or report.planning_status is not None:
        lines.append(
            f"plan      {report.planning_status} "
            f"({report.planning_attempts} attempt(s))"
        )
    lines.append(
        f"work      {len(report.files_changed)} file(s) changed, "
        f"{report.turns_used} turn(s), {report.tool_calls} tool call(s), "
        f"{report.repairs_used} repair(s)"
    )
    lines.append(f"usage     {report.tokens_spent} tokens, ${report.spend}")

    if report.files_changed:
        lines.append("changed   " + ", ".join(report.files_changed))
    for gate in report.automated_gates:
        if not gate["passed"]:
            lines.append(f"gate      {gate['gate']} FAILED")
    for defect in report.defects:
        lines.append(
            f"defect    [{defect.get('category')}/{defect.get('severity')}] "
            f"{defect.get('location')}: {defect.get('fix')}"
        )
    for error in report.schema_errors:
        lines.append(f"schema    {error}")
    if report.summary:
        lines.append(f"summary   {report.summary}")
    return "\n".join(lines)
