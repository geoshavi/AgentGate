"""The fix loop: edit, prove, repair -- bounded, and never self-certifying.

Composition, not new machinery. The fixing session **is** ``CodingSession``:
same turn loop, same bounds, same terminal statuses, same tool safety, same
mutation ledger. What differs is three injected things -- a narrower tool set, a
debugging brief, and a metrics label -- and every one of them was already a
constructor argument or became one in a two-line seam.

Three rules hold this phase together:

**The model never decides success.** ``gate.prove`` runs two commands and their
exit codes are the verdict. A session can end with a confident "fixed" and still
report UNPROVEN; that is the intended outcome, not an edge case.

**The commands cannot move.** The reproduction is frozen from D1 and exposed
only through a no-argument tool. The regression suite is frozen and policy-
checked before the session starts. The fix tool set contains no ``run_command``
and no ``write_file``, so there is no path by which a model can run a narrower
test or write a file wholesale -- edits are anchored replacements only.

**Prerequisites are checked before anything is editable.** An unreproduced
failure or a root cause pointing at a file that is not there aborts before the
first model call. Editing against evidence that does not exist is the failure
mode D1 and D2 were built to prevent, and it would be undone by letting D3 start
anyway.
"""

import sqlite3
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from engine.codeagent.limits import Limits
from engine.codeagent.log import SessionLog
from engine.codeagent.policy import DEFAULT_POLICY, CommandPolicy
from engine.codeagent.session import CodingSession
from engine.codeagent.state import SessionStatus, TaskState
from engine.codeagent.tools.base import Tool
from engine.codeagent.tools.fs import ListFilesTool, ReadFileTool, ReplaceExactTool
from engine.codeagent.tools.git import GitDiffTool, GitStatusTool
from engine.codeagent.tools.search import SearchFilesTool
from engine.codeagent.tools.shell import RunTestsTool
from engine.codeagent.workspace import Workspace, WorkspaceError
from engine.debugagent.evidence import FailureEvidence, render_evidence
from engine.debugagent.gate import ProofResult, freeze_suite, prove, render_repair_feedback
from engine.debugagent.limits import DEBUG_LIMITS
from engine.debugagent.repro import FrozenRepro
from engine.debugagent.rootcause import RootCause
from engine.debugagent.tools.repro import RunReproTool
from engine.runtime.budget import BudgetController
from engine.runtime.gateway import LLMGateway

AGENT_NAME = "DebugAgent.fix"

# The fixing tool set. Two absences are the point:
#
#   run_command -- no arbitrary command execution. The only commands reachable
#                  are the frozen reproduction and the suite, so a model cannot
#                  run a narrowed pytest selection and call it green.
#   write_file  -- no wholesale file writes. Every edit is an anchored
#                  replacement that must match exactly once, which is what keeps
#                  a "fix" from becoming a rewrite.
_BASE_FIX_TOOLS: dict[str, Tool] = {
    "list_files": ListFilesTool(),
    "read_file": ReadFileTool(),
    "search_files": SearchFilesTool(),
    "replace_exact": ReplaceExactTool(),
    "run_tests": RunTestsTool(),
    "git_diff": GitDiffTool(),
    "git_status": GitStatusTool(),
}

# Names only -- the run_repro instance needs the frozen command, so the real
# registry is built per run by ``build_fix_tools``.
DEBUG_FIX_TOOLS: tuple[str, ...] = (*sorted(_BASE_FIX_TOOLS), "run_repro")


class ProofStatus(str, Enum):
    """Whether the fix was demonstrated. Only exit codes reach PROVEN."""

    PROVEN = "PROVEN"
    UNPROVEN = "UNPROVEN"
    # A prerequisite failed, so no fixing session was ever started.
    ABORTED = "ABORTED"


def build_fix_tools(repro: FrozenRepro) -> dict[str, Tool]:
    """The fix tool set, with run_repro bound to this run's frozen command."""
    return {**_BASE_FIX_TOOLS, "run_repro": RunReproTool(repro)}


