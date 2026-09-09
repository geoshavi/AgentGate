"""Agent #3: the Refactoring Agent.

Four groups, each proving something the one below it cannot:

    verify      the two injection points added to run_verified_session
                (system_prompt, agent_name) reach CodingSession, in both the
                initial round and every repair round, and a caller that
                supplies neither gets the Coding Agent's byte-identical
                behaviour -- nothing about verification itself changed
    prompt      the refactoring system prompt covers the stated procedure and
                never encourages weakening a test
    structure   this agent reuses codeagent's session/verify/report machinery
                rather than reimplementing it, and never touches the legacy
                orchestrator or the verdict/judge/benchmark layer directly
    stack       a whole offline run -- real tools, real capabilities, real
                AgentGate verification, real verdict.gate -- driven by a
                scripted provider, proving PASSED is reachable only through
                the same unchanged route run_coding_task uses

Every test here is offline: no network, no API key, no real subprocess beyond
what run_tests already spawns for the fixture's own pytest.
"""

import ast
import shutil
from decimal import Decimal
from pathlib import Path

import pytest
from codeagent_harness import CLEAN_CRITIC, MODEL, ScenarioProvider, critic, final_turn, tool_turn

from engine.codeagent.app import CodeRunResult, WorkspaceRejected, exit_code_for, run_coding_task
from engine.codeagent.limits import DEFAULT_LIMITS, Limits
from engine.codeagent.report import FinalReport
from engine.codeagent.state import SessionStatus
from engine.codeagent.verify import run_verified_session
from engine.codeagent.workspace import Workspace
from engine.refactoragent.app import RefactorRunResult, run_refactor_task
from engine.refactoragent.limits import REFACTOR_LIMITS
from engine.refactoragent.prompt import AGENT_NAME, build_refactor_prompt
from engine.runtime.budget import BudgetController
from engine.runtime.gateway import LLMGateway
from engine.verification.judge import LENSES

FIXTURES = Path(__file__).resolve().parent.parent / "examples"
LENS_PROMPTS = tuple(LENSES.values())

REFACTORED_TODO = (
    '"""A tiny due-date helper, deliberately incomplete."""\n\n\n'
    "def _split_iso_parts(raw: str) -> list[str]:\n"
    '    """The three dash-separated fields of an ISO date string."""\n'
    "    return raw.split(\"-\")\n\n\n"
    "def parse_due_date(raw: str) -> tuple[int, int, int]:\n"
    '    """Parse an ISO date of the form YYYY-MM-DD into (year, month, day)."""\n'
    "    parts = _split_iso_parts(raw)\n"
    "    return int(parts[0]), int(parts[1]), int(parts[2])\n"
)

REFACTOR_TASK = (
    "todo.py's parse_due_date does one thing, splitting the raw string, inline. "
    "Extract that into a small named helper without changing what parse_due_date "
    "returns for valid input."
)

REFACTOR_TURNS = [
    tool_turn("list_files"),
    tool_turn("repo_graph", {"op": "show_module_graph"}),
    tool_turn("detect_tests"),
    tool_turn("read_file", {"path": "todo.py"}),
    tool_turn(
        "write_file", {"path": "todo.py", "content": REFACTORED_TODO, "overwrite": True}
    ),
    tool_turn("run_tests"),
    final_turn("extracted _split_iso_parts; parse_due_date's return value is unchanged", ["todo.py"]),
]


def fixture_copy(tmp_path: Path, name: str = "todo_cli") -> Path:
    workspace = tmp_path / "ws"
    shutil.copytree(FIXTURES / name, workspace)
    return workspace


def provider(agent_turns: list[str], judge_rounds: list[str] | None = None) -> ScenarioProvider:
    # No plan_turns: the Refactoring Agent does not plan, so every non-judge
    # call is routed as an agent turn regardless.
    return ScenarioProvider(
        agent_turns=agent_turns, judge_rounds=judge_rounds or [CLEAN_CRITIC], lens_prompts=LENS_PROMPTS
    )


