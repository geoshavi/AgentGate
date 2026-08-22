import json
from decimal import Decimal
from pathlib import Path

import pytest

from engine.codeagent import plan as plan_module
from engine.codeagent.limits import Limits
from engine.codeagent.log import SessionLog
from engine.codeagent.plan import (
    Plan,
    PlanOutcome,
    PlanStatus,
    make_plan,
    parse_plan_block,
    render_plan_context,
    validate_plan,
)
from engine.codeagent.policy import DEFAULT_POLICY
from engine.codeagent.session import CodingSession
from engine.codeagent.state import SessionStatus
from engine.codeagent.tools.registry import TOOL_REGISTRY
from engine.codeagent.workspace import Workspace
from engine.llm_types import GenerationResult, Message
from engine.runtime.budget import BudgetController
from engine.runtime.gateway import LLMGateway

TOOL_NAMES = sorted(TOOL_REGISTRY)
MODEL = "claude-sonnet-5"  # must exist in runtime/budget.py's PRICE_TABLE

# The scripted harness is duplicated from tests/test_codeagent_session.py rather
# than imported. tests/ is not a package and has no conftest, so a cross-test
# import only resolves when the repo root happens to be the working directory --
# it breaks under `pytest /abs/path/to/test_codeagent_plan.py`. Sharing it
# properly means a tests/ harness module plus an edit to P2's committed test
# file, which is outside P3's scope; P4 needs the same harness and is the right
# moment to consolidate all three.


class ScriptedProvider:
    """Offline stand-in for a real provider. Never touches a network."""

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


def final_turn(summary: str = "done", files: list[str] | None = None) -> str:
    return f'```final\n{json.dumps({"summary": summary, "files_changed": files or []})}\n```'


def workspace(tmp_path: Path) -> Workspace:
    root = tmp_path / "ws"
    root.mkdir(exist_ok=True)
    return Workspace(root)


def plan_block(**payload: object) -> str:
    return f"```plan\n{json.dumps(payload)}\n```"


def valid_payload(**overrides: object) -> dict:
    payload = {
        "goal": "make parse_due_date reject empty input",
        "steps": ["read todo.py", "add the guard", "run the tests"],
        "likely_files": ["todo.py"],
        "validation_commands": [["python", "-m", "pytest", "-q"]],
        "completion_criteria": "pytest passes and the guard raises ValueError",
    }
    payload.update(overrides)
    return payload


def budget(max_tokens: int = 1_000_000, planned: str = "10.00") -> BudgetController:
    return BudgetController(max_tokens=max_tokens, planned_budget=Decimal(planned))


def run_planner(
    tmp_path: Path,
    responses: list[str],
    *,
    limits: Limits | None = None,
    raise_on_call: int | None = None,
    max_tokens: int = 1_000_000,
    planned: str = "10.00",
    log: SessionLog | None = None,
    repo_context: str = "",
) -> tuple[PlanOutcome, ScriptedProvider]:
    provider = ScriptedProvider(responses, raise_on_call=raise_on_call)
    outcome = make_plan(
        task_text="fix parse_due_date",
        workspace=workspace(tmp_path),
        gateway=LLMGateway(provider),
        budget=budget(max_tokens, planned),
        model=MODEL,
        task_id="cd-test",
        tool_names=TOOL_NAMES,
        repo_context=repo_context,
        limits=limits if limits is not None else Limits(),
        log=log,
    )
    return outcome, provider


# -- parsing ----------------------------------------------------------------


def test_parses_a_plan_block() -> None:
    payload, error = parse_plan_block(plan_block(**valid_payload()))

    assert error is None
    assert payload is not None
    assert payload["goal"].startswith("make parse_due_date")


def test_malformed_json_is_reported() -> None:
    payload, error = parse_plan_block('```plan\n{"goal": "x", steps: nope}\n```')

    assert payload is None
    assert error is not None
    assert "not valid JSON" in error


def test_a_missing_block_is_reported() -> None:
    payload, error = parse_plan_block("Here is my plan: first I will read the file.")

    assert payload is None
    assert error is not None
    assert "no ```plan block" in error


