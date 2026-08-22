import json
from decimal import Decimal
from pathlib import Path

import pytest

from engine.codeagent.limits import Limits
from engine.codeagent.log import SessionLog
from engine.codeagent.session import CodingSession
from engine.codeagent.state import SessionStatus, TaskState
from engine.codeagent.workspace import Workspace
from engine.llm_types import GenerationResult, Message
from engine.runtime.budget import BudgetController
from engine.runtime.gateway import LLMGateway

MODEL = "claude-sonnet-5"  # must exist in runtime/budget.py's PRICE_TABLE


class ScriptedProvider:
    """Offline stand-in for a real provider.

    Returns scripted turns in order and records the messages it was handed, so a
    test can assert on what the loop actually fed back. Never touches a network.
    """

    name = "scripted"

    def __init__(self, responses: list[str], *, raise_on_call: int | None = None) -> None:
        self._responses = responses
        self._raise_on_call = raise_on_call
        self.calls = 0
        self.seen_messages: list[list[Message]] = []
        self.seen_systems: list[str | None] = []

    def generate(
        self,
        messages: list[Message],
        model: str,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        timeout_seconds: float | None = None,
    ) -> GenerationResult:
        self.calls += 1
        self.seen_messages.append(list(messages))
        self.seen_systems.append(system)
        if self._raise_on_call == self.calls:
            raise RuntimeError("provider exploded")
        index = min(self.calls - 1, len(self._responses) - 1)
        return GenerationResult(
            text=self._responses[index],
            model=model,
            provider=self.name,
            input_tokens=10,
            output_tokens=20,
            stop_reason="end_turn",
        )


class StepClock:
    """Monotonic fake clock advancing a fixed step per read."""

    def __init__(self, step: float = 1.0) -> None:
        self.now = 0.0
        self.step = step

    def __call__(self) -> float:
        self.now += self.step
        return self.now


def tool_turn(name: str, args: dict | None = None) -> str:
    return f'```tool\n{json.dumps({"name": name, "args": args or {}})}\n```'


def final_turn(summary: str = "done", files: list[str] | None = None) -> str:
    return f'```final\n{json.dumps({"summary": summary, "files_changed": files or []})}\n```'


def build(
    tmp_path: Path,
    responses: list[str],
    *,
    limits: Limits | None = None,
    raise_on_call: int | None = None,
    max_tokens: int = 1_000_000,
    planned_budget: str = "10.00",
    clock: StepClock | None = None,
    log_path: Path | None = None,
) -> tuple[CodingSession, ScriptedProvider]:
    root = tmp_path / "ws"
    root.mkdir(exist_ok=True)
    provider = ScriptedProvider(responses, raise_on_call=raise_on_call)
    session = CodingSession(
        task_text="fix parse_due_date",
        workspace=Workspace(root),
        gateway=LLMGateway(provider),
        budget=BudgetController(max_tokens=max_tokens, planned_budget=Decimal(planned_budget)),
        model=MODEL,
        task_id="cd-test",
        limits=limits if limits is not None else Limits(),
        log=SessionLog(log_path),
        clock=clock if clock is not None else StepClock(step=0.0),
    )
    return session, provider


def seed(tmp_path: Path, relative: str, content: str) -> Path:
    path = tmp_path / "ws" / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# -- normal flow ------------------------------------------------------------


def test_multi_turn_tool_flow_reaches_a_final_response(tmp_path: Path) -> None:
    seed(tmp_path, "todo.py", "def f():\n    return 1\n")
    session, provider = build(
        tmp_path,
        [
            tool_turn("list_files"),
            tool_turn("read_file", {"path": "todo.py"}),
            tool_turn("replace_exact", {"path": "todo.py", "find": "return 1", "replace": "return 2"}),
            final_turn("changed the return value", ["todo.py"]),
        ],
    )

    state = session.run()

    assert state.status is SessionStatus.COMPLETED_UNVERIFIED
    assert state.usage.turns_used == 4
    assert state.usage.tool_calls == 3
    assert state.usage.parse_errors == 0
    assert [inv.call.name for inv in state.tool_results] == [
        "list_files",
        "read_file",
        "replace_exact",
    ]
    assert all(inv.result.ok for inv in state.tool_results)
    assert (tmp_path / "ws" / "todo.py").read_text(encoding="utf-8") == "def f():\n    return 2\n"
    assert provider.calls == 4


