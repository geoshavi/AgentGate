"""End-to-end composition for the Security Review Agent: task in, findings and
a verified report out.

Composition, not new machinery -- the same pattern ``refactoragent/app.py``
and ``testqaagent/app.py`` already establish for Agents #3 and #4: this agent
**is** the Coding Agent's own composition --

    validate workspace -> capabilities -> AgentGate-verified session -> report

-- unchanged, with four injected differences: a security-review system prompt
(``securityagent/prompt.py``), a distinct metrics label, capability defaults
tuned for what a review actually needs (``repo_graph``, ``detect_tests``,
``analyze_code`` and the first-party skills, on by default), and -- new here,
because this is a review agent rather than an editor -- a **narrower,
read-only tool set** built the same way the Debug Agent's fix loop builds its
own (see ``debugagent/fix.py``'s ``_BASE_FIX_TOOLS``): no ``write_file``, no
``replace_exact``, no ``run_command``. This agent reports; it does not edit.

``run_verified_session`` already gained the two injection points this needs
(``system_prompt``, ``agent_name``) for Agent #3 -- see that module's
docstring. No verifier, judge, gate or repair logic changes here: this module
supplies a persona, a metrics label and a tool set, nothing else. In the
common case a review session changes no files, so verification is correctly
*declined* ("the agent changed no files; there is nothing to verify") and the
run ends UNVERIFIED -- that is the honest, expected outcome for a review, not
a failure. If a future caller ever widened this agent's tool set to include
an editor tool, ``PASSED`` would still be reachable only by the same
unchanged route every other agent uses: ``verdict.gate`` returning OK by way
of ``verify.py``. Nothing about that path is touched here.

There is no separate planning call, for the same reason Agents #3 and #4 have
none: "map relevant code and trust boundaries" (the task's own step 1) is
exactly what the system prompt's procedure already asks for as ordinary tool
calls -- ``repo_graph``, ``read_file`` -- and a second, separately-labelled
planning phase would spend tokens without changing what the loop is told to
do.

This module reuses ``codeagent.app``'s workspace validation and exit-code
mapping directly, and returns the exact same ``CodeRunResult``/``FinalReport``
shapes the other three agents do. Findings ride on the report the same way
graph queries and analysis runs already do -- ``FinalReport.context_sources
["security_findings"]`` -- so there is no Security-Agent-specific report type
to duplicate one into.

**Kept separate from the legacy orchestrator.** There is no
``orchestrator/agents/security*.py`` at all; this module does not import,
extend or register with the older prompt-file agent system.
"""

import uuid
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path

from engine.capabilities.external.config import ExternalConfig, load_external_config
from engine.capabilities.skills import SkillBounds, SkillRoot
from engine.codeagent.app import CodeRunResult, WorkspaceRejected, exit_code_for, validate_workspace
from engine.codeagent.capabilities import build_capabilities
from engine.codeagent.limits import Limits
from engine.codeagent.log import SessionLog
from engine.codeagent.policy import DEFAULT_POLICY, CommandPolicy
from engine.codeagent.report import build_report
from engine.codeagent.state import SessionStatus
from engine.codeagent.tools.base import Tool
from engine.codeagent.tools.fs import ListFilesTool, ReadFileTool
from engine.codeagent.tools.git import GitDiffTool, GitStatusTool
from engine.codeagent.tools.search import SearchFilesTool
from engine.codeagent.verify import VerifiedRun, run_verified_session
from engine.runtime.budget import BudgetController
from engine.runtime.gateway import LLMGateway
from engine.securityagent.limits import SECURITY_LIMITS
from engine.securityagent.prompt import AGENT_NAME, build_security_prompt
from engine.securityagent.tools.finding import ReportFindingTool
from engine.state import db

# Read-only inspection only. No write_file, no replace_exact, no run_command
# and no run_tests -- a review agent has no business executing the product or
# its suite, and the absence is what makes "does not edit production code" a
# property of the tool set rather than an instruction a model could ignore.
_BASE_SECURITY_TOOLS: dict[str, Tool] = {
    "list_files": ListFilesTool(),
    "read_file": ReadFileTool(),
    "search_files": SearchFilesTool(),
    "git_diff": GitDiffTool(),
    "git_status": GitStatusTool(),
    "report_finding": ReportFindingTool(),
}

# Re-exported rather than redefined: a security-review run and a coding run
# produce the identical shape (task_id, status, agent_status, verification
# evidence, files changed, usage, context_sources -- see codeagent/report.py),
# so a second dataclass with the same fields would be exactly the duplication
# this phase's instructions rule out.
SecurityRunResult = CodeRunResult