def test_an_empty_response_is_reported() -> None:
    payload, error = parse_plan_block("   ")

    assert payload is None
    assert error is not None
    assert "empty" in error


def test_two_plan_blocks_are_refused() -> None:
    payload, error = parse_plan_block(f"{plan_block(goal='a')}\n{plan_block(goal='b')}")

    assert payload is None
    assert error is not None
    assert "found 2" in error


def test_a_non_object_body_is_refused() -> None:
    payload, error = parse_plan_block('```plan\n["not", "an", "object"]\n```')

    assert payload is None
    assert error is not None
    assert "must be a JSON object" in error


def test_a_plan_fence_does_not_parse_as_a_turn() -> None:
    """The turn parser and the planner share one block definition but not one
    vocabulary: a ```plan block is not a tool call."""
    from engine.codeagent import protocol

    parsed = protocol.parse(plan_block(**valid_payload()))

    assert isinstance(parsed, protocol.ParseError)


# -- validation: accepting ---------------------------------------------------


def test_a_valid_plan_validates(tmp_path: Path) -> None:
    plan, errors = validate_plan(valid_payload(), workspace=workspace(tmp_path))

    assert errors == []
    assert plan is not None
    assert plan.goal.startswith("make parse_due_date")
    assert plan.steps == ["read todo.py", "add the guard", "run the tests"]
    assert plan.likely_files == ["todo.py"]
    assert plan.validation_commands == [["python", "-m", "pytest", "-q"]]


def test_only_goal_and_steps_are_required(tmp_path: Path) -> None:
    plan, errors = validate_plan({"goal": "g", "steps": ["s"]}, workspace=workspace(tmp_path))

    assert errors == []
    assert plan is not None
    assert plan.likely_files == []
    assert plan.validation_commands == []
    assert plan.completion_criteria == ""


def test_optional_fields_accept_null(tmp_path: Path) -> None:
    payload = valid_payload(likely_files=None, validation_commands=None, risks=None)
    plan, errors = validate_plan(payload, workspace=workspace(tmp_path))

    assert errors == []
    assert plan is not None


def test_multi_line_steps_are_normalized_to_one_line(tmp_path: Path) -> None:
    payload = valid_payload(steps=["read   todo.py\nthen think\tabout it"])
    plan, errors = validate_plan(payload, workspace=workspace(tmp_path))

    assert errors == []
    assert plan is not None
    assert plan.steps == ["read todo.py then think about it"]


def test_overlong_text_is_truncated_not_rejected(tmp_path: Path) -> None:
    limits = Limits(max_plan_text_chars=20)
    payload = valid_payload(goal="g" * 500, steps=["s" * 500])
    plan, errors = validate_plan(payload, workspace=workspace(tmp_path), limits=limits)

    assert errors == []
    assert plan is not None
    assert len(plan.goal) == 20
    assert len(plan.steps[0]) == 20


def test_blank_entries_are_dropped(tmp_path: Path) -> None:
    payload = valid_payload(steps=["real step", "   ", ""], risks=["", "a real risk"])
    plan, errors = validate_plan(payload, workspace=workspace(tmp_path))

    assert errors == []
    assert plan is not None
    assert plan.steps == ["real step"]
    assert plan.risks == ["a real risk"]


# -- validation: rejecting ---------------------------------------------------


def test_a_missing_goal_is_rejected(tmp_path: Path) -> None:
    plan, errors = validate_plan({"steps": ["s"]}, workspace=workspace(tmp_path))

    assert plan is None
    assert any("'goal' is required" in error for error in errors)


def test_a_blank_goal_is_rejected(tmp_path: Path) -> None:
    plan, errors = validate_plan({"goal": "   ", "steps": ["s"]}, workspace=workspace(tmp_path))

    assert plan is None
    assert any("'goal' is required" in error for error in errors)


def test_a_wrongly_typed_goal_is_rejected(tmp_path: Path) -> None:
    plan, errors = validate_plan({"goal": 42, "steps": ["s"]}, workspace=workspace(tmp_path))

    assert plan is None
    assert any("must be a string" in error for error in errors)


