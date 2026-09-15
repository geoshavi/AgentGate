"""End-to-end composition for the Architecture Review Agent: task in, findings
and a verified report out.

Composition, not new machinery -- the same pattern ``securityagent/app.py``
already establishes for Agent #5, itself following ``refactoragent/app.py``
and ``testqaagent/app.py`` for Agents #3 and #4: this agent **is** the Coding
Agent's own composition --

    validate workspace -> capabilities -> AgentGate-verified session -> report

-- unchanged, with an architecture-review system prompt
(``architectureagent/prompt.py``), a distinct metrics label, capability
defaults tuned for what this review actually needs (``repo_graph`` as the
primary evidence source, ``detect_tests``, ``analyze_code``, ``report_finding``
and the first-party skills, on by default), and the same **narrower, read-only
tool set** the Security Review Agent uses: no ``write_file``, no
``replace_exact``, no ``run_command``. This agent reports; it does not edit,
structurally rather than by instruction alone.

``report_finding`` (``codeagent/tools/findings.py``) is the identical
capability the Security Review Agent uses -- built shared for exactly this
reuse, not duplicated here. Findings ride on the report the same way graph
queries and analysis runs already do -- ``FinalReport.context_sources
["review_findings"]`` -- so there is no Architecture-Agent-specific report
type either.

No verifier, judge, gate or repair logic changes here: this module supplies a
persona, a metrics label and a tool set, nothing else. In the common case a
review session changes no files, so verification is correctly *declined*
("the agent changed no files; there is nothing to verify") and the run ends
UNVERIFIED -- the honest, expected outcome for a review, not a failure.

There is no separate planning call, for the same reason every review and
editing agent in this codebase has none: "map relevant code" (the task's own
step 1) is exactly what the system prompt's procedure already asks for as
ordinary tool calls -- repo_graph above all.

**Kept separate from the legacy orchestrator.** There is no
``orchestrator/agents/architecture*.py`` at all; this module does not import,
extend or register with the older prompt-file agent system.
"""

import uuid
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path

from engine.architectureagent.limits import ARCHITECTURE_LIMITS
from engine.architectureagent.prompt import AGENT_NAME, build_architecture_prompt
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
from engine.state import db

# Read-only inspection only. No write_file, no replace_exact, no run_command
# and no run_tests, matching the Security Review Agent's own base set --
# report_finding is not listed here either: it arrives through
# capabilities.tools (build_capabilities(report_findings=True)).
_BASE_ARCHITECTURE_TOOLS: dict[str, Tool] = {
    "list_files": ListFilesTool(),
    "read_file": ReadFileTool(),
    "search_files": SearchFilesTool(),
    "git_diff": GitDiffTool(),
    "git_status": GitStatusTool(),
}

# Re-exported rather than redefined: an architecture-review run and a coding
# run produce the identical shape (task_id, status, agent_status, verification
# evidence, files changed, usage, context_sources -- see codeagent/report.py),
# so a second dataclass with the same fields would be exactly the duplication
# this phase's instructions rule out.
ArchitectureRunResult = CodeRunResult


def run_architecture_review_task(
    *,
    task_text: str,
    workspace_path: Path,
    gateway: LLMGateway,
    model: str,
    judge_model: str,
    provider_name: str = "anthropic",
    limits: Limits = ARCHITECTURE_LIMITS,
    policy: CommandPolicy = DEFAULT_POLICY,
    planned_budget: Decimal = Decimal("1.00"),
    max_tokens: int = 100_000,
    task_id: str | None = None,
    artifacts_root: Path | None = None,
    db_path: Path | None = None,
    skill_roots: Sequence[SkillRoot] = (),
    skill_bounds: SkillBounds | None = None,
    # Defaults flipped relative to run_coding_task/run_debug_task, matching
    # every other C-suite review/editing agent: a review without repo_graph
    # as its primary evidence, Semgrep-as-evidence and the first-party
    # skills is not what this agent is for, so these are on unless a caller
    # opts out.
    detect_tests: bool = True,
    analyze: bool = True,
    graph: bool = True,
    report_findings: bool = True,
    include_builtin_skills: bool = True,
    capabilities_config: Path | None = None,
    external_config: ExternalConfig | None = None,
) -> ArchitectureRunResult:
    """Run one architecture-review task end to end and return its report and
    exit code.

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
        report_findings=report_findings,
        include_builtin_skills=include_builtin_skills,
        docs=external.docs,
        github=external.github,
        egress_policy=external.policy,
        workspace_root=workspace.root,
    )
    session_id = task_id or f"arch-{uuid.uuid4().hex[:8]}"

    artifacts_dir: Path | None = None
    log_path: Path | None = None
    if artifacts_root is not None:
        artifacts_dir = Path(artifacts_root) / session_id
        log_path = artifacts_dir / "session.jsonl"

    log = SessionLog(log_path)
    budget = BudgetController(max_tokens=max_tokens, planned_budget=planned_budget)

    # This agent's own bespoke read-only base, merged with whatever
    # capabilities were admitted -- the same shape securityagent/app.py and
    # debugagent/fix.py's build_fix_tools use.
    tools = {**_BASE_ARCHITECTURE_TOOLS, **capabilities.tools}
    system_prompt = build_architecture_prompt(tools, skills_catalogue=capabilities.catalogue)

    if db_path is None:
        run = _execute(
            task_text, workspace, gateway, budget, model, judge_model, session_id,
            limits, policy, log, system_prompt, tools, run_id=None, conn=None,
            capabilities=capabilities,
        )
    else:
        # Same tables every other C-suite agent already writes: one row in
        # `runs`, and one row per LLM call in `agent_execution_metrics`
        # recorded by the Gateway itself. No schema change, no new writer.
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

    return ArchitectureRunResult(
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
        # Explicit here, like securityagent/app.py: this agent's base set is
        # not TOOL_REGISTRY, so CodingSession must be told what it is rather
        # than defaulting to the shared one.
        tools=tools,
        log=log,
        capabilities=capabilities,
        system_prompt=system_prompt,
        agent_name=AGENT_NAME,
    )


__all__ = [
    "AGENT_NAME",
    "ArchitectureRunResult",
    "VerifiedRun",
    "WorkspaceRejected",
    "build_architecture_prompt",
    "exit_code_for",
    "run_architecture_review_task",
    "validate_workspace",
]
