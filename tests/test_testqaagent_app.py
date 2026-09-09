"""Agent #4: the Test/QA Agent.

Four groups, each proving something the one below it cannot:

    prompt      the QA system prompt covers the stated procedure -- inspect,
                map, add focused tests, never patch production to cheat a new
                test, never weaken an existing one -- and never encourages
                either failure mode
    structure   this agent reuses codeagent's session/verify/report machinery
                rather than reimplementing it, and never touches the legacy
                orchestrator or the verdict/judge/benchmark layer directly
    stack       a whole offline run -- real tools, real capabilities, real
                AgentGate verification, real verdict.gate -- driven by a
                scripted provider, proving PASSED is reachable only through
                the same unchanged route run_coding_task and
                run_refactor_task use
    safety      the two things this agent must never do (patch production to
                make its own new test pass; weaken an existing test) stay
                refused by the prompt, not merely omitted

Every test here is offline: no network, no API key, no real subprocess beyond
what run_tests already spawns for the fixture's own pytest.
"""

import ast
import shutil
from decimal import Decimal
from pathlib import Path

import pytest
from codeagent_harness import CLEAN_CRITIC, MODEL, ScenarioProvider, critic, final_turn, tool_turn

from engine.codeagent.app import CodeRunResult, WorkspaceRejected, exit_code_for
from engine.codeagent.limits import DEFAULT_LIMITS
from engine.codeagent.report import FinalReport
from engine.codeagent.state import SessionStatus
from engine.runtime.gateway import LLMGateway
from engine.testqaagent.app import QARunResult, run_qa_task
from engine.testqaagent.limits import QA_LIMITS
from engine.testqaagent.prompt import AGENT_NAME, build_qa_prompt
from engine.verification.judge import LENSES

FIXTURES = Path(__file__).resolve().parent.parent / "examples"
LENS_PROMPTS = tuple(LENSES.values())

NEW_EDGE_CASE_TEST = (
    "from todo import parse_due_date\n\n\n"
    "def test_parses_a_december_date() -> None:\n"
    '    """A month-end boundary the existing suite never exercised."""\n'
    '    assert parse_due_date("2026-12-31") == (2026, 12, 31)\n'
)

QA_TASK = (
    "todo.py's parse_due_date has only one test, and it never exercises a month-end "
    "boundary. Add a focused regression test for that case; do not change todo.py."
)

QA_TURNS = [
    tool_turn("detect_tests"),
    tool_turn("list_files"),
    tool_turn("repo_graph", {"op": "find_references", "name": "parse_due_date"}),
    tool_turn("read_file", {"path": "test_todo.py"}),
    tool_turn(
        "write_file", {"path": "test_todo_edge_cases.py", "content": NEW_EDGE_CASE_TEST}
    ),
    tool_turn("run_tests"),
    final_turn("added a December boundary regression test; todo.py is unchanged", ["test_todo_edge_cases.py"]),
]


def fixture_copy(tmp_path: Path, name: str = "todo_cli") -> Path:
    workspace = tmp_path / "ws"
    shutil.copytree(FIXTURES / name, workspace)
    return workspace


def provider(agent_turns: list[str], judge_rounds: list[str] | None = None) -> ScenarioProvider:
    # No plan_turns: the Test/QA Agent does not plan, so every non-judge call
    # is routed as an agent turn regardless.
    return ScenarioProvider(
        agent_turns=agent_turns, judge_rounds=judge_rounds or [CLEAN_CRITIC], lens_prompts=LENS_PROMPTS
    )


def go(tmp_path: Path, agent_turns: list[str], *, judge_rounds=None, **kwargs):  # type: ignore[no-untyped-def]
    fake = provider(agent_turns, judge_rounds)
    result = run_qa_task(
        task_text=QA_TASK,
        workspace_path=kwargs.pop("workspace", None) or fixture_copy(tmp_path),
        gateway=LLMGateway(fake),
        model=MODEL,
        judge_model=MODEL,
        planned_budget=Decimal("10.00"),
        task_id="qa-app",
        **kwargs,
    )
    return result, fake


# -- the prompt -----------------------------------------------------------------


def _prompt_text() -> str:
    from engine.codeagent.tools.registry import TOOL_REGISTRY

    return build_qa_prompt(TOOL_REGISTRY)


def flat(text: str) -> str:
    return " ".join(text.split()).lower()


def test_the_prompt_advertises_every_tool_by_name_and_description() -> None:
    from engine.codeagent.tools.registry import TOOL_REGISTRY

    text = _prompt_text()
    for name, tool in TOOL_REGISTRY.items():
        assert f"- {name}: {tool.description}" in text


