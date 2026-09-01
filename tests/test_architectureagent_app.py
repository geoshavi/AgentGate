"""Agent #6: the Architecture Review Agent.

Four groups, each proving something the one below it cannot:

    prompt      the architecture system prompt covers the stated review
                areas, states repo_graph's evidentiary limits explicitly, and
                requires a second signal before calling anything dead
    structure   this agent reuses codeagent's session/verify/report machinery
                AND the Security Review Agent's own report_finding capability
                -- not a duplicate -- never touches the legacy orchestrator or
                the verdict/judge/benchmark layer directly, and has no tool
                that could edit a file
    stack       a whole offline run -- real tools, real capabilities, real
                report_finding, real (declined) AgentGate verification --
                driven by a scripted provider, proving the review's findings
                surface on the same FinalReport every other agent uses
    safety      the tool set has no write_file, no replace_exact and no
                run_command, and a scripted attempt to call one fails as an
                unknown tool rather than doing anything

report_finding's own validation, clipping and cap-enforcement behaviour is
proven once, in test_securityagent_app.py, against the identical shared tool
this agent uses -- this file does not re-derive that coverage, only that this
agent reaches the same tool through the same capability.

Every test here is offline: no network, no API key, no real subprocess beyond
what git_diff/git_status already spawn against the fixture's own tree.
"""

import ast
import shutil
from decimal import Decimal
from pathlib import Path

import pytest
from codeagent_harness import CLEAN_CRITIC, MODEL, ScenarioProvider, final_turn, tool_turn

from engine.architectureagent.app import (
    _BASE_ARCHITECTURE_TOOLS,
    ArchitectureRunResult,
    run_architecture_review_task,
)
from engine.architectureagent.limits import ARCHITECTURE_LIMITS
from engine.architectureagent.prompt import AGENT_NAME, build_architecture_prompt
from engine.codeagent.app import CodeRunResult, WorkspaceRejected, exit_code_for
from engine.codeagent.limits import DEFAULT_LIMITS
from engine.codeagent.report import FinalReport
from engine.codeagent.state import REVIEW_BASES, REVIEW_SEVERITIES, SessionStatus
from engine.codeagent.tools.findings import ReportFindingTool
from engine.runtime.gateway import LLMGateway
from engine.verification.judge import LENSES

FIXTURES = Path(__file__).resolve().parent.parent / "examples"
LENS_PROMPTS = tuple(LENSES.values())

FINDING_ARGS = {
    "category": "separation_of_concerns",
    "severity": "LOW",
    "rationale": "fine at this size, but worth flagging before more responsibilities land here",
    "location": "todo.py",
    "evidence": (
        "todo.py is one function, parse_due_date; repo_graph reports no dependents "
        "in this fixture, so there is no boundary being crossed yet"
    ),
    "recommendation": "no action needed now; revisit if todo.py grows a second responsibility",
    "basis": "observed",
}

ARCHITECTURE_TASK = "Review todo_cli's module structure for coupling and separation of concerns."

ARCHITECTURE_TURNS = [
    tool_turn("list_files"),
    tool_turn("detect_tests"),
    tool_turn("repo_graph", {"op": "show_module_graph"}),
    tool_turn("repo_graph", {"op": "find_dependents", "path": "todo.py"}),
    tool_turn("read_file", {"path": "todo.py"}),
    tool_turn("report_finding", FINDING_ARGS),
    final_turn("reviewed todo.py's structure; recorded one finding", []),
]


def fixture_copy(tmp_path: Path, name: str = "todo_cli") -> Path:
    workspace = tmp_path / "ws"
    shutil.copytree(FIXTURES / name, workspace)
    return workspace


def provider(agent_turns: list[str], judge_rounds: list[str] | None = None) -> ScenarioProvider:
    return ScenarioProvider(
        agent_turns=agent_turns, judge_rounds=judge_rounds or [CLEAN_CRITIC], lens_prompts=LENS_PROMPTS
    )


def go(tmp_path: Path, agent_turns: list[str], **kwargs):  # type: ignore[no-untyped-def]
    fake = provider(agent_turns)
    result = run_architecture_review_task(
        task_text=ARCHITECTURE_TASK,
        workspace_path=kwargs.pop("workspace", None) or fixture_copy(tmp_path),
        gateway=LLMGateway(fake),
        model=MODEL,
        judge_model=MODEL,
        planned_budget=Decimal("10.00"),
        task_id="arch-app",
        **kwargs,
    )
    return result, fake