def go(tmp_path: Path, agent_turns: list[str], *, judge_rounds=None, **kwargs):  # type: ignore[no-untyped-def]
    fake = provider(agent_turns, judge_rounds)
    result = run_refactor_task(
        task_text=REFACTOR_TASK,
        workspace_path=kwargs.pop("workspace", None) or fixture_copy(tmp_path),
        gateway=LLMGateway(fake),
        model=MODEL,
        judge_model=MODEL,
        planned_budget=Decimal("10.00"),
        task_id="rf-app",
        **kwargs,
    )
    return result, fake


# -- run_verified_session's two new injection points --------------------------


def ws(tmp_path: Path) -> Workspace:
    root = tmp_path / "ws"
    root.mkdir(exist_ok=True)
    return Workspace(root)


def budget() -> BudgetController:
    return BudgetController(max_tokens=1_000_000, planned_budget=Decimal("10.00"))


def test_the_default_produces_the_coding_agents_own_prompt_and_label(tmp_path: Path) -> None:
    """No override -- every existing call site is unchanged."""
    fake = ScenarioProvider(agent_turns=[final_turn("done")])
    run_verified_session(
        task_text="t",
        workspace=ws(tmp_path),
        gateway=LLMGateway(fake),
        budget=budget(),
        model=MODEL,
        judge_model=MODEL,
        task_id="t",
        limits=DEFAULT_LIMITS,
    )
    assert fake.seen_systems[0] is not None
    assert fake.seen_systems[0].startswith("You are a coding agent")


def test_an_injected_prompt_and_label_reach_the_initial_session(tmp_path: Path) -> None:
    fake = ScenarioProvider(agent_turns=[final_turn("done")])
    custom = "You are a refactoring agent. CUSTOM MARKER."
    run_verified_session(
        task_text="t",
        workspace=ws(tmp_path),
        gateway=LLMGateway(fake),
        budget=budget(),
        model=MODEL,
        judge_model=MODEL,
        task_id="t",
        limits=DEFAULT_LIMITS,
        system_prompt=custom,
        agent_name="RefactoringAgent.turn",
    )
    assert fake.seen_systems[0] == custom


def test_an_injected_prompt_reaches_every_repair_round(tmp_path: Path) -> None:
    """The repair-round CodingSession construction gets the same override too,
    not just the initial one -- both were changed, and this proves both."""
    custom = "You are a refactoring agent. CUSTOM MARKER."
    defect = [{"id": "C1", "category": "CORRECTNESS", "severity": "HIGH", "location": "x.py:1", "fix": "f", "grounding_status": "in_contract_reachable", "violated_requirement": "the task requires this behaviour", "code_path": "solution.py:1", "trigger": "the documented input"}]
    fake = ScenarioProvider(
        agent_turns=[
            tool_turn("write_file", {"path": "x.py", "content": "x = 1\n"}),
            final_turn("first"),
            final_turn("second"),
        ],
        judge_rounds=[critic(defect), CLEAN_CRITIC],
        lens_prompts=LENS_PROMPTS,
    )
    run_verified_session(
        task_text="t",
        workspace=ws(tmp_path),
        gateway=LLMGateway(fake),
        budget=budget(),
        model=MODEL,
        judge_model=MODEL,
        task_id="t",
        limits=DEFAULT_LIMITS,
        system_prompt=custom,
        agent_name="RefactoringAgent.turn",
    )
    agent_systems = [s for s in fake.seen_systems if s not in set(LENS_PROMPTS)]
    assert agent_systems
    assert all(s == custom for s in agent_systems)


# -- the prompt -----------------------------------------------------------------


def _prompt_text() -> str:
    from engine.codeagent.tools.registry import TOOL_REGISTRY

    return build_refactor_prompt(TOOL_REGISTRY)


def flat(text: str) -> str:
    return " ".join(text.split()).lower()


