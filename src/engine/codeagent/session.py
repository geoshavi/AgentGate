"""The bounded turn loop.

One model call per turn, at most one tool execution per turn, and a terminal
status for every way the loop can stop. There is no path out of ``run()`` that
does not set a status and a stop reason, and no bound that merely warns.

Model access goes through ``LLMGateway`` -- the same gateway every other
component uses, unmodified. That is not just reuse: the gateway is where the
token and spend budget is enforced *before* each call, so a session cannot
overspend by construction rather than by remembering to check. Offline tests
drive it by constructing ``LLMGateway`` with a scripted fake provider, exactly
as the existing agent and manager tests do.

Tool access goes through the P1 registry and ``ToolContext``. There is no
second execution path: every filesystem and command guarantee proven in P1
holds here because this module reaches the filesystem only through those tools.

What this module does NOT do, deliberately, is verification. A model that ends
the session gets ``COMPLETED_UNVERIFIED`` -- it finished, and nothing has
checked its work. Wiring that to ``run_verification`` is P4, and the status name
is chosen so the gap cannot be mistaken for a pass in the meantime.
"""

import json
import sqlite3
import time
from collections.abc import Callable

from engine.codeagent import protocol
from engine.codeagent.limits import DEFAULT_LIMITS, Limits
from engine.codeagent.log import SessionLog
from engine.codeagent.plan import PlanOutcome, render_plan_context
from engine.codeagent.policy import DEFAULT_POLICY, CommandPolicy
from engine.codeagent.state import (
    Phase,
    SessionStatus,
    TaskState,
    TestRun,
    ToolCall,
    ToolResult,
)
from engine.codeagent.tools.base import Tool, ToolContext
from engine.codeagent.tools.registry import TOOL_REGISTRY
from engine.codeagent.workspace import Workspace
from engine.llm_types import Message
from engine.runtime.budget import BudgetController, BudgetExceededError
from engine.runtime.gateway import LLMGateway

AGENT_NAME = "CodingAgent.turn"

# Which phase a tool implies. Observability only -- no control flow reads it.
_PHASE_BY_TOOL = {
    "list_files": Phase.EXPLORING,
    "read_file": Phase.EXPLORING,
    "search_files": Phase.EXPLORING,
    "git_diff": Phase.EXPLORING,
    "git_status": Phase.EXPLORING,
    "write_file": Phase.EDITING,
    "replace_exact": Phase.EDITING,
    "run_command": Phase.TESTING,
    "run_tests": Phase.TESTING,
}