def test_missing_steps_are_rejected(tmp_path: Path) -> None:
    plan, errors = validate_plan({"goal": "g"}, workspace=workspace(tmp_path))

    assert plan is None
    assert any("'steps' must be a list" in error for error in errors)


def test_empty_steps_are_rejected(tmp_path: Path) -> None:
    for steps in ([], ["", "  "]):
        plan, errors = validate_plan({"goal": "g", "steps": steps}, workspace=workspace(tmp_path))
        assert plan is None, steps
        assert any("at least one non-empty step" in error for error in errors), steps


def test_non_string_steps_are_rejected(tmp_path: Path) -> None:
    plan, errors = validate_plan({"goal": "g", "steps": [1, 2]}, workspace=workspace(tmp_path))

    assert plan is None
    assert any("must be a string" in error for error in errors)


def test_too_many_steps_are_rejected(tmp_path: Path) -> None:
    payload = valid_payload(steps=[f"step {i}" for i in range(12)])
    plan, errors = validate_plan(payload, workspace=workspace(tmp_path), limits=Limits(max_plan_steps=7))

    assert plan is None
    assert any("more than max_plan_steps (7)" in error for error in errors)


def test_too_many_likely_files_are_rejected(tmp_path: Path) -> None:
    payload = valid_payload(likely_files=[f"f{i}.py" for i in range(20)])
    plan, errors = validate_plan(payload, workspace=workspace(tmp_path), limits=Limits(max_plan_files=10))

    assert plan is None
    assert any("more than max_plan_files (10)" in error for error in errors)


def test_too_many_validation_commands_are_rejected(tmp_path: Path) -> None:
    payload = valid_payload(validation_commands=[["pytest"]] * 9)
    plan, errors = validate_plan(
        payload, workspace=workspace(tmp_path), limits=Limits(max_plan_validation_commands=3)
    )

    assert plan is None
    assert any("more than max_plan_validation_commands (3)" in error for error in errors)


def test_too_many_notes_are_rejected(tmp_path: Path) -> None:
    payload = valid_payload(assumptions=[f"a{i}" for i in range(9)])
    plan, errors = validate_plan(payload, workspace=workspace(tmp_path), limits=Limits(max_plan_notes=5))

    assert plan is None
    assert any("more than max_plan_notes (5)" in error for error in errors)


# -- validation: paths reuse the P1 guard ------------------------------------


@pytest.mark.parametrize(
    "bad_path",
    ["/etc/passwd", "../escape.py", "a/../../out.py"],
)
def test_paths_outside_the_workspace_are_rejected(tmp_path: Path, bad_path: str) -> None:
    payload = valid_payload(likely_files=[bad_path])
    plan, errors = validate_plan(payload, workspace=workspace(tmp_path))

    assert plan is None
    assert any("is not usable" in error for error in errors)
    # Distinguishable from a credential refusal, so the model corrects the
    # right thing: a bad location, not a forbidden file.
    assert any("WorkspaceEscape" in error for error in errors)


@pytest.mark.parametrize("secret", [".env", "id_rsa", "server.pem", ".git/config", "secrets.py"])
def test_credential_paths_are_rejected(tmp_path: Path, secret: str) -> None:
    payload = valid_payload(likely_files=[secret])
    plan, errors = validate_plan(payload, workspace=workspace(tmp_path))

    assert plan is None
    assert any("is not usable" in error for error in errors)
    assert any("ForbiddenPath" in error for error in errors)


def test_likely_files_are_normalized_to_posix_relative(tmp_path: Path) -> None:
    payload = valid_payload(likely_files=["pkg\\mod.py"])
    plan, errors = validate_plan(payload, workspace=workspace(tmp_path))

    assert errors == []
    assert plan is not None
    assert plan.likely_files == ["pkg/mod.py"]


def test_non_string_likely_files_are_rejected(tmp_path: Path) -> None:
    payload = valid_payload(likely_files=[1, 2])
    plan, errors = validate_plan(payload, workspace=workspace(tmp_path))

    assert plan is None
    assert any("'likely_files' must be a list of strings" in error for error in errors)