def test_the_prompt_advertises_every_tool_by_name_and_description() -> None:
    from engine.codeagent.tools.registry import TOOL_REGISTRY

    text = _prompt_text()
    for name, tool in TOOL_REGISTRY.items():
        assert f"- {name}: {tool.description}" in text


def test_the_prompt_states_behaviour_preservation_first() -> None:
    lowered = flat(_prompt_text())
    assert "without changing what the program does" in lowered


def test_the_prompt_covers_the_stated_procedure() -> None:
    lowered = flat(_prompt_text())
    assert "repo_graph" in lowered
    assert "analyze_code" in lowered
    assert "testing skill" in lowered
    assert "small, reversible steps" in lowered
    assert "preserve public interfaces" in lowered
    assert "narrowest relevant test" in lowered


def test_the_prompt_never_endorses_weakening_a_test() -> None:
    lowered = flat(_prompt_text())
    assert "never weaken, delete, or skip a test" in lowered


def test_the_prompt_states_ending_the_session_is_not_a_verdict() -> None:
    lowered = flat(_prompt_text())
    assert "ending the session is not a verdict" in lowered


def test_the_prompt_names_no_verdict_or_judge_internals() -> None:
    """This module writes a persona, not a second policy: it must not name the
    internals it has no business steering."""
    lowered = flat(_prompt_text())
    for phrase in ("verdict.gate", "severity threshold", "judge prompt", "benchmark fixture"):
        assert phrase not in lowered


def test_the_skills_catalogue_is_appended_only_when_present() -> None:
    from engine.codeagent.tools.registry import TOOL_REGISTRY

    bare = build_refactor_prompt(TOOL_REGISTRY)
    assert "Available skills" not in bare

    with_skills = build_refactor_prompt(TOOL_REGISTRY, skills_catalogue="- testing: ...")
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
    for path in sorted(Path("src/engine/refactoragent").glob("*.py")):
        offending = {name for name in _imports(path) if name.startswith("engine.orchestrator")}
        assert not offending, f"{path}: imports {sorted(offending)}"


def test_the_legacy_orchestrator_refactoring_agent_is_untouched() -> None:
    """A guard on this phase itself: Agent #3 must not have been folded into
    or replaced the older prompt-file agent of the same name."""
    legacy = Path("src/engine/orchestrator/agents/refactoring.py")
    assert legacy.is_file()
    assert "PromptFileAgent" in legacy.read_text(encoding="utf-8")


def test_the_agent_never_imports_verification_internals_directly() -> None:
    """Every path to a verdict goes through codeagent.verify, unchanged --
    this module must not reach engine.verification.* itself, which would be a
    second, unaccountable route to a PASSED status."""
    for path in sorted(Path("src/engine/refactoragent").glob("*.py")):
        offending = {name for name in _imports(path) if name.startswith("engine.verification")}
        assert not offending, f"{path}: imports {sorted(offending)}"


def test_the_run_result_is_the_coding_agents_own_type_not_a_copy() -> None:
    """No duplicated dataclass: a refactoring run and a coding run report the
    identical shape, so the alias is the type itself."""
    assert RefactorRunResult is CodeRunResult


def test_the_limits_preset_only_overrides_settings_no_new_fields() -> None:
    from dataclasses import fields

    assert {f.name for f in fields(REFACTOR_LIMITS)} == {f.name for f in fields(DEFAULT_LIMITS)}
    assert REFACTOR_LIMITS.max_files_changed < DEFAULT_LIMITS.max_files_changed
    assert REFACTOR_LIMITS.max_repair_rounds == DEFAULT_LIMITS.max_repair_rounds


# -- the whole offline stack ---------------------------------------------------


def test_a_behaviour_preserving_refactor_passes_through_real_agentgate(tmp_path: Path) -> None:
    result, _ = go(tmp_path, REFACTOR_TURNS)

    assert isinstance(result, CodeRunResult)
    assert isinstance(result.report, FinalReport)
    assert result.report.status == SessionStatus.PASSED.value
    assert result.exit_code == exit_code_for(SessionStatus.PASSED)
    assert result.report.files_changed == ["todo.py"]
    # No planning phase for this agent.
    assert result.report.planning_status is None
    assert result.report.plan is None