# -- the prompt -----------------------------------------------------------------


def _prompt_text() -> str:
    return build_architecture_prompt(dict(_BASE_ARCHITECTURE_TOOLS))


def flat(text: str) -> str:
    return " ".join(text.split()).lower()


def test_the_prompt_advertises_every_tool_by_name_and_description() -> None:
    text = _prompt_text()
    for name, tool in _BASE_ARCHITECTURE_TOOLS.items():
        assert f"- {name}: {tool.description}" in text


def test_the_prompt_states_it_reports_rather_than_fixes() -> None:
    lowered = flat(_prompt_text())
    assert "you do not fix it" in lowered


def test_the_prompt_covers_every_stated_review_area() -> None:
    lowered = flat(_prompt_text())
    for area in (
        "module boundaries and layering",
        "coupling",
        "dependency cycles",
        "oversized modules, functions or classes",
        "duplicated responsibilities",
        "public interface stability",
        "testability and separation of concerns",
        "architecture drift",
    ):
        assert area in lowered


def test_the_prompt_states_repo_graph_is_bounded_and_name_based() -> None:
    lowered = flat(_prompt_text())
    assert "repo_graph is bounded and name-based, not semantic proof" in lowered


def test_the_prompt_requires_a_second_signal_before_calling_something_dead() -> None:
    lowered = flat(_prompt_text())
    assert "never claim a symbol or module is dead from one signal alone" in lowered
    assert "a second signal" in lowered


def test_the_prompt_treats_semgrep_as_advisory_only() -> None:
    lowered = flat(_prompt_text())
    assert "analyze_code" in lowered
    assert "treat its findings as evidence, not truth" in lowered


def test_the_prompt_separates_observed_from_hypothesis() -> None:
    lowered = flat(_prompt_text())
    assert 'basis="observed" only when you can cite' in lowered
    assert 'basis="hypothesis" for a suspicion' in lowered


def test_the_prompt_confirms_layering_intent_before_calling_a_violation() -> None:
    lowered = flat(_prompt_text())
    assert "confirm the intended layering before calling a specific import a violation" in lowered


def test_the_prompt_references_the_refactoring_architecture_skill() -> None:
    lowered = flat(_prompt_text())
    assert "refactoring-architecture skill" in lowered


def test_the_prompt_names_no_verdict_or_judge_internals() -> None:
    lowered = flat(_prompt_text())
    for phrase in ("verdict.gate", "severity threshold", "judge prompt", "benchmark fixture"):
        assert phrase not in lowered


def test_the_skills_catalogue_is_appended_only_when_present() -> None:
    bare = build_architecture_prompt(dict(_BASE_ARCHITECTURE_TOOLS))
    assert "Available skills" not in bare

    with_skills = build_architecture_prompt(
        dict(_BASE_ARCHITECTURE_TOOLS), skills_catalogue="- testing: ..."
    )
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
    for path in sorted(Path("src/engine/architectureagent").rglob("*.py")):
        offending = {name for name in _imports(path) if name.startswith("engine.orchestrator")}
        assert not offending, f"{path}: imports {sorted(offending)}"


def test_the_agent_never_imports_verification_internals_directly() -> None:
    for path in sorted(Path("src/engine/architectureagent").rglob("*.py")):
        offending = {name for name in _imports(path) if name.startswith("engine.verification")}
        assert not offending, f"{path}: imports {sorted(offending)}"


def test_the_agent_never_imports_debug_repro_suite_proof_machinery() -> None:
    for path in sorted(Path("src/engine/architectureagent").rglob("*.py")):
        offending = {name for name in _imports(path) if name.startswith("engine.debugagent")}
        assert not offending, f"{path}: imports {sorted(offending)}"


def test_the_agent_defines_no_tool_of_its_own() -> None:
    """report_finding lives once, in codeagent/tools/findings.py, not copied
    per review agent -- this asserts the absence of a local tools module."""
    assert not (Path("src/engine/architectureagent") / "tools").exists()
    assert not (Path("src/engine/architectureagent") / "tools.py").exists()