@dataclass(frozen=True)
class FixOutcome:
    """What the fix phase did, and whether it worked.

    ``status`` and ``session_status`` are separate claims and stay separate, the
    same way the Coding Agent keeps ``status`` apart from ``agent_status``: one
    is what the harness proved, the other is how the agent's loop ended. A
    session that hit its turn ceiling can still have produced a proven fix, and
    a session that ended cleanly can be UNPROVEN.
    """

    status: ProofStatus
    session_status: SessionStatus
    reason: str
    # The fixing session's own closing sentence. Carried so a report can show
    # what the agent thought it did; it decides nothing, and a session that
    # signs off "fixed the bug" over a failing reproduction is still UNPROVEN.
    final_summary: str = ""
    root_cause: RootCause | None = None
    proof: ProofResult | None = None
    repairs_used: int = 0
    files_changed: list[str] = field(default_factory=list)
    commands_run: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: int = 0
    turns_used: int = 0
    # Usage, carried forward with D2's semantics: model_calls counts
    # gateway.generate attempts, token fields count only what came back.
    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0

    @property
    def proven(self) -> bool:
        return self.status is ProofStatus.PROVEN

    def as_dict(self) -> dict[str, Any]:
        return {
            "proof_status": self.status.value,
            "session_status": self.session_status.value,
            "reason": self.reason,
            "final_summary": self.final_summary,
            "root_cause": None if self.root_cause is None else self.root_cause.as_dict(),
            "proof": None if self.proof is None else self.proof.as_dict(),
            "repairs_used": self.repairs_used,
            "files_changed": list(self.files_changed),
            "commands_run": list(self.commands_run),
            "tool_results": list(self.tool_results),
            "tool_calls": self.tool_calls,
            "turns_used": self.turns_used,
            "model_calls": self.model_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "thinking_tokens": self.thinking_tokens,
        }


def run_fix_loop(
    *,
    task_text: str,
    evidence: FailureEvidence,
    root_cause: RootCause,
    repro: FrozenRepro,
    suite_argv: object,
    workspace: Workspace,
    gateway: LLMGateway,
    budget: BudgetController,
    model: str,
    task_id: str,
    run_id: int | None = None,
    conn: sqlite3.Connection | None = None,
    limits: Limits = DEBUG_LIMITS,
    policy: CommandPolicy = DEFAULT_POLICY,
    log: SessionLog | None = None,
) -> FixOutcome:
    """Apply the smallest fix for a validated root cause, then prove it.

    Never raises: a refused prerequisite, an exhausted budget and an unproven
    fix are all statuses, because the caller's next move -- do not claim
    success -- is identical in every case.
    """
    sink = log if log is not None else SessionLog()

    refusal = _check_prerequisites(evidence, root_cause, workspace)
    if refusal is not None:
        return _aborted(sink, root_cause, refusal)

    try:
        suite = freeze_suite(suite_argv, policy)
    except (TypeError, ValueError) as exc:
        return _aborted(sink, root_cause, str(exc))

    tools = build_fix_tools(repro)
    system = build_fix_prompt(repro, suite)
    brief = render_fix_brief(task_text, evidence, root_cause, repro, suite)

    states: list[TaskState] = []
    proof: ProofResult | None = None
    repairs = 0
    feedback: str | None = None

    while True:
        session = CodingSession(
            task_text=brief,
            workspace=workspace,
            gateway=gateway,
            budget=budget,
            model=model,
            task_id=task_id,
            run_id=run_id,
            conn=conn,
            limits=_remaining(limits, states),
            policy=policy,
            tools=tools,
            log=sink,
            repair_feedback=feedback,
            system_prompt=system,
            agent_name=AGENT_NAME,
        )
        states.append(session.run())

        # The gate runs whatever the session's own status was. A run that hit
        # its turn ceiling may still have fixed the bug, and refusing to look
        # would report a false negative; the exit codes decide either way.
        if not workspace.changed_files:
            proof = None
            reason = "no file was changed, so there is nothing to prove"
        else:
            proof = prove(
                repro=repro, suite=suite, workspace=workspace, policy=policy, limits=limits
            )
            reason = proof.reason
            sink.emit(
                "fix_proof",
                proven=proof.proven,
                stage=proof.stage,
                reason=proof.reason,
                repairs_used=repairs,
            )
            if proof.proven:
                return _finish(
                    ProofStatus.PROVEN, states, proof, repairs, workspace, reason, root_cause
                )

        if repairs >= limits.max_repair_rounds:
            break
        remaining = _remaining(limits, states)
        if remaining.max_turns <= 0 or remaining.max_tool_calls <= 0:
            reason = f"{reason}; no turn allowance left for a repair round"
            break

        repairs += 1
        feedback = (
            render_repair_feedback(proof)
            if proof is not None
            else (
                "FIX NOT PROVEN -- NOTHING WAS CHANGED\n"
                "You ended the session without editing any file, so the bug is "
                "untouched. Apply the smallest change that addresses the root "
                "cause above, then run run_repro to check it."
            )
        )

    return _finish(
        ProofStatus.UNPROVEN,
        states,
        proof,
        repairs,
        workspace,
        f"{reason}; unproven after {repairs} repair round(s)",
        root_cause,
    )