# -- validation: commands reuse the P1 policy --------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["git", "push"],
        ["git", "reset", "--hard"],
        ["bash", "-c", "ls"],
        ["python", "-m", "pip", "install", "x"],
        ["rm", "-rf", "."],
    ],
)
def test_unsupported_validation_commands_are_rejected(tmp_path: Path, argv: list[str]) -> None:
    payload = valid_payload(validation_commands=[argv])
    plan, errors = validate_plan(payload, workspace=workspace(tmp_path), policy=DEFAULT_POLICY)

    assert plan is None
    assert any("is not allowed" in error for error in errors)


def test_a_shell_string_validation_command_is_rejected(tmp_path: Path) -> None:
    payload = valid_payload(validation_commands=["python -m pytest -q"])
    plan, errors = validate_plan(payload, workspace=workspace(tmp_path))

    assert plan is None
    assert any("argv list, not a shell string" in error for error in errors)


def test_allowed_validation_commands_pass(tmp_path: Path) -> None:
    payload = valid_payload(
        validation_commands=[["python", "-m", "pytest", "-q"], ["ruff", "check", "."]]
    )
    plan, errors = validate_plan(payload, workspace=workspace(tmp_path))

    assert errors == []
    assert plan is not None
    assert len(plan.validation_commands) == 2


def test_every_error_is_collected_not_just_the_first(tmp_path: Path) -> None:
    payload = {"steps": [], "likely_files": ["../x.py"], "validation_commands": [["git", "push"]]}
    plan, errors = validate_plan(payload, workspace=workspace(tmp_path))

    assert plan is None
    assert len(errors) >= 3


# -- the planning call -------------------------------------------------------


def test_a_valid_plan_is_returned_on_the_first_attempt(tmp_path: Path) -> None:
    outcome, provider = run_planner(tmp_path, [plan_block(**valid_payload())])

    assert outcome.status is PlanStatus.OK
    assert outcome.ok
    assert outcome.plan is not None
    assert outcome.attempts == 1
    assert outcome.errors == []
    assert provider.calls == 1


def test_an_invalid_plan_is_retried_once_and_can_recover(tmp_path: Path) -> None:
    outcome, provider = run_planner(
        tmp_path,
        ["I will just wing it.", plan_block(**valid_payload())],
        limits=Limits(max_plan_attempts=2),
    )

    assert outcome.status is PlanStatus.OK
    assert outcome.attempts == 2
    assert provider.calls == 2
    # The validation errors were handed back, not silently retried.
    assert "PLAN REJECTED" in provider.seen_messages[1][-1].content


def test_validation_errors_are_fed_back_verbatim(tmp_path: Path) -> None:
    outcome, provider = run_planner(
        tmp_path,
        [plan_block(goal="g", steps=["s"], validation_commands=[["git", "push"]]),
         plan_block(**valid_payload())],
    )

    assert outcome.status is PlanStatus.OK
    retry_prompt = provider.seen_messages[1][-1].content
    assert "git" in retry_prompt
    assert "not allowed" in retry_prompt


def test_planning_attempts_exhausted_is_rejected_not_success(tmp_path: Path) -> None:
    outcome, provider = run_planner(
        tmp_path, ["no block at all"], limits=Limits(max_plan_attempts=2)
    )

    assert outcome.status is PlanStatus.REJECTED
    assert not outcome.ok
    assert outcome.plan is None
    assert outcome.attempts == 2
    assert outcome.errors
    assert "no valid plan after 2 attempt(s)" in outcome.reason
    assert provider.calls == 2


def test_a_single_attempt_limit_is_honoured(tmp_path: Path) -> None:
    outcome, provider = run_planner(tmp_path, ["prose"], limits=Limits(max_plan_attempts=1))

    assert outcome.status is PlanStatus.REJECTED
    assert outcome.attempts == 1
    assert provider.calls == 1