def test_the_final_summary_and_real_file_lists_are_recorded(tmp_path: Path) -> None:
    seed(tmp_path, "todo.py", "x = 1\n")
    session, _ = build(
        tmp_path,
        [
            tool_turn("read_file", {"path": "todo.py"}),
            tool_turn("write_file", {"path": "new.py", "content": "y = 2\n"}),
            final_turn("added a module", ["totally", "made", "up"]),
        ],
    )

    state = session.run()

    assert state.final_summary == "added a module"
    # The ledger is the source of truth, not the model's claim.
    assert state.files_changed == ["new.py"]
    assert state.files_inspected == ["todo.py"]


def test_verification_is_not_run_in_p2(tmp_path: Path) -> None:
    session, _ = build(tmp_path, [final_turn()])

    state = session.run()

    assert state.status is SessionStatus.COMPLETED_UNVERIFIED
    assert state.status is not SessionStatus.PASSED
    assert state.verification_status is None
    assert state.verification_defects == []


def test_observations_are_fed_into_the_next_turn(tmp_path: Path) -> None:
    seed(tmp_path, "todo.py", "needle = 1\n")
    session, provider = build(
        tmp_path,
        [tool_turn("read_file", {"path": "todo.py"}), final_turn()],
    )

    session.run()

    second_call = provider.seen_messages[1]
    assert second_call[-1].role == "user"
    assert "TOOL RESULT: read_file" in second_call[-1].content
    assert "needle = 1" in second_call[-1].content
    # The model's own turn is preserved in between, so the exchange is coherent.
    assert second_call[-2].role == "assistant"


def test_the_system_prompt_is_sent_on_every_turn(tmp_path: Path) -> None:
    session, provider = build(tmp_path, [tool_turn("list_files"), final_turn()])

    session.run()

    assert len(provider.seen_systems) == 2
    assert all(system and "```tool" in system for system in provider.seen_systems)


# -- protocol faults --------------------------------------------------------


def test_a_malformed_turn_is_reported_and_the_session_recovers(tmp_path: Path) -> None:
    session, provider = build(
        tmp_path,
        ["I think I should look around first.", tool_turn("list_files"), final_turn()],
        limits=Limits(max_parse_errors=3),
    )

    state = session.run()

    assert state.status is SessionStatus.COMPLETED_UNVERIFIED
    assert state.usage.parse_errors == 1
    assert state.usage.tool_calls == 1
    # The fault was fed back explicitly rather than silently retried.
    assert "PROTOCOL ERROR" in provider.seen_messages[1][-1].content


def test_repeated_malformed_turns_terminate(tmp_path: Path) -> None:
    session, provider = build(
        tmp_path,
        ["no block here"],  # repeats forever
        limits=Limits(max_parse_errors=3),
    )

    state = session.run()

    assert state.status is SessionStatus.ABORTED_PROTOCOL
    assert state.usage.parse_errors == 3
    assert state.usage.tool_calls == 0
    assert "max_parse_errors (3)" in (state.stop_reason or "")
    assert provider.calls == 3


def test_two_blocks_in_one_turn_execute_nothing(tmp_path: Path) -> None:
    seed(tmp_path, "todo.py", "x = 1\n")
    session, _ = build(
        tmp_path,
        [
            (
                f"{tool_turn('write_file', {'path': 'a.py', 'content': 'a'})}\n"
                f"{tool_turn('write_file', {'path': 'b.py', 'content': 'b'})}"
            ),
            final_turn(),
        ],
        limits=Limits(max_parse_errors=3),
    )

    state = session.run()

    assert state.usage.parse_errors == 1
    assert state.usage.tool_calls == 0
    assert not (tmp_path / "ws" / "a.py").exists()
    assert not (tmp_path / "ws" / "b.py").exists()


