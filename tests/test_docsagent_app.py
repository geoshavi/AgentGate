"""Agent #7: the Documentation/Handover Agent.

Four groups, each proving something the one below it cannot:

    scope       is_doc_path accepts documentation and config-doc filenames
                and rejects everything else, on the filename alone
    tools       DocWriteFileTool/DocReplaceExactTool refuse an out-of-scope
                path before the real write tool is ever reached, and delegate
                correctly -- content actually lands -- for an in-scope one
    prompt      the docs system prompt covers the stated procedure and never
                encourages inventing a claim or editing production code
    structure   this agent reuses codeagent's session/verify/report machinery
                rather than reimplementing it, and never touches the legacy
                orchestrator or the verdict/judge/benchmark layer directly
    stack       a whole offline run -- real tools, real capabilities, real
                (declined-safe) AgentGate verification -- driven by a
                scripted provider, proving a doc-only change can reach PASSED
                through the same unchanged route every other agent uses, and
                that an attempt to write production code never lands

Every test here is offline: no network, no API key, no real subprocess beyond
what run_tests/git_diff/git_status already spawn against the fixture's own
tree.
"""

import ast
import shutil
from decimal import Decimal
from pathlib import Path

import pytest
from codeagent_harness import CLEAN_CRITIC, MODEL, ScenarioProvider, critic, final_turn, tool_turn

from engine.codeagent.app import CodeRunResult, WorkspaceRejected, exit_code_for
from engine.codeagent.limits import DEFAULT_LIMITS, Limits
from engine.codeagent.policy import DEFAULT_POLICY
from engine.codeagent.report import FinalReport
from engine.codeagent.state import SessionStatus
from engine.codeagent.tools.base import ToolContext
from engine.codeagent.workspace import Workspace
from engine.docsagent.app import _BASE_DOCS_TOOLS, DocsRunResult, run_docs_task
from engine.docsagent.limits import DOCS_LIMITS
from engine.docsagent.prompt import AGENT_NAME, build_docs_prompt
from engine.docsagent.scope import is_doc_path
from engine.docsagent.tools import DocReplaceExactTool, DocWriteFileTool
from engine.runtime.gateway import LLMGateway
from engine.verification.judge import LENSES

FIXTURES = Path(__file__).resolve().parent.parent / "examples"
LENS_PROMPTS = tuple(LENSES.values())

HANDOVER_CONTENT = (
    "# Handover\n\nRun the test suite with:\n\n```\npython -m pytest -q\n```\n"
)

DOCS_TASK = "Add a HANDOVER.md for todo_cli describing how to run its tests."

DOCS_TURNS = [
    tool_turn("list_files"),
    tool_turn("detect_tests"),
    tool_turn("read_file", {"path": "test_todo.py"}),
    tool_turn("write_file", {"path": "HANDOVER.md", "content": HANDOVER_CONTENT}),
    tool_turn("run_tests"),
    final_turn("added HANDOVER.md describing how to run the tests", ["HANDOVER.md"]),
]


def fixture_copy(tmp_path: Path, name: str = "todo_cli") -> Path:
    workspace = tmp_path / "ws"
    shutil.copytree(FIXTURES / name, workspace)
    return workspace


def provider(agent_turns: list[str], judge_rounds: list[str] | None = None) -> ScenarioProvider:
    return ScenarioProvider(
        agent_turns=agent_turns, judge_rounds=judge_rounds or [CLEAN_CRITIC], lens_prompts=LENS_PROMPTS
    )


def go(tmp_path: Path, agent_turns: list[str], *, judge_rounds=None, **kwargs):  # type: ignore[no-untyped-def]
    fake = provider(agent_turns, judge_rounds)
    result = run_docs_task(
        task_text=DOCS_TASK,
        workspace_path=kwargs.pop("workspace", None) or fixture_copy(tmp_path),
        gateway=LLMGateway(fake),
        model=MODEL,
        judge_model=MODEL,
        planned_budget=Decimal("10.00"),
        task_id="docs-app",
        **kwargs,
    )
    return result, fake


def ctx_for(tmp_path: Path) -> ToolContext:
    root = tmp_path / "ws"
    root.mkdir(exist_ok=True)
    return ToolContext(workspace=Workspace(root), policy=DEFAULT_POLICY, limits=Limits())