# -- prerequisites ----------------------------------------------------------


def _check_prerequisites(
    evidence: FailureEvidence, root_cause: RootCause, workspace: Workspace
) -> str | None:
    """Why the fixing phase must not start, or None if it may.

    Both checks re-verify a fact an earlier phase already established. That is
    deliberate: this function is the last point before a model is handed edit
    tools, and a caller that skipped D1 or D2 must not be able to reach one.
    """
    if not evidence.reproduced:
        return (
            "the failure was never reproduced, so there is no evidence to fix "
            "against; the fixing phase was not started"
        )
    try:
        resolved = workspace.resolve(root_cause.primary_file)
    except WorkspaceError as exc:
        return f"the root cause names an unusable file: {type(exc).__name__}: {exc}"
    if not resolved.is_file():
        return (
            f"the root cause names {root_cause.primary_file!r}, which is not a file "
            "in this workspace"
        )
    return None


# -- prompting --------------------------------------------------------------


def build_fix_prompt(repro: FrozenRepro, suite: FrozenRepro) -> str:
    """The fixing system prompt.

    Generated rather than stored, matching every other prompt in the codebase.
    It states the two commands verbatim so the model knows exactly what it will
    be judged by -- there is nothing to be gained by hiding the bar.
    """
    return f"""You are a debugging agent. A failure has already been reproduced and
diagnosed. Your job is to apply the SMALLEST change that fixes the stated root
cause, and nothing else.

Work by calling exactly one tool per turn. End every message with exactly one
fenced block and nothing after it.

To call a tool:

```tool
{{"name": "<tool>", "args": {{...}}}}
```

To finish:

```final
{{"summary": "<what you changed and why>", "files_changed": ["<path>", ...]}}
```

You will be judged by two commands, not by what you say:

  reproduction : {repro.display()}
  regression   : {suite.display()}

Both must exit 0. Saying the bug is fixed while the reproduction still fails
changes nothing -- the commands are run for you afterwards either way.

Rules:
- Fix the stated root cause. Do not refactor, tidy, rename, or fix unrelated
  problems; a change beyond the cause is a change nobody asked for.
- Read a file before editing it. Anchors for replace_exact must match exactly
  once, so copy them verbatim, including indentation.
- Call run_repro to check your work. It takes no arguments and always runs the
  reproduction command above -- you cannot narrow or replace it.
- Do not edit tests to make the failure go away. The regression suite runs too.
- All paths are relative to the workspace. Paths outside it are refused, as are
  credential files.
- A tool error is information, not a dead end: read it and adjust.

Available tools:
""" + "\n".join(
        f"- {name}" for name in DEBUG_FIX_TOOLS
    )


def render_fix_brief(
    task_text: str,
    evidence: FailureEvidence,
    root_cause: RootCause,
    repro: FrozenRepro,
    suite: FrozenRepro,
) -> str:
    """The opening message: the bug, the evidence, and the validated cause.

    Passed as the session's ``task_text``, which is how the root cause reaches
    the loop without ``CodingSession`` needing to know what a root cause is.
    """
    refs = "\n".join(f"  - {ref}" for ref in root_cause.evidence_refs)
    related = ", ".join(root_cause.related_files) or "(none)"
    return "\n".join(
        [
            f"REPORTED BUG\n{task_text.strip()}",
            "",
            render_evidence(evidence),
            "",
            "VALIDATED ROOT CAUSE",
            f"  summary   : {root_cause.summary}",
            f"  mechanism : {root_cause.mechanism}",
            f"  location  : {root_cause.location()}",
            f"  related   : {related}",
            f"  fix       : {root_cause.proposed_fix}",
            f"  confidence: {root_cause.confidence.value}",
            f"  evidence  :\n{refs}" if refs else "",
            "",
            "PROOF COMMANDS (frozen -- you cannot change these)",
            f"  reproduction : {repro.display()}",
            f"  regression   : {suite.display()}",
            "",
            "Apply the smallest change that addresses this root cause.",
        ]
    )