class CodingSession:
    def __init__(
        self,
        *,
        task_text: str,
        workspace: Workspace,
        gateway: LLMGateway,
        budget: BudgetController,
        model: str,
        task_id: str,
        run_id: int | None = None,
        conn: sqlite3.Connection | None = None,
        limits: Limits = DEFAULT_LIMITS,
        policy: CommandPolicy = DEFAULT_POLICY,
        tools: dict[str, Tool] | None = None,
        log: SessionLog | None = None,
        clock: Callable[[], float] = time.monotonic,
        planning: PlanOutcome | None = None,
        repair_feedback: str | None = None,
        system_prompt: str | None = None,
        agent_name: str = AGENT_NAME,
    ) -> None:
        self._task_text = task_text
        # Two injection points, both defaulting to the Coding Agent's own
        # behaviour, so every existing call site is unchanged. They exist for
        # the Debug Agent's fix session (D3), which is this same loop with a
        # different brief and a different metrics label -- not a different loop.
        # Everything else it needs is already injectable: the tool registry
        # decides the advertised catalogue, and the opening message is built
        # from task_text.
        self._system_prompt = system_prompt
        self._agent_name = agent_name
        self._workspace = workspace
        self._gateway = gateway
        self._budget = budget
        self._model = model
        self._run_id = run_id
        self._conn = conn
        self._limits = limits
        self._tools = TOOL_REGISTRY if tools is None else tools
        self._log = log if log is not None else SessionLog()
        # Injected so the wall-clock bound is testable without sleeping. Used
        # for the deadline and for tool durations, nowhere else.
        self._clock = clock
        self._ctx = ToolContext(workspace=workspace, policy=policy, limits=limits)
        self._planning = planning
        # Structured verification feedback from a previous round, rendered into
        # the opening message. A repair round is an ordinary session over a
        # workspace that was deliberately NOT reset, so the accumulated diff is
        # what it continues from.
        self._repair_feedback = repair_feedback
        self._state = TaskState(
            task_id=task_id,
            user_goal=task_text,
            workspace=str(workspace.root),
            limits=limits.as_dict(),
        )
        if planning is not None:
            # Recorded whether or not it succeeded. A session that ran without a
            # plan says so in its own report rather than looking like one that
            # was never planned.
            self._state.plan = planning.plan.as_dict() if planning.plan is not None else None
            self._state.planning_status = planning.status.value
            self._state.planning_errors = list(planning.errors)
            self._state.usage.planning_attempts = planning.attempts
        self._deadline = 0.0

    @property
    def state(self) -> TaskState:
        return self._state

    @property
    def log(self) -> SessionLog:
        return self._log

    # -- the loop -----------------------------------------------------------

    def run(self) -> TaskState:
        state = self._state
        self._deadline = self._clock() + self._limits.session_timeout_seconds
        self._log.emit(
            "session_start",
            0,
            task_id=state.task_id,
            workspace=state.workspace,
            model=self._model,
            limits=state.limits,
            planning_status=state.planning_status,
            planning_attempts=state.usage.planning_attempts,
        )
        self._set_phase(Phase.EXPLORING)

        system = (
            protocol.build_system_prompt(self._tools)
            if self._system_prompt is None
            else self._system_prompt
        )
        opening = protocol.render_task(self._task_text)
        if self._planning is not None:
            # The plan is context, not authority: it is appended to the opening
            # message and read by nothing else in this loop.
            opening = f"{opening}\n\n{render_plan_context(self._planning)}"
        if self._repair_feedback:
            opening = f"{opening}\n\n{self._repair_feedback}"
        messages = [Message(role="user", content=opening)]
        consecutive_failures = 0
        last_signature: str | None = None
        repeats = 0

        while True:
            if state.usage.turns_used >= self._limits.max_turns:
                return self._terminate(
                    SessionStatus.ABORTED_TURNS,
                    f"max_turns ({self._limits.max_turns}) reached",
                )
            if self._clock() >= self._deadline:
                return self._terminate(
                    SessionStatus.ABORTED_DEADLINE,
                    f"session deadline of {self._limits.session_timeout_seconds}s exceeded",
                )

            turn = state.usage.turns_used + 1
            # Counted before the call, so a request that raises is still a
            # request that was made. See state.Usage for why not on return.
            state.usage.model_calls += 1
            try:
                result = self._gateway.generate(
                    budget=self._budget,
                    messages=messages,
                    model=self._model,
                    system=system,
                    max_tokens=self._limits.turn_max_tokens,
                    agent_name=self._agent_name,
                    timeout_seconds=self._limits.command_timeout_seconds,
                    conn=self._conn,
                    run_id=self._run_id,
                    task_id=state.task_id,
                )
            except BudgetExceededError as exc:
                # Terminal, never retried: the budget does not replenish, so a
                # retry burns the remaining bounds for a call that cannot
                # succeed. Same reasoning orchestrator/manager.py documents.
                return self._terminate(SessionStatus.ABORTED_BUDGET, str(exc))
            except Exception as exc:  # noqa: BLE001 - a provider failure must end the run, not crash it
                return self._terminate(
                    SessionStatus.ERROR,
                    f"provider call failed: {type(exc).__name__}: {exc}",
                )

            state.usage.turns_used = turn
            state.usage.input_tokens += result.input_tokens
            state.usage.output_tokens += result.output_tokens
            state.usage.thinking_tokens += result.thinking_tokens
            self._sync_usage()
            self._log.emit(
                "model_call",
                turn,
                # Counts, never content. See log.py's docstring.
                text_chars=len(result.text),
                stop_reason=result.stop_reason,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                thinking_tokens=result.thinking_tokens,
            )

            parsed = protocol.parse(result.text)

            if isinstance(parsed, protocol.ParseError):
                state.usage.parse_errors += 1
                remaining = self._limits.max_parse_errors - state.usage.parse_errors
                self._log.emit(
                    "parse_error",
                    turn,
                    reason=parsed.message,
                    response_chars=len(result.text),
                    parse_errors=state.usage.parse_errors,
                )
                if state.usage.parse_errors >= self._limits.max_parse_errors:
                    return self._terminate(
                        SessionStatus.ABORTED_PROTOCOL,
                        f"max_parse_errors ({self._limits.max_parse_errors}) reached",
                    )
                messages.append(Message(role="assistant", content=result.text))
                messages.append(
                    Message(
                        role="user",
                        content=protocol.render_parse_error(parsed.message, remaining=remaining),
                    )
                )
                continue

            if isinstance(parsed, protocol.FinalResponse):
                state.final_summary = parsed.summary
                self._log.emit(
                    "final_response",
                    turn,
                    summary_chars=len(parsed.summary),
                    claimed_files_changed=parsed.files_changed,
                )
                return self._terminate(
                    SessionStatus.COMPLETED_UNVERIFIED,
                    "model returned a final response; verification has not run (P4)",
                )

            call = parsed.call
            if state.usage.tool_calls >= self._limits.max_tool_calls:
                return self._terminate(
                    SessionStatus.ABORTED_TOOL_CALLS,
                    f"max_tool_calls ({self._limits.max_tool_calls}) reached",
                )

            signature = _signature(call)
            repeats = repeats + 1 if signature == last_signature else 1
            last_signature = signature
            if repeats >= self._limits.max_repeated_calls:
                # Stop before executing the redundant call: the loop is already
                # established, and running it again only spends budget.
                return self._terminate(
                    SessionStatus.ABORTED_REPEAT,
                    f"identical {call.name} call repeated {repeats} times with no change "
                    "in between",
                )

            tool_result = self._execute(call, turn)
            if tool_result is None:
                return state  # a tool raised; _execute already terminated

            if tool_result.ok:
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                if consecutive_failures >= self._limits.max_consecutive_tool_failures:
                    return self._terminate(
                        SessionStatus.ABORTED_TOOL_FAILURES,
                        f"max_consecutive_tool_failures "
                        f"({self._limits.max_consecutive_tool_failures}) reached",
                    )

            messages.append(Message(role="assistant", content=result.text))
            messages.append(
                Message(role="user", content=protocol.render_observation(call.name, tool_result))
            )

    # -- tool execution -----------------------------------------------------

    def _execute(self, call: ToolCall, turn: int) -> ToolResult | None:
        """Run one tool. Returns None iff the session was terminated."""
        tool = self._tools.get(call.name)
        if tool is None:
            # An unknown name is an observation, not a protocol fault: the turn
            # was well-formed, the model just named something that is not here.
            result = ToolResult(
                ok=False,
                error=f"unknown tool {call.name!r}; available tools: {sorted(self._tools)}",
            )
            duration_ms = 0
        else:
            self._set_phase(_PHASE_BY_TOOL.get(call.name, self._state.phase))
            started = self._clock()
            try:
                result = tool.run(call.args, self._ctx)
            except Exception as exc:  # noqa: BLE001 - a tool bug ends the session loudly
                # Not converted into an observation: an unexpected exception is
                # a defect in the tool, and feeding it back would have the model
                # retry a broken tool until a bound stops it, hiding the bug.
                self._log.emit("tool_error", turn, tool=call.name, error=f"{type(exc).__name__}: {exc}")
                self._terminate(
                    SessionStatus.ERROR,
                    f"tool {call.name!r} raised {type(exc).__name__}: {exc}",
                )
                return None
            duration_ms = int((self._clock() - started) * 1000)

        self._state.record_tool(call, result, duration_ms=duration_ms)
        self._drain_commands(call)
        self._log.emit(
            "tool_call",
            turn,
            tool=call.name,
            args=call.args,
            ok=result.ok,
            exit_code=result.exit_code,
            truncated=result.truncated,
            output_chars=len(result.output),
            output=result.output,
            error=result.error,
        )
        return result

    def _drain_commands(self, call: ToolCall) -> None:
        """Move commands that actually executed into the report's record.

        A test run gets a ``TestRun`` entry as well: "the suite was run and
        what it said" is the question a reader of the report asks first, and
        answering it from an argv list in ``commands_run`` would mean knowing
        which argv happens to be pytest.
        """
        for record in self._ctx.command_log:
            self._state.commands_run.append(record)
            if call.name != "run_tests":
                continue
            self._state.test_results.append(
                TestRun(
                    argv=record.argv,
                    passed=record.exit_code == 0,
                    exit_code=record.exit_code,
                    summary=_last_line(self._state.tool_results[-1].result.output),
                    duration_ms=record.duration_ms,
                )
            )
        self._ctx.command_log.clear()

    # -- bookkeeping --------------------------------------------------------

    def _set_phase(self, phase: Phase) -> None:
        if phase is self._state.phase:
            return
        previous = self._state.phase
        self._state.phase = phase
        self._log.emit(
            "phase", self._state.usage.turns_used, from_phase=previous.value, to_phase=phase.value
        )

    def _sync_usage(self) -> None:
        self._state.usage.tokens_spent = self._budget.spent_tokens
        self._state.usage.spend = self._budget.spent_amount

    def _terminate(self, status: SessionStatus, reason: str) -> TaskState:
        state = self._state
        # The report's file lists come from the workspace ledger, never from
        # what the model claimed it did. One is a record of writes that
        # happened; the other is an assertion.
        state.files_changed = self._workspace.changed_files
        state.files_inspected = self._workspace.inspected_files
        self._sync_usage()

        previous = state.status
        state.status = status
        state.stop_reason = reason
        state.phase = Phase.DONE

        turn = state.usage.turns_used
        self._log.emit(
            "status", turn, from_status=previous.value, to_status=status.value, reason=reason
        )
        self._log.emit(
            "session_end",
            turn,
            status=status.value,
            stop_reason=reason,
            turns_used=state.usage.turns_used,
            tool_calls=state.usage.tool_calls,
            parse_errors=state.usage.parse_errors,
            tokens_spent=state.usage.tokens_spent,
            spend=str(state.usage.spend),
            files_changed=state.files_changed,
            files_inspected=state.files_inspected,
        )
        return state


def _last_line(text: str, limit: int = 200) -> str:
    """The last non-empty line of a tool's output -- for pytest that is the
    summary line ("1 failed, 2 passed"), which is the useful part."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1][:limit] if lines else ""


def _signature(call: ToolCall) -> str:
    """Stable identity of a call, for loop detection. Sorted keys so argument
    order in the model's JSON does not disguise a repeat."""
    return f"{call.name}:{json.dumps(call.args, sort_keys=True, default=str)}"