# -- scope ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "README", "README.md", "readme.MD", "CHANGELOG.rst", "AUTHORS", "LICENSE",
        "NOTICE.txt", "CONTRIBUTING.md", "HANDOVER.md", ".env.example",
        "docs/architecture.md", "src/engine/module/README.md",
    ],
)
def test_documentation_paths_are_accepted(path: str) -> None:
    assert is_doc_path(path)


@pytest.mark.parametrize(
    "path",
    [
        "todo.py", "package.json", "pyproject.toml", "docs/example.py",
        "src/engine/verify.py", ".env", "tox.ini", "setup.cfg", "",
    ],
)
def test_non_documentation_paths_are_rejected(path: str) -> None:
    assert not is_doc_path(path)


def test_windows_separators_are_handled() -> None:
    assert is_doc_path("docs\\HANDOVER.md")
    assert not is_doc_path("src\\engine\\app.py")


# -- the doc-scoped tools ---------------------------------------------------------


def test_writing_a_doc_path_succeeds_and_lands_on_disk(tmp_path: Path) -> None:
    ctx = ctx_for(tmp_path)
    result = DocWriteFileTool().run({"path": "README.md", "content": "hello\n"}, ctx)

    assert result.ok
    assert (ctx.workspace.root / "README.md").read_text(encoding="utf-8") == "hello\n"


def test_writing_a_non_doc_path_is_refused_before_it_reaches_the_real_tool(tmp_path: Path) -> None:
    ctx = ctx_for(tmp_path)
    result = DocWriteFileTool().run({"path": "app.py", "content": "x = 1\n"}, ctx)

    assert result.ok is False
    assert "is not a documentation or config-doc path" in (result.error or "")
    assert not (ctx.workspace.root / "app.py").exists()
    assert ctx.workspace.changed_files == []


def test_replace_exact_on_a_doc_path_delegates_to_the_real_tool(tmp_path: Path) -> None:
    ctx = ctx_for(tmp_path)
    (ctx.workspace.root / "CHANGELOG.md").write_text("## Unreleased\n- nothing yet\n", encoding="utf-8")
    result = DocReplaceExactTool().run(
        {"path": "CHANGELOG.md", "find": "- nothing yet", "replace": "- added handover docs"}, ctx
    )

    assert result.ok
    assert "added handover docs" in (ctx.workspace.root / "CHANGELOG.md").read_text(encoding="utf-8")


def test_replace_exact_on_a_non_doc_path_is_refused(tmp_path: Path) -> None:
    ctx = ctx_for(tmp_path)
    (ctx.workspace.root / "app.py").write_text("x = 1\n", encoding="utf-8")
    result = DocReplaceExactTool().run({"path": "app.py", "find": "x = 1", "replace": "x = 2"}, ctx)

    assert result.ok is False
    assert (ctx.workspace.root / "app.py").read_text(encoding="utf-8") == "x = 1\n"


def test_the_mass_deletion_guard_still_applies_through_delegation(tmp_path: Path) -> None:
    """The wrapper adds one refusal; it does not remove any of the real
    tool's own guarantees."""
    ctx = ctx_for(tmp_path)
    (ctx.workspace.root / "README.md").write_text("a" * 3000, encoding="utf-8")
    result = DocWriteFileTool().run({"path": "README.md", "content": "", "overwrite": True}, ctx)

    assert result.ok is False
    assert (ctx.workspace.root / "README.md").stat().st_size > 0


# -- the prompt -----------------------------------------------------------------


def _prompt_text() -> str:
    return build_docs_prompt(dict(_BASE_DOCS_TOOLS))


def flat(text: str) -> str:
    return " ".join(text.split()).lower()


def test_the_prompt_advertises_every_tool_by_name_and_description() -> None:
    text = _prompt_text()
    for name, tool in _BASE_DOCS_TOOLS.items():
        assert f"- {name}: {tool.description}" in text


def test_the_prompt_states_the_write_scope() -> None:
    lowered = flat(_prompt_text())
    assert "scoped to documentation and config-doc files only" in lowered


def test_the_prompt_forbids_inventing_claims() -> None:
    lowered = flat(_prompt_text())
    assert "never invent a command, a feature, an api, an environment variable" in lowered


def test_the_prompt_requires_separating_current_from_planned_work() -> None:
    lowered = flat(_prompt_text())
    assert "separate current behaviour from planned or future work" in lowered