# -- assembly ---------------------------------------------------------------


def _remaining(limits: Limits, states: list[TaskState]) -> Limits:
    """Turn and tool allowances left, shared across rounds.

    Granted once for the whole run rather than afresh to each repair, so
    repairs cannot extend a fix past its own bounds -- the same rule
    ``verify.run_verified_session`` applies to its rounds.
    """
    from dataclasses import replace

    used_turns = sum(state.usage.turns_used for state in states)
    used_calls = sum(state.usage.tool_calls for state in states)
    return replace(
        limits,
        max_turns=limits.max_turns - used_turns,
        max_tool_calls=limits.max_tool_calls - used_calls,
    )


def _finish(
    status: ProofStatus,
    states: list[TaskState],
    proof: ProofResult | None,
    repairs: int,
    workspace: Workspace,
    reason: str,
    root_cause: RootCause,
) -> FixOutcome:
    """Assemble the outcome from observable records only."""
    commands: list[dict[str, Any]] = []
    tools: list[dict[str, Any]] = []
    for state in states:
        for record in state.commands_run:
            commands.append(
                {
                    "argv": list(record.argv),
                    "exit_code": record.exit_code,
                    "timed_out": record.timed_out,
                    "duration_ms": record.duration_ms,
                }
            )
        for invocation in state.tool_results:
            tools.append(
                {
                    "tool": invocation.call.name,
                    "ok": invocation.result.ok,
                    "exit_code": invocation.result.exit_code,
                    "error": invocation.result.error,
                }
            )

    # The proof commands were executed by the harness, not by the session, so
    # they are not in any TaskState. They are still commands this run ran, and a
    # report that omitted them would understate what happened.
    if proof is not None:
        for proof_run in (proof.repro_after, proof.suite_after):
            if proof_run is not None:
                commands.append(
                    {
                        "argv": list(proof_run.argv),
                        "exit_code": proof_run.exit_code,
                        "timed_out": proof_run.timed_out,
                        "duration_ms": proof_run.duration_ms,
                    }
                )

    return FixOutcome(
        status=status,
        session_status=states[-1].status if states else SessionStatus.ERROR,
        reason=reason,
        final_summary=(states[-1].final_summary or "") if states else "",
        root_cause=root_cause,
        proof=proof,
        repairs_used=repairs,
        # From the ledger, never from what any model said it changed.
        files_changed=workspace.changed_files,
        commands_run=commands,
        tool_results=tools,
        tool_calls=sum(state.usage.tool_calls for state in states),
        turns_used=sum(state.usage.turns_used for state in states),
        # Summed over the initial session and every repair, from each session's
        # own per-call accounting -- not from the budget, which is shared with
        # the diagnosis phase and would double-count it.
        model_calls=sum(state.usage.model_calls for state in states),
        input_tokens=sum(state.usage.input_tokens for state in states),
        output_tokens=sum(state.usage.output_tokens for state in states),
        thinking_tokens=sum(state.usage.thinking_tokens for state in states),
    )


def _aborted(sink: SessionLog, root_cause: RootCause, reason: str) -> FixOutcome:
    sink.emit("fix_aborted", reason=reason)
    return FixOutcome(
        status=ProofStatus.ABORTED,
        session_status=SessionStatus.ABORTED_WORKSPACE,
        reason=reason,
        root_cause=root_cause,
    )


__all__ = [
    "AGENT_NAME",
    "DEBUG_FIX_TOOLS",
    "FixOutcome",
    "ProofStatus",
    "build_fix_prompt",
    "build_fix_tools",
    "render_fix_brief",
    "run_fix_loop",
]