def test_a_provider_failure_is_unavailable_not_rejected(tmp_path: Path) -> None:
    outcome, provider = run_planner(
        tmp_path, [plan_block(**valid_payload())], raise_on_call=1
    )

    assert outcome.status is PlanStatus.UNAVAILABLE
    assert outcome.plan is None
    assert "planning call failed" in outcome.reason
    assert "RuntimeError" in outcome.reason
    assert provider.calls == 1


def test_budget_exhaustion_is_unavailable(tmp_path: Path) -> None:
    outcome, provider = run_planner(tmp_path, [plan_block(**valid_payload())], max_tokens=10)

    assert outcome.status is PlanStatus.UNAVAILABLE
    assert "budget exhausted" in outcome.reason
    assert provider.calls == 0


def test_planning_never_raises_for_an_unusable_plan(tmp_path: Path) -> None:
    for responses in (["prose"], [plan_block(goal="g")], ["{}"]):
        outcome, _ = run_planner(tmp_path, responses)
        assert isinstance(outcome, PlanOutcome)
        assert outcome.status is not PlanStatus.OK


def test_the_planner_is_told_the_task_and_the_context(tmp_path: Path) -> None:
    _, provider = run_planner(
        tmp_path, [plan_block(**valid_payload())], repo_context="todo.py  (42 B)"
    )

    request = provider.seen_messages[0][0].content
    assert "fix parse_due_date" in request
    assert "todo.py  (42 B)" in request
    assert "no contents" in request


def test_repo_context_is_bounded(tmp_path: Path) -> None:
    _, provider = run_planner(
        tmp_path,
        [plan_block(**valid_payload())],
        repo_context="x" * 50_000,
        limits=Limits(max_plan_context_chars=100),
    )

    assert len(provider.seen_messages[0][0].content) < 1_000


def test_the_planner_prompt_lists_the_real_tool_names(tmp_path: Path) -> None:
    _, provider = run_planner(tmp_path, [plan_block(**valid_payload())])

    system = provider.seen_systems[0] or ""
    for name in TOOL_NAMES:
        assert name in system
    assert "```plan" in system