# -- tool outcomes ----------------------------------------------------------


def test_an_unknown_tool_becomes_an_observation_not_a_protocol_error(tmp_path: Path) -> None:
    session, provider = build(
        tmp_path,
        [tool_turn("teleport", {"to": "mars"}), final_turn()],
    )

    state = session.run()

    assert state.status is SessionStatus.COMPLETED_UNVERIFIED
    assert state.usage.parse_errors == 0
    assert state.usage.tool_calls == 1
    result = state.tool_results[0].result
    assert not result.ok
    assert "unknown tool 'teleport'" in (result.error or "")
    assert "read_file" in (result.error or "")  # names the real tools
    assert "unknown tool" in provider.seen_messages[1][-1].content


def test_a_tool_failure_is_fed_back_to_the_model(tmp_path: Path) -> None:
    session, provider = build(
        tmp_path,
        [tool_turn("read_file", {"path": "missing.py"}), final_turn()],
    )

    state = session.run()

    assert not state.tool_results[0].result.ok
    observation = provider.seen_messages[1][-1].content
    assert "status: error" in observation
    assert "not a file: missing.py" in observation


def test_a_refused_unsafe_path_is_an_observation_not_a_crash(tmp_path: Path) -> None:
    (tmp_path / "outside.py").write_text("secret\n", encoding="utf-8")
    session, provider = build(
        tmp_path,
        [tool_turn("read_file", {"path": "../outside.py"}), final_turn()],
    )

    state = session.run()

    assert state.status is SessionStatus.COMPLETED_UNVERIFIED
    assert "WorkspaceEscape" in (state.tool_results[0].result.error or "")
    assert "secret" not in provider.seen_messages[1][-1].content


def test_a_denied_command_is_an_observation(tmp_path: Path) -> None:
    session, _ = build(tmp_path, [tool_turn("run_command", {"argv": ["git", "push"]}), final_turn()])

    state = session.run()

    assert state.status is SessionStatus.COMPLETED_UNVERIFIED
    assert "CommandDenied" in (state.tool_results[0].result.error or "")


def test_a_tool_that_raises_terminates_the_session(tmp_path: Path) -> None:
    class ExplodingTool:
        name = "boom"
        description = "raises"

        def run(self, args: dict, ctx: object) -> None:
            raise ZeroDivisionError("tool defect")

    root = tmp_path / "ws"
    root.mkdir(exist_ok=True)
    provider = ScriptedProvider([tool_turn("boom"), final_turn()])
    session = CodingSession(
        task_text="t",
        workspace=Workspace(root),
        gateway=LLMGateway(provider),
        budget=BudgetController(max_tokens=1_000_000, planned_budget=Decimal("10.00")),
        model=MODEL,
        task_id="cd-test",
        tools={"boom": ExplodingTool()},  # type: ignore[dict-item]
        log=SessionLog(),
        clock=StepClock(step=0.0),
    )

    state = session.run()

    # A tool defect is loud and terminal, never an observation the model retries.
    assert state.status is SessionStatus.ERROR
    assert "ZeroDivisionError" in (state.stop_reason or "")
    assert provider.calls == 1


# -- bounds -----------------------------------------------------------------


def test_max_turns_terminates(tmp_path: Path) -> None:
    # Distinct args each turn so loop detection cannot fire first.
    responses = [tool_turn("list_files", {"max_depth": depth}) for depth in range(1, 9)]
    session, provider = build(
        tmp_path, responses, limits=Limits(max_turns=3, max_tool_calls=99, max_repeated_calls=99)
    )

    state = session.run()

    assert state.status is SessionStatus.ABORTED_TURNS
    assert state.usage.turns_used == 3
    assert provider.calls == 3
    assert "max_turns (3)" in (state.stop_reason or "")


