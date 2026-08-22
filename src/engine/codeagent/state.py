"""Machine-readable execution state for a Coding Agent session.

Records only *observable* execution data: what was called, what it returned,
what changed on disk, and what it cost. There is deliberately no field for
the model's reasoning, and no code path that could put reasoning text into
one. This mirrors a decision the codebase already made -- ``GenerationResult``
carries ``thinking_tokens`` as a count and its docstring states the reasoning
text "is deliberately never carried here" -- so the agent inherits the rule
rather than inventing a second, weaker one.

``verification_status`` and ``final_summary`` are placeholders for P4 and P5.
They exist now so the serialized shape does not change when those phases land;
until then they stay ``None``, which reads as "not reached", never as "passed".

Nothing in this module imports ``runtime/`` or ``providers/``: P1 makes no
model calls, and the state shape must not require one to be constructible.
"""

import json
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any


class SessionStatus(str, Enum):
    """How the session ended. ``RUNNING`` until it has."""

    RUNNING = "RUNNING"
    PASSED = "PASSED"  # set only from verdict.gate's return value (P4)
    # The agent finished its own work and said so. Verification has NOT run --
    # this is the terminal success of P2 and must never be read as PASSED.
    COMPLETED_UNVERIFIED = "COMPLETED_UNVERIFIED"
    UNVERIFIED = "UNVERIFIED"
    ABORTED_TURNS = "ABORTED_TURNS"
    ABORTED_TOOL_CALLS = "ABORTED_TOOL_CALLS"
    ABORTED_TOOL_FAILURES = "ABORTED_TOOL_FAILURES"
    ABORTED_REPEAT = "ABORTED_REPEAT"
    ABORTED_BUDGET = "ABORTED_BUDGET"
    ABORTED_DEADLINE = "ABORTED_DEADLINE"
    ABORTED_POLICY = "ABORTED_POLICY"
    ABORTED_PROTOCOL = "ABORTED_PROTOCOL"
    ABORTED_WORKSPACE = "ABORTED_WORKSPACE"
    ERROR = "ERROR"


class Phase(str, Enum):
    """Where in the flow the session currently is.

    Separate from ``SessionStatus`` because they answer different questions:
    status is the outcome, phase is the position. A session can be RUNNING in
    any phase, and a terminal status can be reached from any of them.
    """

    PLANNING = "PLANNING"
    EXPLORING = "EXPLORING"
    EDITING = "EDITING"
    TESTING = "TESTING"
    VERIFYING = "VERIFYING"
    REPORTING = "REPORTING"
    DONE = "DONE"


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResult:
    """What a tool hands back. ``output`` is already truncated to the session's
    limit, and ``truncated`` says so explicitly -- a caller must never have to
    infer from a length whether it is looking at a partial result.
    """

    ok: bool
    output: str = ""
    truncated: bool = False
    error: str | None = None
    exit_code: int | None = None


@dataclass(frozen=True)
class ToolInvocation:
    index: int
    call: ToolCall
    result: ToolResult
    duration_ms: int = 0


@dataclass(frozen=True)
class CommandRun:
    argv: list[str]
    exit_code: int | None
    timed_out: bool
    duration_ms: int
    output_truncated: bool = False


@dataclass(frozen=True)
class TestRun:
    # pytest collects any class named Test*; this is a record, not a suite.
    # Not annotated, so dataclass does not treat it as a field.
    __test__ = False

    argv: list[str]
    passed: bool
    exit_code: int | None
    summary: str
    duration_ms: int


@dataclass
class Usage:
    """Consumption against the session's limits. Token and spend fields stay
    zero in P1 (no model calls exist yet) and are populated by the gateway's
    own accounting in P2.
    """

    turns_used: int = 0
    planning_attempts: int = 0
    repairs_used: int = 0
    parse_errors: int = 0
    denied_commands: int = 0
    tool_calls: int = 0
    tokens_spent: int = 0
    spend: Decimal = Decimal(0)


@dataclass
class TaskState:
    task_id: str
    user_goal: str
    workspace: str
    status: SessionStatus = SessionStatus.RUNNING
    phase: Phase = Phase.PLANNING
    files_inspected: list[str] = field(default_factory=list)
    files_changed: list[str] = field(default_factory=list)
    commands_run: list[CommandRun] = field(default_factory=list)
    tool_results: list[ToolInvocation] = field(default_factory=list)
    test_results: list[TestRun] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    limits: dict[str, object] = field(default_factory=dict)
    # Planning (P3). Held as plain data rather than a Plan object, matching how
    # ``limits`` is held: this dataclass is the serialized report, and keeping
    # it free of imports from the modules it describes is what lets any of them
    # change without breaking the report's shape.
    # ``planning_status`` is None only when planning was never attempted --
    # never as a stand-in for a failure, which has its own explicit status.
    plan: dict[str, Any] | None = None
    planning_status: str | None = None
    planning_errors: list[str] = field(default_factory=list)
    # Placeholders, filled by P4 / P5. None means "not reached".
    verification_status: str | None = None
    verification_defects: list[dict[str, Any]] = field(default_factory=list)
    final_summary: str | None = None
    stop_reason: str | None = None

    def record_tool(self, call: ToolCall, result: ToolResult, *, duration_ms: int = 0) -> None:
        self.tool_results.append(
            ToolInvocation(
                index=len(self.tool_results) + 1,
                call=call,
                result=result,
                duration_ms=duration_ms,
            )
        )
        self.usage.tool_calls += 1

    def note_inspected(self, relative_path: str) -> None:
        if relative_path not in self.files_inspected:
            self.files_inspected.append(relative_path)

    def note_changed(self, relative_path: str) -> None:
        if relative_path not in self.files_changed:
            self.files_changed.append(relative_path)

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready form.

        ``Decimal`` is rendered as a string, never a float: the budget code is
        explicit that money never becomes a float, and a serializer that
        quietly did so would undo that guarantee at the persistence boundary.
        """
        return asdict(self, dict_factory=_dict_factory)

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=False)


def _dict_factory(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    return {key: _encode(value) for key, value in pairs}


def _encode(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, list):
        return [_encode(item) for item in value]
    if isinstance(value, dict):
        return {key: _encode(item) for key, item in value.items()}
    return value