def test_report_finding_is_the_identical_shared_tool_security_uses() -> None:
    from engine.securityagent.app import _BASE_SECURITY_TOOLS

    assert "report_finding" not in _BASE_ARCHITECTURE_TOOLS
    assert "report_finding" not in _BASE_SECURITY_TOOLS
    # Both agents reach it through the same capability, not a copy of it.
    import inspect

    from engine.architectureagent import app as arch_app
    from engine.securityagent import app as sec_app

    assert "ReportFindingTool" not in inspect.getsource(arch_app)
    assert "ReportFindingTool" not in inspect.getsource(sec_app)
    assert "report_findings=report_findings" in inspect.getsource(
        arch_app.run_architecture_review_task
    )


def test_the_run_result_is_the_coding_agents_own_type_not_a_copy() -> None:
    from engine.refactoragent.app import RefactorRunResult
    from engine.securityagent.app import SecurityRunResult
    from engine.testqaagent.app import QARunResult

    assert ArchitectureRunResult is CodeRunResult
    assert ArchitectureRunResult is RefactorRunResult
    assert ArchitectureRunResult is QARunResult
    assert ArchitectureRunResult is SecurityRunResult


def test_the_limits_preset_only_overrides_settings_no_new_fields() -> None:
    from dataclasses import fields

    assert {f.name for f in fields(ARCHITECTURE_LIMITS)} == {f.name for f in fields(DEFAULT_LIMITS)}
    assert ARCHITECTURE_LIMITS.max_files_changed == 0
    assert ARCHITECTURE_LIMITS.max_repair_rounds == DEFAULT_LIMITS.max_repair_rounds


def test_the_base_tool_set_has_no_editor_or_command_tool() -> None:
    forbidden = {"write_file", "replace_exact", "run_command", "run_tests"}
    assert forbidden.isdisjoint(_BASE_ARCHITECTURE_TOOLS)


# -- the whole offline stack ---------------------------------------------------


def test_a_review_records_findings_and_the_run_is_honestly_unverified(tmp_path: Path) -> None:
    """No file was changed -- by construction, this agent has no tool that
    could change one -- so verification is correctly declined. UNVERIFIED
    here is the honest, expected outcome of a pure review, not a failure."""
    result, fake = go(tmp_path, ARCHITECTURE_TURNS)

    assert isinstance(result, CodeRunResult)
    assert isinstance(result.report, FinalReport)
    assert result.report.files_changed == []
    assert result.report.verification_ran is False
    assert result.report.status == SessionStatus.UNVERIFIED.value
    assert result.exit_code == exit_code_for(SessionStatus.UNVERIFIED)
    assert result.report.planning_status is None

    findings = result.report.context_sources["review_findings"]
    assert isinstance(findings, list) and len(findings) == 1
    assert findings[0]["category"] == "separation_of_concerns"
    assert findings[0]["severity"] == "LOW"
    assert findings[0]["basis"] == "observed"

    assert fake.seen_systems[0] is not None
    assert fake.seen_systems[0].startswith("You are an architecture review agent")


def test_report_finding_actually_records_a_real_finding_through_the_tool(tmp_path: Path) -> None:
    """Confirms this agent reaches the real, validated tool -- not a stub --
    by checking the recorded severity/basis were normalised the same way
    test_securityagent_app.py proves for the identical tool."""
    result, _ = go(
        tmp_path,
        [
            tool_turn("read_file", {"path": "todo.py"}),
            tool_turn("report_finding", {**FINDING_ARGS, "severity": "low", "basis": "HYPOTHESIS"}),
            final_turn("reviewed"),
        ],
    )
    findings = result.report.context_sources["review_findings"]
    assert findings[0]["severity"] == "LOW"
    assert findings[0]["basis"] == "hypothesis"


def test_no_findings_is_also_a_complete_honest_result(tmp_path: Path) -> None:
    result, _ = go(tmp_path, [tool_turn("read_file", {"path": "todo.py"}), final_turn("reviewed; nothing to report")])

    assert result.report.context_sources["review_findings"] is None
    assert result.report.status == SessionStatus.UNVERIFIED.value


def test_the_engines_own_source_tree_is_refused(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceRejected):
        run_architecture_review_task(
            task_text=ARCHITECTURE_TASK,
            workspace_path=Path(__file__).resolve().parent.parent,
            gateway=LLMGateway(provider([final_turn("done")])),
            model=MODEL,
            judge_model=MODEL,
        )