def test_max_tool_calls_terminates(tmp_path: Path) -> None:
    responses = [tool_turn("list_files", {"max_depth": depth}) for depth in range(1, 9)]
    session, _ = build(
        tmp_path, responses, limits=Limits(max_turns=99, max_tool_calls=2, max_repeated_calls=99)
    )

    state = session.run()

    assert state.status is SessionStatus.ABORTED_TOOL_CALLS
    assert state.usage.tool_calls == 2
    assert "max_tool_calls (2)" in (state.stop_reason or "")


def test_consecutive_tool_failures_terminate(tmp_path: Path) -> None:
    # Distinct missing paths, so this bound is isolated from loop detection.
    responses = [tool_turn("read_file", {"path": f"missing{i}.py"}) for i in range(1, 9)]
    session, _ = build(
        tmp_path,
        responses,
        limits=Limits(max_consecutive_tool_failures=3, max_turns=99, max_repeated_calls=99),
    )

    state = session.run()

    assert state.status is SessionStatus.ABORTED_TOOL_FAILURES
    assert state.usage.tool_calls == 3
    assert all(not inv.result.ok for inv in state.tool_results)


def test_a_success_resets_the_consecutive_failure_counter(tmp_path: Path) -> None:
    seed(tmp_path, "todo.py", "x = 1\n")
    session, _ = build(
        tmp_path,
        [
            tool_turn("read_file", {"path": "missing1.py"}),
            tool_turn("read_file", {"path": "missing2.py"}),
            tool_turn("read_file", {"path": "todo.py"}),  # succeeds, resets
            tool_turn("read_file", {"path": "missing3.py"}),
            tool_turn("read_file", {"path": "missing4.py"}),
            final_turn(),
        ],
        limits=Limits(max_consecutive_tool_failures=3, max_turns=99, max_repeated_calls=99),
    )

    state = session.run()

    assert state.status is SessionStatus.COMPLETED_UNVERIFIED
    assert state.usage.tool_calls == 5


def test_an_identical_repeated_call_terminates(tmp_path: Path) -> None:
    session, _ = build(
        tmp_path,
        [tool_turn("list_files")],  # the same call forever
        limits=Limits(max_repeated_calls=3, max_turns=99, max_tool_calls=99),
    )

    state = session.run()

    assert state.status is SessionStatus.ABORTED_REPEAT
    # Terminated before executing the third identical call.
    assert state.usage.tool_calls == 2
    assert "repeated 3 times" in (state.stop_reason or "")


def test_repeat_detection_ignores_argument_key_order(tmp_path: Path) -> None:
    seed(tmp_path, "todo.py", "x = 1\n")
    session, _ = build(
        tmp_path,
        [
            '```tool\n{"name": "read_file", "args": {"path": "todo.py", "start": 1}}\n```',
            '```tool\n{"name": "read_file", "args": {"start": 1, "path": "todo.py"}}\n```',
            '```tool\n{"name": "read_file", "args": {"path": "todo.py", "start": 1}}\n```',
        ],
        limits=Limits(max_repeated_calls=3, max_turns=99, max_tool_calls=99),
    )

    state = session.run()

    assert state.status is SessionStatus.ABORTED_REPEAT


def test_a_different_call_in_between_resets_repeat_detection(tmp_path: Path) -> None:
    session, _ = build(
        tmp_path,
        [
            tool_turn("list_files"),
            tool_turn("list_files"),
            tool_turn("git_status"),
            tool_turn("list_files"),
            tool_turn("list_files"),
            final_turn(),
        ],
        limits=Limits(max_repeated_calls=3, max_turns=99, max_tool_calls=99),
    )

    state = session.run()

    assert state.status is SessionStatus.COMPLETED_UNVERIFIED


def test_the_token_budget_terminates_the_session(tmp_path: Path) -> None:
    session, provider = build(
        tmp_path,
        [tool_turn("list_files"), final_turn()],
        limits=Limits(turn_max_tokens=4_000),
        max_tokens=100,  # smaller than one turn's request
    )

    state = session.run()

    assert state.status is SessionStatus.ABORTED_BUDGET
    assert "token budget" in (state.stop_reason or "")
    assert provider.calls == 0  # refused before the call, not after