def test_a_judge_blocked_change_ends_unverified_not_passed(tmp_path: Path) -> None:
    defect = [
        {"id": "C1", "category": "CORRECTNESS", "severity": "HIGH", "location": "todo.py:1", "fix": "f", "grounding_status": "in_contract_reachable", "violated_requirement": "the task requires this behaviour", "code_path": "solution.py:1", "trigger": "the documented input"}
    ]
    result, _ = go(tmp_path, REFACTOR_TURNS, judge_rounds=[critic(defect)])

    assert result.report.status == SessionStatus.UNVERIFIED.value
    assert result.report.status != SessionStatus.PASSED.value
    assert result.report.defects


def test_ending_without_a_change_never_reaches_agentgate(tmp_path: Path) -> None:
    result, _ = go(tmp_path, [final_turn("looked around, nothing to do")])

    assert result.report.status == SessionStatus.UNVERIFIED.value
    assert result.report.verification_ran is False


def test_the_engines_own_source_tree_is_refused(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceRejected):
        run_refactor_task(
            task_text=REFACTOR_TASK,
            workspace_path=Path(__file__).resolve().parent.parent,
            gateway=LLMGateway(provider([final_turn("done")])),
            model=MODEL,
            judge_model=MODEL,
        )


def test_capabilities_default_on_and_are_actually_reachable(tmp_path: Path) -> None:
    """repo_graph, detect_tests and the first-party skills are on by default --
    the scripted run calls two of them, and both must have actually run rather
    than being refused as unknown tools."""
    result, _ = go(tmp_path, REFACTOR_TURNS)

    sources = result.report.context_sources
    assert sources["graph_queries"]
    assert sources["graph_queries"][0]["op"] == "show_module_graph"
    # The fixture's test file sits at its root rather than under tests/, so
    # detection is honestly UNKNOWN here -- the claim under test is that the
    # tool ran and was recorded at all, not what this particular tree implies.
    assert sources["test_detection"] is not None
    assert "refactoring-architecture" in sources["skills"]["advertised"]
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

    go(tmp_path, REFACTOR_TURNS, db_path=db_path)

    from engine.state import db

    with db.connect(db_path) as conn:
        runs = conn.execute("SELECT id, status FROM runs").fetchall()
        metrics = conn.execute(
            "SELECT agent_name FROM agent_execution_metrics WHERE run_id = ?", (runs[0][0],)
        ).fetchall()

    assert runs[0][1] == "passed"
    names = {row[0] for row in metrics}
    assert AGENT_NAME in names
    assert "RefactoringAgent.turn" in names
    # No planning phase, so no plan-metrics row should exist for this run.
    assert "CodingAgent.plan" not in names
    assert any(name.startswith("judge:") for name in names)


def test_a_run_never_widens_the_shared_tool_registry(tmp_path: Path) -> None:
    """The base tool set is TOOL_REGISTRY, imported and merged, never mutated
    -- a run_coding_task call after a refactor run must see the same tools."""
    from engine.codeagent.tools.registry import TOOL_REGISTRY

    before = dict(TOOL_REGISTRY)
    go(tmp_path, REFACTOR_TURNS)
    assert dict(TOOL_REGISTRY) == before

    # And a plain Coding Agent run afterwards behaves exactly as it always did.
    fake = ScenarioProvider(agent_turns=[final_turn("done")], plan_turns=["```plan\n{}\n```"])
    result = run_coding_task(
        task_text="t",
        workspace_path=fixture_copy(tmp_path / "second", "todo_cli"),
        gateway=LLMGateway(fake),
        model=MODEL,
        judge_model=MODEL,
        limits=Limits(max_plan_attempts=1),
    )
    assert fake.seen_systems[-1] is not None
    assert fake.seen_systems[-1].startswith("You are a coding agent")
    assert result.report.agent_status  # the run completed and produced a report
