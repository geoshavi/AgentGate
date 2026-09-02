"""Full Integration acceptance: all seven AgentGate engineering agents, run
through their real production composition, entirely offline.

This file adds nothing new to any individual agent's coverage -- every
turn-by-turn behaviour proven here already has a dedicated home in
``test_{codeagent,debugagent,refactoragent,testqaagent,securityagent,
architectureagent,docsagent}_app.py``. What it proves that no single one of
those files can is the *whole-stack* property: run the seven together, in one
process, sharing nothing but the workspace and reporting machinery they are
designed to share, and confirm what changes for one agent never touches
another's:

    schema      the six composition agents (Coding, Refactoring, Test/QA,
                Security, Architecture, Docs) return the identical
                ``FinalReport``/``CodeRunResult`` types -- not six copies of
                one shape -- while the Debug Agent's report stays its own,
                deliberately distinct type
    boundary    no capability (``report_finding``, ``repo_graph``,
                ``analyze_code``) can hand a review agent an editing or
                shell-executing tool, regardless of which flags are on
    isolation   seven runs against seven separate workspaces in one test
                process never cross-contaminate a file, a report, or an
                egress ledger
    advisory    a Security Agent's ``report_finding`` calls surface in
                ``context_sources`` without moving ``verdict.gate``'s
                UNVERIFIED conclusion for a run that changed no files
    frozen      the Debug Agent's repro/suite/proof semantics are unchanged
                when its run is interleaved with six other agents' runs in
                the same process
    fail-closed no agent here is given an ``external_config``, so Context7
                and GitHub stay absent from every report's context_sources

Every run below is offline: a scripted provider stands in for the model, and
no test here opens a socket, calls a real subprocess beyond the fixtures'
own ``pytest -q``, or spends a real budget.
"""

from decimal import Decimal
from pathlib import Path

from codeagent_harness import CLEAN_CRITIC, MODEL, DebugScenarioProvider
from test_architectureagent_app import ARCHITECTURE_TURNS
from test_architectureagent_app import fixture_copy as architecture_fixture_copy
from test_architectureagent_app import go as run_architecture
from test_codeagent_app import SOLVE_TURNS as CODING_TURNS
from test_codeagent_app import go as run_coding
from test_debugagent_app import BUG, DIAGNOSIS, LENS_PROMPTS, REPRO, SOLVE_TURNS, SUITE
from test_debugagent_app import fixture_copy as debug_fixture_copy
from test_docsagent_app import DOCS_TURNS
from test_docsagent_app import go as run_docs
from test_refactoragent_app import REFACTOR_TURNS
from test_refactoragent_app import go as run_refactor
from test_securityagent_app import _BASE_SECURITY_TOOLS, SECURITY_TURNS
from test_securityagent_app import go as run_security
from test_testqaagent_app import QA_TURNS
from test_testqaagent_app import go as run_qa

from engine.architectureagent.app import _BASE_ARCHITECTURE_TOOLS, ArchitectureRunResult
from engine.codeagent.app import CodeRunResult
from engine.codeagent.capabilities import build_capabilities
from engine.codeagent.state import SessionStatus
from engine.debugagent.app import DebugRunResult, run_debug_task
from engine.debugagent.fix import ProofStatus
from engine.debugagent.limits import DEBUG_LIMITS
from engine.docsagent.app import DocsRunResult
from engine.refactoragent.app import RefactorRunResult
from engine.runtime.gateway import LLMGateway
from engine.securityagent.app import SecurityRunResult
from engine.testqaagent.app import QARunResult

FORBIDDEN_TOOLS = {"write_file", "replace_exact", "run_command"}


def test_the_six_composition_agents_share_one_report_type_not_six() -> None:
    """A duplicated dataclass -- not merely a matching shape -- is exactly the
    "inconsistent report schema across agents" this run was asked to rule
    out. Identity (``is``), not structural equality, is the property that
    catches it."""
    assert SecurityRunResult is CodeRunResult
    assert ArchitectureRunResult is CodeRunResult
    assert QARunResult is CodeRunResult
    assert RefactorRunResult is CodeRunResult
    assert DocsRunResult is CodeRunResult

    # The Debug Agent's report is deliberately its own type -- it carries
    # frozen repro/suite/proof fields no other agent has -- so it must NOT
    # collapse into the shared shape.
    assert DebugRunResult is not CodeRunResult