def test_the_prompt_states_coverage_without_changing_the_product_first() -> None:
    lowered = flat(_prompt_text())
    assert "without changing what the product does" in lowered


def test_the_prompt_covers_the_stated_procedure() -> None:
    lowered = flat(_prompt_text())
    assert "detect_tests" in lowered
    assert "repo_graph" in lowered
    assert "analyze_code" in lowered
    assert "smallest focused test" in lowered
    assert "narrowest relevant test" in lowered


def test_the_prompt_forbids_patching_production_to_cheat_a_new_test() -> None:
    lowered = flat(_prompt_text())
    assert "that is a real finding" in lowered
    assert "rather than editing production code to make the new test pass" in lowered


def test_the_prompt_never_endorses_weakening_an_existing_test() -> None:
    lowered = flat(_prompt_text())
    assert "never weaken, delete, or skip an existing test" in lowered


def test_the_prompt_states_ending_the_session_is_not_a_verdict() -> None:
    lowered = flat(_prompt_text())
    assert "ending the session is not a verdict" in lowered


def test_the_prompt_names_no_verdict_or_judge_internals() -> None:
    lowered = flat(_prompt_text())
    for phrase in ("verdict.gate", "severity threshold", "judge prompt", "benchmark fixture"):
        assert phrase not in lowered


def test_the_skills_catalogue_is_appended_only_when_present() -> None:
    from engine.codeagent.tools.registry import TOOL_REGISTRY

    bare = build_qa_prompt(TOOL_REGISTRY)
    assert "Available skills" not in bare

    with_skills = build_qa_prompt(TOOL_REGISTRY, skills_catalogue="- testing: ...")
    assert "Available skills" in with_skills


# -- structure: reuse, not duplication -----------------------------------------


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_the_agent_never_imports_the_legacy_orchestrator() -> None:
    for path in sorted(Path("src/engine/testqaagent").glob("*.py")):
        offending = {name for name in _imports(path) if name.startswith("engine.orchestrator")}
        assert not offending, f"{path}: imports {sorted(offending)}"


def test_the_legacy_orchestrator_testing_agent_is_untouched() -> None:
    """A guard on this phase itself: Agent #4 must not have been folded into
    or replaced the older prompt-file agent of the same name."""
    legacy = Path("src/engine/orchestrator/agents/testing.py")
    assert legacy.is_file()
    assert "PromptFileAgent" in legacy.read_text(encoding="utf-8")


def test_the_agent_never_imports_verification_internals_directly() -> None:
    """Every path to a verdict goes through codeagent.verify, unchanged --
    this module must not reach engine.verification.* itself, which would be a
    second, unaccountable route to a PASSED status."""
    for path in sorted(Path("src/engine/testqaagent").glob("*.py")):
        offending = {name for name in _imports(path) if name.startswith("engine.verification")}
        assert not offending, f"{path}: imports {sorted(offending)}"


def test_the_agent_never_imports_debug_repro_suite_proof_machinery() -> None:
    for path in sorted(Path("src/engine/testqaagent").glob("*.py")):
        offending = {name for name in _imports(path) if name.startswith("engine.debugagent")}
        assert not offending, f"{path}: imports {sorted(offending)}"


def test_the_run_result_is_the_coding_agents_own_type_not_a_copy() -> None:
    """No duplicated dataclass: a QA run and a coding run report the identical
    shape, so the alias is the type itself -- and it is not redefined as a
    separate copy the Refactoring Agent's own alias already is."""
    from engine.refactoragent.app import RefactorRunResult

    assert QARunResult is CodeRunResult
    assert QARunResult is RefactorRunResult


def test_the_limits_preset_only_overrides_settings_no_new_fields() -> None:
    from dataclasses import fields

    assert {f.name for f in fields(QA_LIMITS)} == {f.name for f in fields(DEFAULT_LIMITS)}
    assert QA_LIMITS.max_files_changed < DEFAULT_LIMITS.max_files_changed
    assert QA_LIMITS.max_repair_rounds == DEFAULT_LIMITS.max_repair_rounds


def test_the_agent_reuses_run_verified_sessions_injection_points() -> None:
    """No second verified-run loop: this agent's own _execute calls the exact
    function Agent #3 extended, with only a system_prompt and agent_name of
    its own -- proven by inspecting the actual call, not by trusting the
    docstring."""
    import inspect

    from engine.testqaagent import app as qa_app

    source = inspect.getsource(qa_app._execute)
    assert "run_verified_session(" in source
    assert "system_prompt=system_prompt" in source
    assert "agent_name=AGENT_NAME" in source