def test_the_spend_budget_terminates_the_session(tmp_path: Path) -> None:
    session, provider = build(
        tmp_path,
        [tool_turn("list_files"), final_turn()],
        planned_budget="0.000001",
    )

    state = session.run()

    assert state.status is SessionStatus.ABORTED_BUDGET
    assert "spend budget" in (state.stop_reason or "")
    assert provider.calls == 0


def test_the_wall_clock_deadline_terminates_the_session(tmp_path: Path) -> None:
    responses = [tool_turn("list_files", {"max_depth": depth}) for depth in range(1, 30)]
    session, _ = build(
        tmp_path,
        responses,
        limits=Limits(session_timeout_seconds=3.0, max_turns=99, max_tool_calls=99, max_repeated_calls=99),
        clock=StepClock(step=1.0),
    )

    state = session.run()

    assert state.status is SessionStatus.ABORTED_DEADLINE
    assert "deadline of 3.0s" in (state.stop_reason or "")


def test_a_zero_deadline_terminates_before_any_model_call(tmp_path: Path) -> None:
    session, provider = build(
        tmp_path,
        [final_turn()],
        limits=Limits(session_timeout_seconds=0.0),
        clock=StepClock(step=1.0),
    )

    state = session.run()

    assert state.status is SessionStatus.ABORTED_DEADLINE
    assert provider.calls == 0


def test_a_provider_exception_terminates_safely(tmp_path: Path) -> None:
    session, provider = build(
        tmp_path,
        [tool_turn("list_files"), final_turn()],
        raise_on_call=1,
    )

    state = session.run()

    assert state.status is SessionStatus.ERROR
    assert "provider call failed" in (state.stop_reason or "")
    assert "RuntimeError" in (state.stop_reason or "")
    assert provider.calls == 1  # terminated, not retried


def test_a_provider_exception_mid_session_preserves_completed_work(tmp_path: Path) -> None:
    seed(tmp_path, "todo.py", "x = 1\n")
    session, _ = build(
        tmp_path,
        [tool_turn("write_file", {"path": "new.py", "content": "y = 2\n"}), final_turn()],
        raise_on_call=2,
    )

    state = session.run()

    assert state.status is SessionStatus.ERROR
    assert state.files_changed == ["new.py"]
    assert (tmp_path / "ws" / "new.py").exists()


# -- every exit is terminal and explained -----------------------------------


@pytest.mark.parametrize(
    ("responses", "limits", "expected"),
    [
        ([final_turn()], Limits(), SessionStatus.COMPLETED_UNVERIFIED),
        (["prose"], Limits(max_parse_errors=1), SessionStatus.ABORTED_PROTOCOL),
        ([tool_turn("list_files", {"max_depth": 1})], Limits(max_turns=1), SessionStatus.ABORTED_TURNS),
        (
            [tool_turn("list_files", {"max_depth": 1})],
            Limits(max_tool_calls=0),
            SessionStatus.ABORTED_TOOL_CALLS,
        ),
        ([tool_turn("list_files")], Limits(max_repeated_calls=2), SessionStatus.ABORTED_REPEAT),
    ],
)
def test_every_terminal_path_sets_a_status_and_a_reason(
    tmp_path: Path, responses: list[str], limits: Limits, expected: SessionStatus
) -> None:
    session, _ = build(tmp_path, responses, limits=limits)

    state = session.run()

    assert state.status is expected
    assert state.status is not SessionStatus.RUNNING
    assert state.stop_reason
    assert state.phase.value == "DONE"


def test_the_session_never_returns_while_running(tmp_path: Path) -> None:
    session, _ = build(tmp_path, [final_turn()])
    state = session.run()

    assert isinstance(state, TaskState)
    assert state.status is not SessionStatus.RUNNING


# -- logging ----------------------------------------------------------------


def test_the_log_records_the_session_shape(tmp_path: Path) -> None:
    seed(tmp_path, "todo.py", "x = 1\n")
    session, _ = build(
        tmp_path, [tool_turn("read_file", {"path": "todo.py"}), final_turn("did it")]
    )

    session.run()
    kinds = [event.kind for event in session.log.events]

    assert kinds[0] == "session_start"
    assert kinds[-1] == "session_end"
    assert "model_call" in kinds
    assert "tool_call" in kinds
    assert "final_response" in kinds
    assert "status" in kinds