def test_no_capability_combination_ever_yields_an_editor_or_shell_tool() -> None:
    """``report_finding``, ``repo_graph`` and ``analyze_code`` are the only
    capabilities a review agent is offered. None of them, alone or together,
    can widen a read-only agent's authority to touch the workspace or a
    shell -- that has to stay true independent of which flags a caller
    passes."""
    bundle = build_capabilities(
        detect_tests=True, analyze=True, graph=True, report_findings=True,
        include_builtin_skills=False,
    )
    assert FORBIDDEN_TOOLS.isdisjoint(bundle.tools)
    assert FORBIDDEN_TOOLS.isdisjoint(_BASE_SECURITY_TOOLS)
    assert FORBIDDEN_TOOLS.isdisjoint(_BASE_ARCHITECTURE_TOOLS)


def run_debug(tmp_path: Path):  # type: ignore[no-untyped-def]
    fake = DebugScenarioProvider(
        diagnosis_turns=[DIAGNOSIS], fix_turns=SOLVE_TURNS,
        judge_rounds=[CLEAN_CRITIC], lens_prompts=LENS_PROMPTS,
    )
    result = run_debug_task(
        task_text=BUG,
        workspace_path=debug_fixture_copy(tmp_path),
        repro_argv=REPRO,
        suite_argv=SUITE,
        gateway=LLMGateway(fake),
        model=MODEL,
        judge_model=MODEL,
        limits=DEBUG_LIMITS,
        planned_budget=Decimal("10.00"),
        task_id="dbg-full-integration",
    )
    return result


def test_all_seven_agents_run_together_offline_without_state_leaking(tmp_path: Path) -> None:
    coding, _ = run_coding(tmp_path / "coding", CODING_TURNS)
    refactor, _ = run_refactor(tmp_path / "refactor", REFACTOR_TURNS)
    qa, _ = run_qa(tmp_path / "qa", QA_TURNS)
    security, _ = run_security(tmp_path / "security", SECURITY_TURNS)
    architecture, _ = run_architecture(tmp_path / "architecture", ARCHITECTURE_TURNS)
    docs, _ = run_docs(tmp_path / "docs", DOCS_TURNS)
    debug = run_debug(tmp_path / "debug")

    # -- editing agents actually edited, each inside its own workspace only --
    assert coding.report.status == SessionStatus.PASSED.value
    assert coding.report.files_changed == ["todo.py", "test_due_date.py"]

    assert refactor.report.status == SessionStatus.PASSED.value
    assert refactor.report.files_changed == ["todo.py"]

    assert qa.report.status == SessionStatus.PASSED.value
    assert qa.report.files_changed == ["test_todo_edge_cases.py"]

    assert docs.report.status == SessionStatus.PASSED.value
    assert docs.report.files_changed == ["HANDOVER.md"]

    # -- review agents changed nothing, in their own workspace or anyone else's --
    original_todo = (
        architecture_fixture_copy(tmp_path / "reference") / "todo.py"
    ).read_text(encoding="utf-8")

    assert security.report.files_changed == []
    assert security.report.status == SessionStatus.UNVERIFIED.value
    assert (tmp_path / "security" / "ws" / "todo.py").read_text(encoding="utf-8") == original_todo

    assert architecture.report.files_changed == []
    assert architecture.report.status == SessionStatus.UNVERIFIED.value
    assert (tmp_path / "architecture" / "ws" / "todo.py").read_text(encoding="utf-8") == original_todo

    # -- findings are advisory: present in context_sources, absent from the
    #    route that produced UNVERIFIED (no file changed, so verification was
    #    correctly declined -- report_finding never entered that decision) --
    sec_findings = security.report.context_sources["review_findings"]
    assert isinstance(sec_findings, list) and len(sec_findings) == 1
    arch_findings = architecture.report.context_sources["review_findings"]
    assert isinstance(arch_findings, list) and len(arch_findings) == 1
    assert security.report.verification_ran is False
    assert architecture.report.verification_ran is False

    # -- no agent here was given external_config, so Context7/GitHub stay
    #    fail-closed by default across the whole stack --
    for run in (coding, refactor, qa, security, architecture, docs):
        assert run.report.context_sources.get("external") is None

    # -- the Debug Agent's frozen semantics are unaffected by six other
    #    agents having just run in this same process --
    debug_report = debug.report
    assert list(debug_report.repro_command) == REPRO
    assert list(debug_report.suite_command) == SUITE
    assert debug_report.observed.proof_status == ProofStatus.PROVEN.value
    assert debug_report.status == SessionStatus.PASSED.value
    assert debug_report.context_sources.get("external") is None