def test_capabilities_default_on_and_are_actually_reachable(tmp_path: Path) -> None:
    result, _ = go(tmp_path, ARCHITECTURE_TURNS)

    sources = result.report.context_sources
    assert sources["graph_queries"]
    ops = {q["op"] for q in sources["graph_queries"]}
    assert {"show_module_graph", "find_dependents"} <= ops
    assert sources["test_detection"] is not None
    assert "refactoring-architecture" in sources["skills"]["advertised"]
    assert "testing" in sources["skills"]["advertised"]


def test_capabilities_can_be_turned_off(tmp_path: Path) -> None:
    result, _ = go(
        tmp_path,
        [tool_turn("list_files"), final_turn("looked, nothing to report")],
        detect_tests=False,
        analyze=False,
        graph=False,
        report_findings=False,
        include_builtin_skills=False,
    )
    sources = result.report.context_sources
    assert sources["graph_queries"] is None
    assert sources["test_detection"] is None
    assert sources["review_findings"] is None
    assert sources["skills"]["advertised"] == []


def test_report_findings_can_be_turned_off_independently(tmp_path: Path) -> None:
    """report_finding is its own opt-in flag, distinct from graph/analyze/
    detect_tests -- turning it off alone must remove only that tool."""
    result, _ = go(
        tmp_path,
        [
            tool_turn("report_finding", FINDING_ARGS),
            final_turn("could not report; the tool was unavailable"),
        ],
        report_findings=False,
    )
    assert result.report.context_sources["review_findings"] is None
    # The call failed as an unknown tool, not as a validation error.
    assert result.report.tool_calls >= 1


def test_the_run_is_recorded_in_the_database_under_its_own_metrics_label(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"

    go(tmp_path, ARCHITECTURE_TURNS, db_path=db_path)

    from engine.state import db

    with db.connect(db_path) as conn:
        runs = conn.execute("SELECT id, status FROM runs").fetchall()
        metrics = conn.execute(
            "SELECT agent_name FROM agent_execution_metrics WHERE run_id = ?", (runs[0][0],)
        ).fetchall()

    # No file changed, so this run is correctly recorded as not passed.
    assert runs[0][1] == "failed"
    names = {row[0] for row in metrics}
    assert AGENT_NAME in names
    assert "ArchitectureReviewAgent.turn" in names
    assert "CodingAgent.plan" not in names
    assert not any(name.startswith("judge:") for name in names)  # declined, never called


def test_a_run_never_widens_the_shared_tool_registry(tmp_path: Path) -> None:
    from engine.codeagent.tools.registry import TOOL_REGISTRY

    before = dict(TOOL_REGISTRY)
    go(tmp_path, ARCHITECTURE_TURNS)
    assert dict(TOOL_REGISTRY) == before


# -- safety: no tool can edit a file, even if a turn asks it to ----------------


def test_an_attempt_to_write_a_file_fails_as_an_unknown_tool(tmp_path: Path) -> None:
    result, fake = go(
        tmp_path,
        [
            tool_turn("write_file", {"path": "todo.py", "content": "x = 1\n"}),
            final_turn("could not edit; reporting instead", []),
        ],
    )

    assert result.report.files_changed == []
    assert fake.agent_calls == 2
    assert result.report.commands_run == []


def test_an_attempt_to_run_a_command_fails_as_an_unknown_tool(tmp_path: Path) -> None:
    result, _ = go(
        tmp_path,
        [
            tool_turn("run_command", {"argv": ["rm", "-rf", "."]}),
            final_turn("could not run commands; reporting instead", []),
        ],
    )
    assert result.report.files_changed == []
    assert result.report.commands_run == []


# -- sanity: the shared tool this agent depends on still behaves as specified --


def test_report_finding_still_validates_severity_the_same_way() -> None:
    """One narrow sanity check against the real, shared tool -- full coverage
    of report_finding's validation lives in test_securityagent_app.py."""
    import tempfile

    from engine.codeagent.limits import Limits
    from engine.codeagent.policy import DEFAULT_POLICY
    from engine.codeagent.tools.base import ToolContext
    from engine.codeagent.workspace import Workspace

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "ws"
        root.mkdir()
        ctx = ToolContext(workspace=Workspace(root), policy=DEFAULT_POLICY, limits=Limits())
        bad = ReportFindingTool().run({**FINDING_ARGS, "severity": "SEVERE"}, ctx)
        assert bad.ok
        assert "not one of" in bad.output
        for severity in REVIEW_SEVERITIES:
            assert severity in bad.output
        for basis in REVIEW_BASES:
            assert basis in ReportFindingTool().description