# -- the whole offline stack ---------------------------------------------------


def test_a_focused_regression_test_passes_through_real_agentgate(tmp_path: Path) -> None:
    result, fake = go(tmp_path, QA_TURNS)

    assert isinstance(result, CodeRunResult)
    assert isinstance(result.report, FinalReport)
    assert result.report.status == SessionStatus.PASSED.value
    assert result.exit_code == exit_code_for(SessionStatus.PASSED)
    assert result.report.files_changed == ["test_todo_edge_cases.py"]
    # No planning phase for this agent.
    assert result.report.planning_status is None
    assert result.report.plan is None
    # The persona and metrics label actually reached the loop.
    assert fake.seen_systems[0] is not None
    assert fake.seen_systems[0].startswith("You are a test and QA agent")


def test_a_judge_blocked_change_ends_unverified_not_passed(tmp_path: Path) -> None:
    defect = [
        {"id": "C1", "category": "CORRECTNESS", "severity": "HIGH", "location": "test_todo_edge_cases.py:1", "fix": "f", "grounding_status": "in_contract_reachable", "violated_requirement": "the task requires this behaviour", "code_path": "solution.py:1", "trigger": "the documented input"}
    ]
    result, _ = go(tmp_path, QA_TURNS, judge_rounds=[critic(defect)])

    assert result.report.status == SessionStatus.UNVERIFIED.value
    assert result.report.status != SessionStatus.PASSED.value
    assert result.report.defects


def test_ending_without_a_change_never_reaches_agentgate(tmp_path: Path) -> None:
    result, _ = go(tmp_path, [final_turn("looked around, coverage is already adequate")])

    assert result.report.status == SessionStatus.UNVERIFIED.value
    assert result.report.verification_ran is False


def test_the_engines_own_source_tree_is_refused(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceRejected):
        run_qa_task(
            task_text=QA_TASK,
            workspace_path=Path(__file__).resolve().parent.parent,
            gateway=LLMGateway(provider([final_turn("done")])),
            model=MODEL,
            judge_model=MODEL,
        )


def test_capabilities_default_on_and_are_actually_reachable(tmp_path: Path) -> None:
    """repo_graph, detect_tests and the first-party skills are on by default --
    the scripted run calls two of them, and both must have actually run rather
    than being refused as unknown tools."""
    result, _ = go(tmp_path, QA_TURNS)

    sources = result.report.context_sources
    assert sources["graph_queries"]
    assert sources["graph_queries"][0]["op"] == "find_references"
    # The fixture's test file sits at its root rather than under tests/, so
    # detection is honestly UNKNOWN here -- the claim under test is that the
    # tool ran and was recorded at all, not what this particular tree implies.
    assert sources["test_detection"] is not None
    assert "testing" in sources["skills"]["advertised"]


def test_capabilities_can_be_turned_off(tmp_path: Path) -> None:
    result, _ = go(
        tmp_path,
        [tool_turn("list_files"), final_turn("looked, made no change")],
        detect_tests=False,
        analyze=False,
        graph=False,
        include_builtin_skills=False,
    )
    sources = result.report.context_sources
    assert sources["graph_queries"] is None
    assert sources["test_detection"] is None
    assert sources["skills"]["advertised"] == []


def test_the_run_is_recorded_in_the_database_under_its_own_metrics_label(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"

    go(tmp_path, QA_TURNS, db_path=db_path)

    from engine.state import db

    with db.connect(db_path) as conn:
        runs = conn.execute("SELECT id, status FROM runs").fetchall()
        metrics = conn.execute(
            "SELECT agent_name FROM agent_execution_metrics WHERE run_id = ?", (runs[0][0],)
        ).fetchall()

    assert runs[0][1] == "passed"
    names = {row[0] for row in metrics}
    assert AGENT_NAME in names
    assert "TestQAAgent.turn" in names
    # No planning phase, so no plan-metrics row should exist for this run.
    assert "CodingAgent.plan" not in names
    assert any(name.startswith("judge:") for name in names)


def test_a_run_never_widens_the_shared_tool_registry(tmp_path: Path) -> None:
    from engine.codeagent.tools.registry import TOOL_REGISTRY

    before = dict(TOOL_REGISTRY)
    go(tmp_path, QA_TURNS)
    assert dict(TOOL_REGISTRY) == before
