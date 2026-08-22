import json
from dataclasses import fields
from decimal import Decimal

from engine.codeagent.limits import DEFAULT_LIMITS, Limits
from engine.codeagent.state import (
    CommandRun,
    Phase,
    SessionStatus,
    TaskState,
    TestRun,
    ToolCall,
    ToolResult,
    Usage,
)


def _state() -> TaskState:
    return TaskState(
        task_id="cd-8f3a1c",
        user_goal="fix parse_due_date on empty input",
        workspace="/ws",
        limits=DEFAULT_LIMITS.as_dict(),
    )


# -- defaults ---------------------------------------------------------------


def test_a_new_state_is_running_and_unverified() -> None:
    state = _state()

    assert state.status is SessionStatus.RUNNING
    assert state.phase is Phase.PLANNING
    # Placeholders must read as "not reached", never as a passing outcome.
    assert state.verification_status is None
    assert state.final_summary is None
    assert state.stop_reason is None


def test_collections_default_empty_and_are_not_shared_between_instances() -> None:
    first, second = _state(), _state()
    first.note_changed("a.py")

    assert first.files_changed == ["a.py"]
    assert second.files_changed == []


# -- recording --------------------------------------------------------------


def test_record_tool_indexes_from_one_and_counts_usage() -> None:
    state = _state()
    state.record_tool(ToolCall("read_file", {"path": "a.py"}), ToolResult(ok=True, output="x"))
    state.record_tool(ToolCall("run_tests"), ToolResult(ok=True, exit_code=0), duration_ms=120)

    assert [inv.index for inv in state.tool_results] == [1, 2]
    assert state.usage.tool_calls == 2
    assert state.tool_results[1].duration_ms == 120


def test_note_helpers_deduplicate() -> None:
    state = _state()
    state.note_inspected("a.py")
    state.note_inspected("a.py")
    state.note_changed("b.py")
    state.note_changed("b.py")

    assert state.files_inspected == ["a.py"]
    assert state.files_changed == ["b.py"]


# -- serialization ----------------------------------------------------------


def test_state_serializes_to_valid_json() -> None:
    state = _state()
    state.record_tool(ToolCall("read_file", {"path": "a.py"}), ToolResult(ok=True, output="x"))
    state.commands_run.append(
        CommandRun(argv=["python", "-m", "pytest"], exit_code=1, timed_out=False, duration_ms=900)
    )
    state.test_results.append(
        TestRun(argv=["pytest"], passed=False, exit_code=1, summary="1 failed", duration_ms=900)
    )

    payload = json.loads(state.to_json())

    assert payload["task_id"] == "cd-8f3a1c"
    assert payload["status"] == "RUNNING"
    assert payload["phase"] == "PLANNING"
    assert payload["tool_results"][0]["call"]["name"] == "read_file"
    assert payload["commands_run"][0]["exit_code"] == 1
    assert payload["test_results"][0]["passed"] is False


def test_json_round_trips_through_to_dict() -> None:
    state = _state()
    state.record_tool(ToolCall("git_diff", {"stat": True}), ToolResult(ok=True, output="d"))

    assert json.loads(state.to_json()) == state.to_dict()


def test_enums_serialize_as_their_string_values() -> None:
    state = _state()
    state.status = SessionStatus.ABORTED_TURNS
    state.phase = Phase.EDITING

    payload = state.to_dict()

    assert payload["status"] == "ABORTED_TURNS"
    assert payload["phase"] == "EDITING"
    assert isinstance(payload["status"], str)


def test_decimal_spend_serializes_as_a_string_never_a_float() -> None:
    state = _state()
    state.usage.spend = Decimal("0.0416")

    payload = state.to_dict()
    raw = state.to_json()

    assert payload["usage"]["spend"] == "0.0416"
    assert isinstance(payload["usage"]["spend"], str)
    assert not isinstance(payload["usage"]["spend"], float)
    # The exact value survives the text form; a float would not guarantee this.
    assert Decimal(json.loads(raw)["usage"]["spend"]) == Decimal("0.0416")


def test_limits_are_recorded_with_the_state() -> None:
    state = _state()
    payload = state.to_dict()

    assert payload["limits"]["max_read_bytes"] == DEFAULT_LIMITS.max_read_bytes
    assert payload["limits"]["command_timeout_seconds"] == DEFAULT_LIMITS.command_timeout_seconds


# -- no chain-of-thought ----------------------------------------------------


_REASONING_WORDS = ("reasoning", "thinking", "thought", "chain_of_thought", "scratchpad", "rationale")


def test_no_state_dataclass_has_a_reasoning_field() -> None:
    """Structural guarantee: there is nowhere to put chain-of-thought."""
    for cls in (TaskState, Usage, ToolCall, ToolResult, CommandRun, TestRun):
        for f in fields(cls):
            assert not any(word in f.name.lower() for word in _REASONING_WORDS), (
                f"{cls.__name__}.{f.name}"
            )


def test_serialized_state_exposes_only_observable_execution_data() -> None:
    state = _state()
    state.record_tool(ToolCall("read_file", {"path": "a.py"}), ToolResult(ok=True, output="x"))

    keys = set(state.to_dict())

    assert keys == {
        "task_id",
        "user_goal",
        "workspace",
        "status",
        "phase",
        "files_inspected",
        "files_changed",
        "commands_run",
        "tool_results",
        "test_results",
        "usage",
        "limits",
        "verification_status",
        "verification_defects",
        "final_summary",
        "stop_reason",
    }


# -- limits -----------------------------------------------------------------


def test_limits_are_overridable_without_mutating_the_default() -> None:
    tight = Limits(max_read_bytes=10, command_timeout_seconds=0.5)

    assert tight.max_read_bytes == 10
    assert tight.command_timeout_seconds == 0.5
    assert DEFAULT_LIMITS.max_read_bytes != 10


def test_limits_serialize_to_a_plain_dict() -> None:
    payload = Limits().as_dict()

    assert payload["max_files_changed"] == 20
    assert payload["max_delete_bytes"] == 2_000
    assert all(isinstance(key, str) for key in payload)