def test_the_prompt_prefers_concise_docs_over_large_dumps() -> None:
    lowered = flat(_prompt_text())
    assert "prefer a short, accurate paragraph over a large autogenerated dump" in lowered


def test_the_prompt_asks_to_preserve_existing_style() -> None:
    lowered = flat(_prompt_text())
    assert "preserve the existing documentation" in lowered


def test_the_prompt_forbids_editing_code_to_match_docs() -> None:
    lowered = flat(_prompt_text())
    assert "never change production code just to make a doc" in lowered


def test_the_prompt_asks_for_validation_where_practical() -> None:
    lowered = flat(_prompt_text())
    assert "a command you did not check is a claim, not a fact" in lowered


def test_the_prompt_never_endorses_weakening_a_test() -> None:
    lowered = flat(_prompt_text())
    assert "never weaken or remove an existing test" in lowered


def test_the_prompt_names_no_verdict_or_judge_internals() -> None:
    lowered = flat(_prompt_text())
    for phrase in ("verdict.gate", "severity threshold", "judge prompt", "benchmark fixture"):
        assert phrase not in lowered


def test_the_skills_catalogue_is_appended_only_when_present() -> None:
    bare = build_docs_prompt(dict(_BASE_DOCS_TOOLS))
    assert "Available skills" not in bare

    with_skills = build_docs_prompt(dict(_BASE_DOCS_TOOLS), skills_catalogue="- testing: ...")
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
    for path in sorted(Path("src/engine/docsagent").rglob("*.py")):
        offending = {name for name in _imports(path) if name.startswith("engine.orchestrator")}
        assert not offending, f"{path}: imports {sorted(offending)}"


def test_the_agent_never_imports_verification_internals_directly() -> None:
    for path in sorted(Path("src/engine/docsagent").rglob("*.py")):
        offending = {name for name in _imports(path) if name.startswith("engine.verification")}
        assert not offending, f"{path}: imports {sorted(offending)}"


def test_the_agent_never_imports_debug_repro_suite_proof_machinery() -> None:
    for path in sorted(Path("src/engine/docsagent").rglob("*.py")):
        offending = {name for name in _imports(path) if name.startswith("engine.debugagent")}
        assert not offending, f"{path}: imports {sorted(offending)}"


def test_the_tool_wrappers_never_reimplement_write_mechanics() -> None:
    """No second write path -- both wrappers delegate to the real tool."""
    import inspect

    from engine.docsagent import tools as docs_tools

    source = inspect.getsource(docs_tools)
    assert "open(" not in source
    assert "write_text" not in source
    assert source.count("self._inner.run(args, ctx)") == 2


def test_the_run_result_is_the_coding_agents_own_type_not_a_copy() -> None:
    from engine.architectureagent.app import ArchitectureRunResult
    from engine.refactoragent.app import RefactorRunResult
    from engine.securityagent.app import SecurityRunResult
    from engine.testqaagent.app import QARunResult

    assert DocsRunResult is CodeRunResult
    assert DocsRunResult is RefactorRunResult
    assert DocsRunResult is QARunResult
    assert DocsRunResult is SecurityRunResult
    assert DocsRunResult is ArchitectureRunResult


def test_the_limits_preset_only_overrides_settings_no_new_fields() -> None:
    from dataclasses import fields

    assert {f.name for f in fields(DOCS_LIMITS)} == {f.name for f in fields(DEFAULT_LIMITS)}
    assert DOCS_LIMITS.max_files_changed < DEFAULT_LIMITS.max_files_changed
    assert DOCS_LIMITS.max_repair_rounds == DEFAULT_LIMITS.max_repair_rounds


def test_the_base_tool_set_has_no_arbitrary_command_tool() -> None:
    assert "run_command" not in _BASE_DOCS_TOOLS
    assert "write_file" in _BASE_DOCS_TOOLS
    assert isinstance(_BASE_DOCS_TOOLS["write_file"], DocWriteFileTool)
    assert isinstance(_BASE_DOCS_TOOLS["replace_exact"], DocReplaceExactTool)


# -- the whole offline stack ---------------------------------------------------