def run_security_review_task(
    *,
    task_text: str,
    workspace_path: Path,
    gateway: LLMGateway,
    model: str,
    judge_model: str,
    provider_name: str = "anthropic",
    limits: Limits = SECURITY_LIMITS,
    policy: CommandPolicy = DEFAULT_POLICY,
    planned_budget: Decimal = Decimal("1.00"),
    max_tokens: int = 100_000,
    task_id: str | None = None,
    artifacts_root: Path | None = None,
    db_path: Path | None = None,
    skill_roots: Sequence[SkillRoot] = (),
    skill_bounds: SkillBounds | None = None,
    # Defaults flipped relative to run_coding_task/run_debug_task, matching
    # run_refactor_task and run_qa_task: a review without a dependency map,
    # Semgrep-as-evidence and the first-party skills is not what this agent
    # is for, so these are on unless a caller opts out.
    detect_tests: bool = True,
    analyze: bool = True,
    graph: bool = True,
    include_builtin_skills: bool = True,
    capabilities_config: Path | None = None,
    external_config: ExternalConfig | None = None,
) -> SecurityRunResult:
    """Run one security-review task end to end and return its report and exit
    code.

    Raises ``WorkspaceRejected`` before any model call if the workspace is
    unusable -- the same refusal ``run_coding_task`` raises, including for
    the engine's own source tree. Every other failure -- provider, tool,
    verifier, budget -- is already a status rather than an exception by the
    time it reaches here, so this function returns a report in all of those
    cases instead of raising.
    """
    workspace = validate_workspace(workspace_path, max_files_changed=limits.max_files_changed)
    external = external_config or load_external_config(capabilities_config)
    capabilities = build_capabilities(
        skill_roots=skill_roots,
        bounds=skill_bounds,
        detect_tests=detect_tests,
        analyze=analyze,
        graph=graph,
        include_builtin_skills=include_builtin_skills,
        docs=external.docs,
        github=external.github,
        egress_policy=external.policy,
        workspace_root=workspace.root,
    )
    session_id = task_id or f"sec-{uuid.uuid4().hex[:8]}"

    artifacts_dir: Path | None = None
    log_path: Path | None = None
    if artifacts_root is not None:
        artifacts_dir = Path(artifacts_root) / session_id
        log_path = artifacts_dir / "session.jsonl"

    log = SessionLog(log_path)
    budget = BudgetController(max_tokens=max_tokens, planned_budget=planned_budget)

    # This agent's own bespoke tool set, merged with whatever capabilities
    # were admitted -- the same shape debugagent/fix.py's build_fix_tools
    # uses, applied to a read-only base instead of a narrowed-write one.
    tools = {**_BASE_SECURITY_TOOLS, **capabilities.tools}
    system_prompt = build_security_prompt(tools, skills_catalogue=capabilities.catalogue)

    if db_path is None:
        run = _execute(
            task_text, workspace, gateway, budget, model, judge_model, session_id,
            limits, policy, log, system_prompt, tools, run_id=None, conn=None,
            capabilities=capabilities,
        )
    else:
        # Same tables `engine code`, `engine debug` and the other three C-suite
        # agents already write: one row in `runs`, and one row per LLM call in
        # `agent_execution_metrics` recorded by the Gateway itself. No schema
        # change, no new writer.
        with db.connect(Path(db_path)) as conn:
            run_id = db.create_run(conn, task_text, provider_name, model)
            run = _execute(
                task_text, workspace, gateway, budget, model, judge_model, session_id,
                limits, policy, log, system_prompt, tools, run_id=run_id, conn=conn,
                capabilities=capabilities,
            )
            db.finish_run(
                conn,
                run_id,
                "passed" if run.status is SessionStatus.PASSED else "failed",
                len(run.states),
            )

    report = build_report(run)
    report_path: Path | None = None
    if artifacts_dir is not None:
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        report_path = artifacts_dir / "report.json"
        report_path.write_text(report.to_json(), encoding="utf-8")

    return SecurityRunResult(
        report=report,
        exit_code=exit_code_for(run.status),
        artifacts_dir=artifacts_dir,
        report_path=report_path,
        log_path=log_path,
    )


def _execute(
    task_text, workspace, gateway, budget, model, judge_model, session_id,
    limits, policy, log, system_prompt, tools, *, run_id, conn, capabilities=None,
):  # type: ignore[no-untyped-def]
    return run_verified_session(
        task_text=task_text,
        workspace=workspace,
        gateway=gateway,
        budget=budget,
        model=model,
        judge_model=judge_model,
        task_id=session_id,
        run_id=run_id,
        conn=conn,
        limits=limits,
        policy=policy,
        # Explicit here, unlike the other three agents: this agent's base set
        # is not TOOL_REGISTRY, so CodingSession must be told what it is
        # rather than defaulting to the shared one.
        tools=tools,
        log=log,
        capabilities=capabilities,
        system_prompt=system_prompt,
        agent_name=AGENT_NAME,
    )


__all__ = [
    "AGENT_NAME",
    "SecurityRunResult",
    "VerifiedRun",
    "WorkspaceRejected",
    "build_security_prompt",
    "exit_code_for",
    "run_security_review_task",
    "validate_workspace",
]
