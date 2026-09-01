"""End-to-end composition for the Documentation/Handover Agent: task in,
verified report out.

Composition, not new machinery -- the same pattern every C-suite agent in
this codebase follows: this agent **is** the Coding Agent's own composition --

    validate workspace -> capabilities -> AgentGate-verified session -> report

-- unchanged, with a documentation system prompt (``docsagent/prompt.py``), a
distinct metrics label, capability defaults tuned for what a handover task
needs (``repo_graph``, ``detect_tests``, the first-party skills, and Context7/
GitHub automatically when an operator has configured them -- Semgrep is not
requested here, since static-analysis findings are not among the evidence
this task named), and a **doc-scoped write pair** in place of the ordinary
``write_file``/``replace_exact``: ``docsagent/tools.py``'s
``DocWriteFileTool``/``DocReplaceExactTool`` refuse any path that does not
look like documentation before ever reaching the real write tool they wrap.
"Writes only docs, never production source" is therefore a property of the
tool set, not an instruction a model could ignore -- the same structural
approach the Security and Architecture Review Agents use for "cannot edit at
all", narrowed here to "can edit only this".

No verifier, judge, gate or repair logic changes here: this module supplies a
persona, a metrics label and a tool set, nothing else. PASSED remains
reachable only by the same unchanged route every other agent uses --
``verdict.gate`` returning OK by way of ``verify.py``.

There is no separate planning call, for the same reason every other agent
here has none: "inspect the repository before documenting" (the task's own
step 1) is exactly what the prompt's own procedure already asks for as
ordinary tool calls.

This module reuses ``codeagent.app``'s workspace validation and exit-code
mapping directly, and returns the exact same ``CodeRunResult``/``FinalReport``
shapes every other C-suite agent does -- there is no Docs-Agent-specific
field to add, so there is no Docs-Agent-specific report type to duplicate one
into.

**Kept separate from the legacy orchestrator.** There is no
``orchestrator/agents/docs*.py`` or ``handover*.py``; this module does not
import, extend or register with the older prompt-file agent system.
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
from engine.codeagent.tools.shell import RunTestsTool
from engine.codeagent.verify import VerifiedRun, run_verified_session
from engine.docsagent.limits import DOCS_LIMITS
from engine.docsagent.prompt import AGENT_NAME, build_docs_prompt
from engine.docsagent.tools import DocReplaceExactTool, DocWriteFileTool
from engine.runtime.budget import BudgetController
from engine.runtime.gateway import LLMGateway
from engine.state import db

# Read plus run_tests (to validate a documented test command actually runs)
# plus the two doc-scoped writers. No run_command -- this agent has no
# business executing the product, only describing it.
_BASE_DOCS_TOOLS: dict[str, Tool] = {
    "list_files": ListFilesTool(),
    "read_file": ReadFileTool(),
    "search_files": SearchFilesTool(),
    "git_diff": GitDiffTool(),
    "git_status": GitStatusTool(),
    "run_tests": RunTestsTool(),
    "write_file": DocWriteFileTool(),
    "replace_exact": DocReplaceExactTool(),
}

# Re-exported rather than redefined: a docs run and a coding run produce the
# identical shape (task_id, status, agent_status, verification evidence,
# files changed, usage, context_sources -- see codeagent/report.py), so a
# second dataclass with the same fields would be exactly the duplication this
# phase's instructions rule out.
DocsRunResult = CodeRunResult


def run_docs_task(
    *,
    task_text: str,
    workspace_path: Path,
    gateway: LLMGateway,
    model: str,
    judge_model: str,
    provider_name: str = "anthropic",
    limits: Limits = DOCS_LIMITS,
    policy: CommandPolicy = DEFAULT_POLICY,
    planned_budget: Decimal = Decimal("1.00"),
    max_tokens: int = 100_000,
    task_id: str | None = None,
    artifacts_root: Path | None = None,
    db_path: Path | None = None,
    skill_roots: Sequence[SkillRoot] = (),
    skill_bounds: SkillBounds | None = None,
    # Defaults flipped relative to run_coding_task/run_debug_task, matching
    # every other C-suite agent: documenting without a dependency map, a
    # test-detection signal and the first-party skills is not what this
    # agent is for. analyze defaults False -- Semgrep is not among the
    # evidence this task named, unlike the review and refactoring agents.
    detect_tests: bool = True,
    analyze: bool = False,
    graph: bool = True,
    include_builtin_skills: bool = True,
    capabilities_config: Path | None = None,
    external_config: ExternalConfig | None = None,
) -> DocsRunResult:
    """Run one documentation/handover task end to end and return its report
    and exit code.

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
    session_id = task_id or f"docs-{uuid.uuid4().hex[:8]}"

    artifacts_dir: Path | None = None
    log_path: Path | None = None
    if artifacts_root is not None:
        artifacts_dir = Path(artifacts_root) / session_id
        log_path = artifacts_dir / "session.jsonl"

    log = SessionLog(log_path)
    budget = BudgetController(max_tokens=max_tokens, planned_budget=planned_budget)

    # This agent's own bespoke base -- read tools, run_tests, and the two
    # doc-scoped writers -- merged with whatever capabilities were admitted,
    # the same shape every other non-Coding C-suite agent uses.
    tools = {**_BASE_DOCS_TOOLS, **capabilities.tools}
    system_prompt = build_docs_prompt(tools, skills_catalogue=capabilities.catalogue)

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

    return DocsRunResult(
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
        # Explicit here, like securityagent/app.py and architectureagent/
        # app.py: this agent's base set is not TOOL_REGISTRY, so
        # CodingSession must be told what it is rather than defaulting to
        # the shared one.
        tools=tools,
        log=log,
        capabilities=capabilities,
        system_prompt=system_prompt,
        agent_name=AGENT_NAME,
    )


__all__ = [
    "AGENT_NAME",
    "DocsRunResult",
    "VerifiedRun",
    "WorkspaceRejected",
    "build_docs_prompt",
    "exit_code_for",
    "run_docs_task",
    "validate_workspace",
]