def test_the_plan_call_uses_the_planning_token_cap(tmp_path: Path) -> None:
    provider = ScriptedProvider([plan_block(**valid_payload())])
    captured: list[int] = []
    original = provider.generate

    def spy(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        captured.append(int(kwargs.get("max_tokens", 0)))
        return original(*args, **kwargs)  # type: ignore[arg-type]

    provider.generate = spy  # type: ignore[method-assign]
    make_plan(
        task_text="t",
        workspace=workspace(tmp_path),
        gateway=LLMGateway(provider),
        budget=budget(),
        model=MODEL,
        task_id="cd-test",
        tool_names=TOOL_NAMES,
        limits=Limits(plan_max_tokens=1_200),
    )

    assert captured == [1_200]


# -- no tool execution during planning ---------------------------------------


def test_planning_executes_no_tool(tmp_path: Path) -> None:
    """A plan naming files and commands must not touch either."""
    marker = tmp_path / "ws" / "todo.py"
    payload = valid_payload(
        likely_files=["todo.py"], validation_commands=[["python", "-m", "pytest", "-q"]]
    )
    outcome, _ = run_planner(tmp_path, [plan_block(**payload)])

    assert outcome.status is PlanStatus.OK
    # The planner validated a path to a file that does not exist and never
    # created, read, or ran anything.
    assert not marker.exists()
    assert list((tmp_path / "ws").iterdir()) == []


def test_the_planner_module_cannot_reach_the_tool_registry() -> None:
    """Structural proof rather than a promise: plan.py never imports the
    registry, so there is no code path from planning to execution."""
    source = Path(plan_module.__file__).read_text(encoding="utf-8")

    assert "tools.registry" not in source
    assert "TOOL_REGISTRY" not in source
    assert "tools.shell" not in source


# -- observability -----------------------------------------------------------


def test_the_log_records_attempts_and_the_result(tmp_path: Path) -> None:
    log = SessionLog()
    run_planner(tmp_path, ["prose", plan_block(**valid_payload())], log=log)

    kinds = [event.kind for event in log.events]
    assert kinds.count("plan_attempt") == 2
    assert "plan_rejected" in kinds
    assert log.of_kind("plan_result")[0].payload["status"] == "OK"


def test_the_log_records_validation_errors(tmp_path: Path) -> None:
    log = SessionLog()
    run_planner(tmp_path, [plan_block(goal="g", steps=[])], limits=Limits(max_plan_attempts=1), log=log)

    rejected = log.of_kind("plan_rejected")[0]
    assert any("non-empty step" in error for error in rejected.payload["errors"])


def test_the_log_records_counts_never_the_response_text(tmp_path: Path) -> None:
    secret = "SECRET PLANNING MONOLOGUE THAT MUST NOT BE PERSISTED"
    log = SessionLog()
    run_planner(tmp_path, [secret], limits=Limits(max_plan_attempts=1), log=log)

    dumped = json.dumps([event.to_dict() for event in log.events])
    assert secret not in dumped
    assert log.of_kind("plan_attempt")[0].payload["text_chars"] == len(secret)


def test_the_stored_plan_is_structured_data(tmp_path: Path) -> None:
    log = SessionLog()
    run_planner(tmp_path, [plan_block(**valid_payload())], log=log)

    stored = log.of_kind("plan_result")[0].payload["plan"]
    assert stored["goal"].startswith("make parse_due_date")
    assert stored["steps"]


# -- rendering ---------------------------------------------------------------


def test_a_plan_renders_as_context_with_an_explicit_disclaimer() -> None:
    outcome = PlanOutcome(
        status=PlanStatus.OK,
        plan=Plan(
            goal="fix the guard",
            steps=["read", "edit"],
            likely_files=["todo.py"],
            validation_commands=[["pytest", "-q"]],
            assumptions=["it is python"],
            risks=["the fix breaks an old test"],
            completion_criteria="pytest passes",
        ),
        attempts=1,
    )

    rendered = render_plan_context(outcome)

    assert "goal: fix the guard" in rendered
    assert "1. read" in rendered
    assert "likely files: todo.py" in rendered
    assert "validation: pytest -q" in rendered
    assert "done when: pytest passes" in rendered
    assert "not a constraint" in rendered


@pytest.mark.parametrize("status", [PlanStatus.REJECTED, PlanStatus.UNAVAILABLE])
def test_a_failed_plan_renders_as_an_explicit_absence(status: PlanStatus) -> None:
    rendered = render_plan_context(PlanOutcome(status=status, reason="it went wrong"))

    assert "PLAN: none" in rendered
    assert status.value in rendered
    assert "it went wrong" in rendered
    # The fallback is conservative in a stated way, not a hidden mode.
    assert "inspect the workspace before changing anything" in rendered


def test_rendering_is_deterministic() -> None:
    outcome = PlanOutcome(status=PlanStatus.OK, plan=Plan(goal="g", steps=["s"]), attempts=1)
    assert render_plan_context(outcome) == render_plan_context(outcome)


# -- integration with CodingSession ------------------------------------------


def build_session(
    tmp_path: Path, responses: list[str], planning: PlanOutcome | None
) -> tuple[CodingSession, ScriptedProvider]:
    provider = ScriptedProvider(responses)
    session = CodingSession(
        task_text="fix parse_due_date",
        workspace=workspace(tmp_path),
        gateway=LLMGateway(provider),
        budget=budget(),
        model=MODEL,
        task_id="cd-test",
        log=SessionLog(),
        clock=StepClock(step=0.0),
        planning=planning,
    )
    return session, provider


def test_a_plan_reaches_the_sessions_opening_message(tmp_path: Path) -> None:
    outcome = PlanOutcome(
        status=PlanStatus.OK, plan=Plan(goal="fix the guard", steps=["read", "edit"]), attempts=1
    )
    session, provider = build_session(tmp_path, [final_turn()], outcome)

    session.run()

    opening = provider.seen_messages[0][0].content
    assert "TASK" in opening
    assert "goal: fix the guard" in opening


def test_the_session_records_a_successful_plan(tmp_path: Path) -> None:
    outcome = PlanOutcome(
        status=PlanStatus.OK, plan=Plan(goal="g", steps=["s"]), attempts=1
    )
    session, _ = build_session(tmp_path, [final_turn()], outcome)

    state = session.run()

    assert state.plan is not None
    assert state.plan["goal"] == "g"
    assert state.planning_status == "OK"
    assert state.planning_errors == []
    assert state.usage.planning_attempts == 1


def test_the_planless_fallback_runs_and_records_why(tmp_path: Path) -> None:
    outcome = PlanOutcome(
        status=PlanStatus.REJECTED,
        plan=None,
        attempts=2,
        errors=["'steps' must contain at least one non-empty step"],
        reason="no valid plan after 2 attempt(s)",
    )
    session, provider = build_session(tmp_path, [final_turn()], outcome)

    state = session.run()

    # The session still runs -- a plan is advisory, so losing it is not fatal.
    assert state.status is SessionStatus.COMPLETED_UNVERIFIED
    # And the failure is preserved rather than looking like an unplanned run.
    assert state.plan is None
    assert state.planning_status == "REJECTED"
    assert state.planning_errors == ["'steps' must contain at least one non-empty step"]
    assert state.usage.planning_attempts == 2
    assert "PLAN: none" in provider.seen_messages[0][0].content


def test_a_failed_plan_is_never_fabricated_into_a_successful_one(tmp_path: Path) -> None:
    outcome = PlanOutcome(status=PlanStatus.UNAVAILABLE, reason="provider down", attempts=0)
    session, _ = build_session(tmp_path, [final_turn()], outcome)

    state = session.run()

    assert state.plan is None
    assert state.planning_status == "UNAVAILABLE"
    assert state.planning_status != "OK"


def test_no_planning_at_all_is_distinguishable_from_failed_planning(tmp_path: Path) -> None:
    session, provider = build_session(tmp_path, [final_turn()], None)

    state = session.run()

    # None means never attempted; a failure would have carried a status string.
    assert state.planning_status is None
    assert state.plan is None
    assert "PLAN" not in provider.seen_messages[0][0].content


def test_the_session_start_event_carries_planning_metadata(tmp_path: Path) -> None:
    outcome = PlanOutcome(status=PlanStatus.OK, plan=Plan(goal="g", steps=["s"]), attempts=2)
    session, _ = build_session(tmp_path, [final_turn()], outcome)

    session.run()

    start = session.log.of_kind("session_start")[0]
    assert start.payload["planning_status"] == "OK"
    assert start.payload["planning_attempts"] == 2


def test_planning_state_survives_serialization(tmp_path: Path) -> None:
    outcome = PlanOutcome(
        status=PlanStatus.OK,
        plan=Plan(goal="g", steps=["s"], validation_commands=[["pytest"]]),
        attempts=1,
    )
    session, _ = build_session(tmp_path, [final_turn()], outcome)

    payload = json.loads(session.run().to_json())

    assert payload["plan"]["goal"] == "g"
    assert payload["plan"]["validation_commands"] == [["pytest"]]
    assert payload["planning_status"] == "OK"
    assert payload["usage"]["planning_attempts"] == 1


def test_a_plan_does_not_constrain_which_tools_run(tmp_path: Path) -> None:
    """The plan names one file; the session uses a different tool entirely and
    is not blocked."""
    outcome = PlanOutcome(
        status=PlanStatus.OK,
        plan=Plan(goal="g", steps=["s"], likely_files=["todo.py"]),
        attempts=1,
    )
    session, _ = build_session(
        tmp_path,
        ['```tool\n{"name": "list_files", "args": {}}\n```', final_turn()],
        outcome,
    )

    state = session.run()

    assert state.status is SessionStatus.COMPLETED_UNVERIFIED
    assert state.tool_results[0].result.ok


# -- offline guarantee -------------------------------------------------------


def test_planning_runs_with_no_provider_sdk_and_no_network(tmp_path: Path) -> None:
    outcome, provider = run_planner(tmp_path, [plan_block(**valid_payload())])

    assert provider.name == "scripted"
    assert outcome.status is PlanStatus.OK