def test_a_doc_only_change_reaches_passed_through_real_agentgate(tmp_path: Path) -> None:
    result, fake = go(tmp_path, DOCS_TURNS)

    assert isinstance(result, CodeRunResult)
    assert isinstance(result.report, FinalReport)
    assert result.report.status == SessionStatus.PASSED.value
    assert result.exit_code == exit_code_for(SessionStatus.PASSED)
    assert result.report.files_changed == ["HANDOVER.md"]
    assert result.report.planning_status is None

    assert fake.seen_systems[0] is not None
    assert fake.seen_systems[0].startswith("You are a documentation and handover agent")


def test_a_judge_blocked_change_ends_unverified_not_passed(tmp_path: Path) -> None:
    defect = [
        {"id": "C1", "category": "CORRECTNESS", "severity": "HIGH", "location": "HANDOVER.md:1", "fix": "f", "grounding_status": "in_contract_reachable", "violated_requirement": "the task requires this behaviour", "code_path": "solution.py:1", "trigger": "the documented input"}
    ]
    result, _ = go(tmp_path, DOCS_TURNS, judge_rounds=[critic(defect)])

    assert result.report.status == SessionStatus.UNVERIFIED.value
    assert result.report.defects


def test_an_attempt_to_write_production_code_never_lands(tmp_path: Path) -> None:
    result, fake = go(
        tmp_path,
        [
            tool_turn("write_file", {"path": "todo.py", "content": "x = 1\n"}),
            final_turn("could not edit source code; nothing changed", []),
        ],
    )

    assert result.report.files_changed == []
    assert result.report.status == SessionStatus.UNVERIFIED.value
    assert fake.agent_calls == 2


def test_an_attempt_to_run_a_command_fails_as_an_unknown_tool(tmp_path: Path) -> None:
    result, _ = go(
        tmp_path,
        [
            tool_turn("run_command", {"argv": ["rm", "-rf", "."]}),
            final_turn("could not run commands; nothing changed", []),
        ],
    )
    assert result.report.files_changed == []


def test_the_engines_own_source_tree_is_refused(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceRejected):
        run_docs_task(
            task_text=DOCS_TASK,
            workspace_path=Path(__file__).resolve().parent.parent,
            gateway=LLMGateway(provider([final_turn("done")])),
            model=MODEL,
            judge_model=MODEL,
        )


def test_capabilities_default_on_and_are_actually_reachable(tmp_path: Path) -> None:
    result, _ = go(tmp_path, DOCS_TURNS)

    sources = result.report.context_sources
    assert sources["test_detection"] is not None
    assert "testing" in sources["skills"]["advertised"]
    assert "refactoring-architecture" in sources["skills"]["advertised"]


def test_analyze_defaults_off_unlike_review_agents(tmp_path: Path) -> None:
    """Semgrep is not among this task's named evidence; graph and
    detect_tests are on by default, analyze is not."""
    result, _ = go(tmp_path, [tool_turn("list_files"), final_turn("looked, no changes needed")])
    assert "analyze_code" not in _BASE_DOCS_TOOLS
    assert result.report.context_sources["analysis"] is None


def test_capabilities_can_be_turned_off(tmp_path: Path) -> None:
    result, _ = go(
        tmp_path,
        [tool_turn("list_files"), final_turn("looked, no changes needed")],
        detect_tests=False,
        graph=False,
        include_builtin_skills=False,
    )
    sources = result.report.context_sources
    assert sources["graph_queries"] is None
    assert sources["test_detection"] is None
    assert sources["skills"]["advertised"] == []


def test_the_run_is_recorded_in_the_database_under_its_own_metrics_label(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"

    go(tmp_path, DOCS_TURNS, db_path=db_path)

    from engine.state import db

    with db.connect(db_path) as conn:
        runs = conn.execute("SELECT id, status FROM runs").fetchall()
        metrics = conn.execute(
            "SELECT agent_name FROM agent_execution_metrics WHERE run_id = ?", (runs[0][0],)
        ).fetchall()

    assert runs[0][1] == "passed"
    names = {row[0] for row in metrics}
    assert AGENT_NAME in names
    assert "DocsHandoverAgent.turn" in names
    assert "CodingAgent.plan" not in names
    assert any(name.startswith("judge:") for name in names)


def test_a_run_never_widens_the_shared_tool_registry(tmp_path: Path) -> None:
    from engine.codeagent.tools.registry import TOOL_REGISTRY

    before = dict(TOOL_REGISTRY)
    go(tmp_path, DOCS_TURNS)
    assert dict(TOOL_REGISTRY) == before