def test_log_events_carry_turn_numbers_and_are_sequenced(tmp_path: Path) -> None:
    session, _ = build(tmp_path, [tool_turn("list_files"), final_turn()])
    session.run()

    events = session.log.events
    assert [event.seq for event in events] == list(range(1, len(events) + 1))
    assert [event.turn for event in session.log.of_kind("model_call")] == [1, 2]


def test_the_tool_call_event_records_the_normalized_request(tmp_path: Path) -> None:
    seed(tmp_path, "todo.py", "x = 1\n")
    session, _ = build(tmp_path, [tool_turn("read_file", {"path": "todo.py"}), final_turn()])
    session.run()

    event = session.log.of_kind("tool_call")[0]
    assert event.payload["tool"] == "read_file"
    assert event.payload["args"] == {"path": "todo.py"}
    assert event.payload["ok"] is True


def test_the_model_call_event_records_counts_never_text(tmp_path: Path) -> None:
    secret = "SECRET REASONING THAT MUST NOT BE PERSISTED"
    session, _ = build(tmp_path, [f"{secret}\n\n{final_turn()}"])
    session.run()

    event = session.log.of_kind("model_call")[0]
    assert event.payload["text_chars"] > 0
    assert "text" not in event.payload
    assert secret not in json.dumps([e.to_dict() for e in session.log.events])


def test_a_parse_error_event_records_the_fault_not_the_response(tmp_path: Path) -> None:
    secret = "SECRET PLAN I AM WRITING OUT LOUD"
    session, _ = build(tmp_path, [secret], limits=Limits(max_parse_errors=1))
    session.run()

    event = session.log.of_kind("parse_error")[0]
    assert event.payload["response_chars"] == len(secret)
    assert secret not in json.dumps(event.to_dict())


def test_the_log_can_be_written_to_disk_as_jsonl(tmp_path: Path) -> None:
    log_path = tmp_path / "logs" / "session.jsonl"
    session, _ = build(tmp_path, [tool_turn("list_files"), final_turn()], log_path=log_path)

    session.run()

    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == len(session.log.events)
    first = json.loads(lines[0])
    assert first["kind"] == "session_start"
    assert json.loads(lines[-1])["kind"] == "session_end"


def test_oversized_log_values_are_bounded(tmp_path: Path) -> None:
    session, _ = build(
        tmp_path,
        [tool_turn("write_file", {"path": "big.py", "content": "x" * 40_000}), final_turn()],
    )

    session.run()

    event = session.log.of_kind("tool_call")[0]
    assert len(event.payload["args"]["content"]) < 2_000
    assert "chars total" in event.payload["args"]["content"]


def test_state_serializes_after_a_real_session(tmp_path: Path) -> None:
    seed(tmp_path, "todo.py", "x = 1\n")
    session, _ = build(tmp_path, [tool_turn("read_file", {"path": "todo.py"}), final_turn("ok")])

    state = session.run()
    payload = json.loads(state.to_json())

    assert payload["status"] == "COMPLETED_UNVERIFIED"
    assert payload["final_summary"] == "ok"
    assert payload["verification_status"] is None
    assert isinstance(payload["usage"]["spend"], str)


# -- offline guarantee ------------------------------------------------------


def test_the_loop_runs_with_no_provider_sdk_and_no_network(tmp_path: Path) -> None:
    """The whole loop is driven by a plain object satisfying the Provider shape:
    no SDK import, no credentials, no socket."""
    session, provider = build(tmp_path, [tool_turn("list_files"), final_turn()])

    state = session.run()

    assert provider.name == "scripted"
    assert state.status is SessionStatus.COMPLETED_UNVERIFIED
    assert state.usage.tokens_spent == 60  # 2 calls x (10 in + 20 out)
    assert state.usage.spend > Decimal(0)
