"""Agent #5: the Security Review Agent.

Five groups, each proving something the one below it cannot:

    finding     report_finding validates, bounds and records a claim -- and
                only a claim: it changes nothing, and a malformed call is
                refused rather than silently recorded
    prompt      the security system prompt covers the stated procedure and
                never encourages weakening a test or a policy
    structure   this agent reuses codeagent's session/verify/report machinery
                rather than reimplementing it, never touches the legacy
                orchestrator or the verdict/judge/benchmark layer directly,
                and has no tool that could edit a file
    stack       a whole offline run -- real tools, real capabilities, real
                report_finding, real (declined) AgentGate verification --
                driven by a scripted provider, proving the review's findings
                surface on the same FinalReport every other agent uses
    safety      the tool set has no write_file, no replace_exact and no
                run_command, and a scripted attempt to call one fails as an
                unknown tool rather than doing anything

Every test here is offline: no network, no API key, no real subprocess beyond
what git_diff/git_status already spawn against the fixture's own tree.
"""

import ast
import shutil
from decimal import Decimal
from pathlib import Path

import pytest
from codeagent_harness import CLEAN_CRITIC, MODEL, ScenarioProvider, final_turn, tool_turn

from engine.codeagent.app import CodeRunResult, WorkspaceRejected, exit_code_for
from engine.codeagent.limits import DEFAULT_LIMITS, Limits
from engine.codeagent.report import FinalReport
from engine.codeagent.state import REVIEW_BASES, REVIEW_SEVERITIES, SessionStatus
from engine.codeagent.tools.base import ToolContext
from engine.codeagent.tools.findings import ReportFindingTool
from engine.codeagent.workspace import Workspace
from engine.runtime.gateway import LLMGateway
from engine.securityagent.app import (
    _BASE_SECURITY_TOOLS,
    SecurityRunResult,
    run_security_review_task,
)
from engine.securityagent.limits import SECURITY_LIMITS
from engine.securityagent.prompt import AGENT_NAME, build_security_prompt
from engine.verification.judge import LENSES

FIXTURES = Path(__file__).resolve().parent.parent / "examples"
LENS_PROMPTS = tuple(LENSES.values())

FINDING_ARGS = {
    "category": "unsafe_deserialization",
    "severity": "LOW",
    "rationale": "malformed input crashes the process rather than being rejected cleanly",
    "location": "todo.py:9",
    "evidence": (
        "parts = raw.split('-'); int(parts[0]) indexes into parts without checking "
        "len(parts) == 3 first, so a malformed date raises an unhandled IndexError"
    ),
    "recommendation": "validate len(parts) == 3 and that each part is numeric before indexing",
    "basis": "observed",
}

SECURITY_TASK = "Review todo.py's date parser for how it handles untrusted input."

