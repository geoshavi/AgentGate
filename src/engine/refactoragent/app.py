"""End-to-end composition for the Refactoring Agent: task in, verified report out.

Composition, not new machinery -- the same way the Debug Agent's fix loop
**is** ``CodingSession`` with a narrower tool set and a different brief (see
``debugagent/fix.py``'s module docstring), Agent #3 **is** the Coding Agent's
own composition --

    validate workspace -> capabilities -> AgentGate-verified session -> report

-- unchanged, with three injected differences: a refactoring system prompt
(``refactoragent/prompt.py``), a distinct metrics label, and capability
defaults tuned for what a refactor actually needs -- ``repo_graph``,
``detect_tests``, ``analyze_code`` and the first-party skills, all on by
default here rather than opt-in, because a refactor without dependency
mapping and a test signal is not this agent's job. ``run_verified_session``
gained exactly the two injection points ``CodingSession`` itself already had
(``system_prompt``, ``agent_name``) to make this possible -- see that
module's docstring. No verifier, judge, gate or repair logic changed: this
module supplies a persona and a metrics label, nothing else, and PASSED is
reachable only by the same route it always was -- ``verdict.gate`` returning
OK by way of ``verify.py``.

There is no separate planning call here. The Coding Agent's ``make_plan``
step is generic enough to reuse, but it is also an extra model call this
agent does not need: "inspect the task and repo structure" (the task's own
step 1) is exactly what the system prompt's procedure already asks for as
ordinary tool calls -- ``list_files``, ``repo_graph`` -- and a second,
separately-labelled planning phase would spend tokens without changing what
the loop is told to do.

This module reuses ``codeagent.app``'s workspace validation and exit-code
mapping directly rather than re-deriving them, and returns the exact same
``CodeRunResult``/``FinalReport`` shapes the Coding Agent does -- there is no
Refactoring-Agent-specific field to add, so there is no Refactoring-Agent-
specific type to duplicate one into.

**Kept separate from the legacy orchestrator.** ``orchestrator/agents/
refactoring.py`` is an older, unrelated prompt-file agent with no workspace
guard, no command policy, and no AgentGate verification -- this module does
not import it, extend it, or register with it, and does not touch it.
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
from engine.codeagent.tools.registry import TOOL_REGISTRY
from engine.codeagent.verify import VerifiedRun, run_verified_session
from engine.refactoragent.limits import REFACTOR_LIMITS
from engine.refactoragent.prompt import AGENT_NAME, build_refactor_prompt
from engine.runtime.budget import BudgetController
from engine.runtime.gateway import LLMGateway
from engine.state import db

# Re-exported rather than redefined: a refactoring run and a coding run
# produce the identical shape (task_id, status, agent_status, verification
# evidence, files changed, usage, context_sources -- see codeagent/report.py),
# so a second dataclass with the same fields would be the duplication this
# phase's instructions rule out. The alias exists only so a caller reading
# this module does not have to know that fact to use it.
RefactorRunResult = CodeRunResult


def run_refactor_task(
    *,
    task_text: str,
    workspace_path: Path,
    gateway: LLMGateway,
    model: str,
    judge_model: str,
    provider_name: str = "anthropic",
    limits: Limits = REFACTOR_LIMITS,
    policy: CommandPolicy = DEFAULT_POLICY,
    planned_budget: Decimal = Decimal("1.00"),
    max_tokens: int = 100_000,
    task_id: str | None = None,
    artifacts_root: Path | None = None,
    db_path: Path | None = None,
    skill_roots: Sequence[SkillRoot] = (),
    skill_bounds: SkillBounds | None = None,
    # Defaults flipped relative to run_coding_task/run_debug_task: a refactor
    # without dependency mapping, a test signal and the first-party skills is
    # not what this agent is for, so these are on unless a caller opts out.
    detect_tests: bool = True,
    analyze: bool = True,
    graph: bool = True,
    include_builtin_skills: bool = True,
    capabilities_config: Path | None = None,
    external_config: ExternalConfig | None = None,
) -> RefactorRunResult:
    """Run one refactoring task end to end and return its report and exit code.

    Raises ``WorkspaceRejected`` before any model call if the workspace is
    unusable -- the same refusal ``run_coding_task`` raises, including for the
    engine's own source tree. Every other failure -- provider, tool, verifier,
    budget -- is already a status rather than an exception by the time it
    reaches here, so this function returns a report in all of those cases
    instead of raising.
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
    session_id = task_id or f"rf-{uuid.uuid4().hex[:8]}"

    artifacts_dir: Path | None = None
    log_path: Path | None = None
    if artifacts_root is not None:
        artifacts_dir = Path(artifacts_root) / session_id
        log_path = artifacts_dir / "session.jsonl"

    log = SessionLog(log_path)
    budget = BudgetController(max_tokens=max_tokens, planned_budget=planned_budget)

    # Built from the exact tool set CodingSession will assemble internally
    # (TOOL_REGISTRY merged with the capability tools) -- computed here rather
    # than left to protocol.build_system_prompt because a custom system_prompt
    # bypasses that generator entirely, the same reason debugagent/fix.py
    # computes fix_tool_names() itself instead of calling it.
    tools = {**TOOL_REGISTRY, **capabilities.tools}
    system_prompt = build_refactor_prompt(tools, skills_catalogue=capabilities.catalogue)

    if db_path is None:
        run = _execute(
            task_text, workspace, gateway, budget, model, judge_model, session_id,
            limits, policy, log, system_prompt, run_id=None, conn=None, capabilities=capabilities,
        )
    else:
        # Same tables `engine code` and `engine debug` already write: one row
        # in `runs`, and one row per LLM call in `agent_execution_metrics`
        # recorded by the Gateway itself. No schema change, no new writer.
        with db.connect(Path(db_path)) as conn:
            run_id = db.create_run(conn, task_text, provider_name, model)
            run = _execute(
                task_text, workspace, gateway, budget, model, judge_model, session_id,
                limits, policy, log, system_prompt, run_id=run_id, conn=conn,
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

    return RefactorRunResult(
        report=report,
        exit_code=exit_code_for(run.status),
        artifacts_dir=artifacts_dir,
        report_path=report_path,
        log_path=log_path,
    )


def _execute(
    task_text, workspace, gateway, budget, model, judge_model, session_id,
    limits, policy, log, system_prompt, *, run_id, conn, capabilities=None,
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
        log=log,
        capabilities=capabilities,
        system_prompt=system_prompt,
        agent_name=AGENT_NAME,
    )


__all__ = [
    "AGENT_NAME",
    "RefactorRunResult",
    "VerifiedRun",
    "WorkspaceRejected",
    "build_refactor_prompt",
    "exit_code_for",
    "run_refactor_task",
    "validate_workspace",
]
