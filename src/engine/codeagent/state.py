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
    # Debug Agent (D1): the reported failure could not be observed, so there is
    # no evidence to debug against. Terminal *before* any edit is permitted --
    # a fix with no observed failure is an unfalsifiable guess.
    ABORTED_NO_REPRO = "ABORTED_NO_REPRO"
    # Debug Agent (D2): the failure reproduced, but no root-cause hypothesis
    # survived validation. Terminal for the same reason as ABORTED_NO_REPRO --
    # editing against a diagnosis that points nowhere real is a guess wearing
    # the costume of an explanation.
    ABORTED_NO_ROOT_CAUSE = "ABORTED_NO_ROOT_CAUSE"
    ERROR = "ERROR"


class Phase(str, Enum):
    """Where in the flow the session currently is.

    Separate from ``SessionStatus`` because they answer different questions:
    status is the outcome, phase is the position. A session can be RUNNING in
    any phase, and a terminal status can be reached from any of them.
    """

    # Debug Agent (D1). First, not after PLANNING: the reproduction runs before
    # anything is planned, because a failure that will not reproduce ends the
    # run rather than starting one.
    REPRODUCING = "REPRODUCING"
    # Debug Agent (D2): inspecting evidence-named code to form a hypothesis,
    # before any plan exists and long before anything is edited.
    DIAGNOSING = "DIAGNOSING"
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
class CapabilityEvent:
    """One capability disclosure, or one refusal.

    Records what entered context and where it came from -- never the content
    itself. ``digest`` is the snapshot provenance of the served text, so a report
    can state exactly which bytes the model was shown without storing them.

    A refusal carries ``error`` and zero ``chars``; a duplicate carries
    ``duplicate=True`` and zero ``chars``, because nothing new was disclosed.
    Both still happened, and both cost the caller an ordinary tool call.
    """

    kind: str  # "skill"
    name: str
    reference: str | None = None
    chars: int = 0
    truncated: bool = False
    duplicate: bool = False
    error: str | None = None
    digest: str = ""

    @property
    def key(self) -> str:
        return self.name if self.reference is None else f"{self.name}/{self.reference}"

    @property
    def disclosed(self) -> bool:
        """True when this event put new text into context."""
        return self.error is None and not self.duplicate


@dataclass(frozen=True)
class ExternalEvent:
    """One external-capability call, or one refusal.

    Records what was asked for and what was accepted -- never the response body.
    ``chars`` is post-truncation, so it is the number of characters that actually
    entered the model's context rather than the number the provider sent.

    ``resolved_id`` is provenance a reader needs to judge the answer: which
    library the provider actually matched. There is deliberately no field for a
    server, a URL or a credential, because none of those is a thing this layer
    should be able to write down.
    """

    provider: str
    operation: str
    library: str = ""
    resolved_id: str = ""
    chars: int = 0
    truncated: bool = False
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


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
    # Per-call model accounting, distinct from ``tokens_spent``/``spend``, which
    # come from the BudgetController and are cumulative over everything that
    # shares the budget -- including a diagnosis phase this session knows
    # nothing about. These four describe this session alone.
    #
    # ``model_calls`` counts gateway.generate ATTEMPTS: it is incremented before
    # the call, so a request that raised is still counted, because it was still
    # made. The token fields count only what a GenerationResult returned, and
    # are never estimated for a failed call -- so one attempt with zero tokens
    # is a request that never came back, which is exactly what a reader needs
    # to be able to see. ``thinking_tokens`` is a count; reasoning text is never
    # carried, per GenerationResult's own rule.
    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0


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
    # Capabilities (C2). Skills are neither a measured fact about the program nor
    # a claim by the model: they are an input that shaped the run, so they are
    # recorded apart from both. Bodies are deliberately absent -- only names,
    # counts and digests, because a report that stored skill text would grow the
    # transcript this layer exists to bound.
    advertised_skills: list[str] = field(default_factory=list)
    loaded_skills: list[str] = field(default_factory=list)
    loaded_skill_references: list[str] = field(default_factory=list)
    skill_events: list[dict[str, Any]] = field(default_factory=list)
    skill_chars: int = 0
    skill_roots: list[dict[str, Any]] = field(default_factory=list)
    skill_discovery_errors: list[str] = field(default_factory=list)
    skill_shadowed: list[str] = field(default_factory=list)
    # Derived from ``files_changed`` -- never from re-reading a skill file. See
    # capabilities/skills/registry.py:mutations_from_ledger.
    skill_source_mutations: list[str] = field(default_factory=list)
    # Test detection (C3). Held as a plain dict for the same reason ``plan`` is:
    # this dataclass is the serialized report, and keeping it free of imports
    # from the modules it describes is what lets any of them change without
    # breaking the report's shape. None means detection never ran.
    # External capabilities (C6). Counts, provenance and refusal reasons only --
    # a response body never reaches TaskState, which is what keeps a run record
    # from becoming a copy of someone else's documentation.
    external_calls: int = 0
    external_chars: int = 0
    external_failures: list[str] = field(default_factory=list)
    external_events: list[dict[str, Any]] = field(default_factory=list)
    test_detection: dict[str, Any] | None = None
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