SECURITY_TURNS = [
    tool_turn("list_files"),
    tool_turn("detect_tests"),
    tool_turn("repo_graph", {"op": "show_module_graph"}),
    tool_turn("read_file", {"path": "todo.py"}),
    tool_turn("report_finding", FINDING_ARGS),
    final_turn("reviewed todo.py's date parser; recorded one input-validation finding", []),
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
    result = run_security_review_task(
        task_text=SECURITY_TASK,
        workspace_path=kwargs.pop("workspace", None) or fixture_copy(tmp_path),
        gateway=LLMGateway(fake),
        model=MODEL,
        judge_model=MODEL,
        planned_budget=Decimal("10.00"),
        task_id="sec-app",
        **kwargs,
    )
    return result, fake


def ws(tmp_path: Path) -> Workspace:
    root = tmp_path / "ws"
    root.mkdir(exist_ok=True)
    return Workspace(root)


def ctx_for(tmp_path: Path, *, limits: Limits | None = None) -> ToolContext:
    from engine.codeagent.policy import DEFAULT_POLICY

    return ToolContext(workspace=ws(tmp_path), policy=DEFAULT_POLICY, limits=limits or Limits())


# -- report_finding ---------------------------------------------------------


def test_a_complete_finding_is_recorded_and_acknowledged(tmp_path: Path) -> None:
    ctx = ctx_for(tmp_path)
    result = ReportFindingTool().run(FINDING_ARGS, ctx)

    assert result.ok
    assert "recorded finding #1" in result.output
    assert "[LOW/observed]" in result.output
    assert len(ctx.review_findings_log) == 1
    finding = ctx.review_findings_log[0]
    assert finding.category == "unsafe_deserialization"
    assert finding.severity == "LOW"
    assert finding.basis == "observed"
    assert finding.ok


def test_severity_is_normalised_and_validated(tmp_path: Path) -> None:
    ctx = ctx_for(tmp_path)
    args = {**FINDING_ARGS, "severity": "low"}
    result = ReportFindingTool().run(args, ctx)
    assert result.ok
    assert ctx.review_findings_log[0].severity == "LOW"

    ctx2 = ctx_for(tmp_path)
    bad = ReportFindingTool().run({**FINDING_ARGS, "severity": "SEVERE"}, ctx2)
    assert bad.ok  # refused as an ordinary observation, not a session failure
    assert "not one of" in bad.output
    assert ctx2.review_findings_log == []


def test_basis_must_be_observed_or_hypothesis(tmp_path: Path) -> None:
    ctx = ctx_for(tmp_path)
    result = ReportFindingTool().run({**FINDING_ARGS, "basis": "guess"}, ctx)
    assert result.ok
    assert "not one of" in result.output
    assert ctx.review_findings_log == []

    ctx2 = ctx_for(tmp_path)
    ReportFindingTool().run({**FINDING_ARGS, "basis": "HYPOTHESIS"}, ctx2)
    assert ctx2.review_findings_log[0].basis == "hypothesis"


def test_a_missing_required_argument_fails(tmp_path: Path) -> None:
    ctx = ctx_for(tmp_path)
    args = dict(FINDING_ARGS)
    del args["evidence"]
    result = ReportFindingTool().run(args, ctx)
    assert result.ok is False
    assert ctx.review_findings_log == []


def test_an_unexpected_argument_is_refused_rather_than_ignored(tmp_path: Path) -> None:
    ctx = ctx_for(tmp_path)
    result = ReportFindingTool().run({**FINDING_ARGS, "cvss": 9.8}, ctx)
    assert result.ok
    assert "cvss" in result.output
    assert ctx.review_findings_log == []


def test_optional_fields_default_to_empty_when_omitted(tmp_path: Path) -> None:
    ctx = ctx_for(tmp_path)
    args = dict(FINDING_ARGS)
    del args["rationale"]
    del args["recommendation"]
    result = ReportFindingTool().run(args, ctx)
    assert result.ok
    assert ctx.review_findings_log[0].rationale == ""
    assert ctx.review_findings_log[0].recommendation == ""


def test_free_text_fields_are_clipped_not_rejected(tmp_path: Path) -> None:
    ctx = ctx_for(tmp_path, limits=Limits(max_review_finding_field_chars=10))
    result = ReportFindingTool().run(FINDING_ARGS, ctx)
    assert result.ok
    finding = ctx.review_findings_log[0]
    assert len(finding.category) <= 10
    assert len(finding.evidence) <= 10


def test_recording_is_capped_and_refuses_once_reached(tmp_path: Path) -> None:
    ctx = ctx_for(tmp_path, limits=Limits(max_review_findings=2))
    tool = ReportFindingTool()
    assert tool.run(FINDING_ARGS, ctx).ok
    assert tool.run(FINDING_ARGS, ctx).ok
    third = tool.run(FINDING_ARGS, ctx)

    assert third.ok
    assert "max_review_findings" in third.output
    assert len(ctx.review_findings_log) == 2  # the refusal was not logged


def test_report_finding_changes_nothing_it_only_records() -> None:
    """No workspace mutation path exists on this tool at all."""
    import inspect

    from engine.codeagent.tools import findings as finding_module

    source = inspect.getsource(finding_module)
    assert "workspace.resolve" not in source
    assert "write_text" not in source
    assert "run_argv" not in source


# -- the prompt -----------------------------------------------------------------


def _prompt_text() -> str:
    return build_security_prompt(dict(_BASE_SECURITY_TOOLS))


def flat(text: str) -> str:
    return " ".join(text.split()).lower()


def test_the_prompt_advertises_every_tool_by_name_and_description() -> None:
    text = _prompt_text()
    for name, tool in _BASE_SECURITY_TOOLS.items():
        assert f"- {name}: {tool.description}" in text


def test_the_prompt_states_it_does_not_fix_findings() -> None:
    lowered = flat(_prompt_text())
    assert "you do not fix them" in lowered


def test_the_prompt_covers_the_stated_procedure() -> None:
    lowered = flat(_prompt_text())
    assert "repo_graph" in lowered
    assert "analyze_code" in lowered
    for risk in (
        "injection", "path traversal", "command execution", "secret exposure",
        "unsafe deserialization", "ssrf", "unsafe file handling", "dependency or configuration",
    ):
        assert risk in lowered
    assert "report_finding" in lowered
    for severity in REVIEW_SEVERITIES:
        assert severity.lower() in lowered
    for basis in REVIEW_BASES:
        assert basis in lowered


def test_the_prompt_separates_observed_from_hypothesis() -> None:
    lowered = flat(_prompt_text())
    assert 'basis="observed" only when you can cite' in lowered
    assert 'basis="hypothesis" for a suspicion' in lowered


def test_the_prompt_states_ending_the_session_is_not_a_verdict() -> None:
    lowered = flat(_prompt_text())
    assert "ending the session is not a verdict" in lowered


def test_the_prompt_names_no_verdict_or_judge_internals() -> None:
    lowered = flat(_prompt_text())
    for phrase in ("verdict.gate", "severity threshold", "judge prompt", "benchmark fixture"):
        assert phrase not in lowered


def test_the_skills_catalogue_is_appended_only_when_present() -> None:
    bare = build_security_prompt(dict(_BASE_SECURITY_TOOLS))
    assert "Available skills" not in bare

    with_skills = build_security_prompt(dict(_BASE_SECURITY_TOOLS), skills_catalogue="- testing: ...")
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
    for path in sorted(Path("src/engine/securityagent").rglob("*.py")):
        offending = {name for name in _imports(path) if name.startswith("engine.orchestrator")}
        assert not offending, f"{path}: imports {sorted(offending)}"


def test_the_agent_never_imports_verification_internals_directly() -> None:
    for path in sorted(Path("src/engine/securityagent").rglob("*.py")):
        offending = {name for name in _imports(path) if name.startswith("engine.verification")}
        assert not offending, f"{path}: imports {sorted(offending)}"


def test_the_agent_never_imports_debug_repro_suite_proof_machinery() -> None:
    for path in sorted(Path("src/engine/securityagent").rglob("*.py")):
        offending = {name for name in _imports(path) if name.startswith("engine.debugagent")}
        assert not offending, f"{path}: imports {sorted(offending)}"


def test_the_run_result_is_the_coding_agents_own_type_not_a_copy() -> None:
    from engine.refactoragent.app import RefactorRunResult
    from engine.testqaagent.app import QARunResult

    assert SecurityRunResult is CodeRunResult
    assert SecurityRunResult is RefactorRunResult
    assert SecurityRunResult is QARunResult


def test_the_limits_preset_only_overrides_settings_no_new_fields() -> None:
    from dataclasses import fields

    assert {f.name for f in fields(SECURITY_LIMITS)} == {f.name for f in fields(DEFAULT_LIMITS)}
    assert SECURITY_LIMITS.max_files_changed == 0
    assert SECURITY_LIMITS.max_repair_rounds == DEFAULT_LIMITS.max_repair_rounds


def test_the_base_tool_set_has_no_editor_or_command_tool() -> None:
    forbidden = {"write_file", "replace_exact", "run_command", "run_tests"}
    assert forbidden.isdisjoint(_BASE_SECURITY_TOOLS)
    # report_finding is not in the base set at all -- it arrives through
    # capabilities.tools (build_capabilities(report_findings=True)), the same
    # shared mechanism repo_graph and analyze_code already use.
    assert "report_finding" not in _BASE_SECURITY_TOOLS


# -- the whole offline stack ---------------------------------------------------


def test_a_review_records_findings_and_the_run_is_honestly_unverified(tmp_path: Path) -> None:
    """No file was changed -- by construction, this agent has no tool that
    could change one -- so verification is correctly declined. UNVERIFIED
    here is the honest, expected outcome of a pure review, not a failure."""
    result, fake = go(tmp_path, SECURITY_TURNS)

    assert isinstance(result, CodeRunResult)
    assert isinstance(result.report, FinalReport)
    assert result.report.files_changed == []
    assert result.report.verification_ran is False
    assert result.report.status == SessionStatus.UNVERIFIED.value
    assert result.exit_code == exit_code_for(SessionStatus.UNVERIFIED)
    assert result.report.planning_status is None

    findings = result.report.context_sources["review_findings"]
    assert isinstance(findings, list) and len(findings) == 1
    assert findings[0]["category"] == "unsafe_deserialization"
    assert findings[0]["severity"] == "LOW"
    assert findings[0]["basis"] == "observed"

    assert fake.seen_systems[0] is not None
    assert fake.seen_systems[0].startswith("You are a security review agent")


def test_no_findings_is_also_a_complete_honest_result(tmp_path: Path) -> None:
    result, _ = go(tmp_path, [tool_turn("read_file", {"path": "todo.py"}), final_turn("reviewed; nothing to report")])

    assert result.report.context_sources["review_findings"] is None
    assert result.report.status == SessionStatus.UNVERIFIED.value


def test_the_engines_own_source_tree_is_refused(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceRejected):
        run_security_review_task(
            task_text=SECURITY_TASK,
            workspace_path=Path(__file__).resolve().parent.parent,
            gateway=LLMGateway(provider([final_turn("done")])),
            model=MODEL,
            judge_model=MODEL,
        )


def test_capabilities_default_on_and_are_actually_reachable(tmp_path: Path) -> None:
    result, _ = go(tmp_path, SECURITY_TURNS)

    sources = result.report.context_sources
    assert sources["graph_queries"]
    assert sources["graph_queries"][0]["op"] == "show_module_graph"
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
        include_builtin_skills=False,
    )
    sources = result.report.context_sources
    assert sources["graph_queries"] is None
    assert sources["test_detection"] is None
    assert sources["skills"]["advertised"] == []


def test_the_run_is_recorded_in_the_database_under_its_own_metrics_label(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"

    go(tmp_path, SECURITY_TURNS, db_path=db_path)

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
    assert "SecurityReviewAgent.turn" in names
    assert "CodingAgent.plan" not in names
    assert not any(name.startswith("judge:") for name in names)  # declined, never called


def test_a_run_never_widens_the_shared_tool_registry(tmp_path: Path) -> None:
    from engine.codeagent.tools.registry import TOOL_REGISTRY

    before = dict(TOOL_REGISTRY)
    go(tmp_path, SECURITY_TURNS)
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
    # The first turn's tool call was refused, never executed.
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
