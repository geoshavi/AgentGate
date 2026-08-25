"""End-to-end composition: task in, verified report out.

The one place that wires P1-P4 together --

    validate workspace -> bounded repo context -> plan -> session
        -> AgentGate verification -> bounded repair -> report

-- and nothing more. It owns no policy of its own: every bound comes from
``Limits``, every safety guarantee from ``Workspace``/``CommandPolicy``, and
the verdict from ``verdict.gate`` by way of ``verify.py``. Keeping the
composition root out of ``cli.py`` follows the existing engine, where
``cli.py`` parses arguments and ``orchestrator/engine.py`` composes the run.

**The workspace is edited in place.** That is a departure from blueprint §9,
which specified copy-in/diff-out, and it is what the ``--workspace`` argument
means: the agent's changes are meant to survive the run. Confinement is
unchanged -- every path still goes through ``Workspace.resolve`` -- but the
blast radius is now the directory the caller names, so this module refuses one
directory outright: the engine's own source tree. An agent editing the
verification code that judges it would invalidate the measurement history this
repository exists to protect, and that is not a mistake worth leaving
available.

Exit codes are the honest three: verified, blocked, broken. ``PASSED`` is
reachable only when AgentGate returned OK.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from engine.capabilities.skills import SkillBounds, SkillRoot
from engine.codeagent.capabilities import build_capabilities
from engine.codeagent.limits import DEFAULT_LIMITS, Limits
from engine.codeagent.log import SessionLog
from engine.codeagent.plan import PlanOutcome, make_plan
from engine.codeagent.policy import DEFAULT_POLICY, CommandPolicy
from engine.codeagent.report import FinalReport, build_report
from engine.codeagent.state import SessionStatus
from engine.codeagent.tools.base import ToolContext
from engine.codeagent.tools.fs import ListFilesTool
from engine.codeagent.tools.registry import TOOL_REGISTRY
from engine.codeagent.verify import run_verified_session
from engine.codeagent.workspace import Workspace, WorkspaceError
from engine.runtime.budget import BudgetController
from engine.runtime.gateway import LLMGateway
from engine.state import db

EXIT_VERIFIED = 0
EXIT_UNVERIFIED = 1
EXIT_ERROR = 2

# Presence of this file means the workspace is this engine's own checkout.
# Chosen over a generic "is the cwd" test because it identifies the tree by the
# thing that must not be touched -- the measured verification path -- rather
# than by where the command happened to be run from.
_ENGINE_MARKER = Path("src") / "engine" / "verification" / "verdict.py"


class WorkspaceRejected(Exception):
    """The workspace cannot be used, and no model call was made."""


@dataclass(frozen=True)
class CodeRunResult:
    report: FinalReport
    exit_code: int
    artifacts_dir: Path | None = None
    report_path: Path | None = None
    log_path: Path | None = None


def validate_workspace(path: Path, *, max_files_changed: int | None = None) -> Workspace:
    """Resolve and accept a workspace, or refuse before anything is spent."""
    resolved = Path(path).expanduser()
    if not resolved.exists():
        raise WorkspaceRejected(f"workspace does not exist: {resolved}")
    if not resolved.is_dir():
        raise WorkspaceRejected(f"workspace is not a directory: {resolved}")
    if (resolved / _ENGINE_MARKER).exists():
        raise WorkspaceRejected(
            f"refusing to run against the engine's own source tree ({resolved}): the agent "
            "would be able to edit the verification code that judges it. Copy the target "
            "elsewhere and point --workspace at the copy."
        )
    try:
        return Workspace(
            resolved,
            **({} if max_files_changed is None else {"max_files_changed": max_files_changed}),
        )
    except WorkspaceError as exc:
        raise WorkspaceRejected(str(exc)) from exc


def build_repo_context(
    workspace: Workspace,
    limits: Limits = DEFAULT_LIMITS,
    policy: CommandPolicy = DEFAULT_POLICY,
) -> str:
    """A shallow, bounded listing for the planner: names and sizes, no contents.

    Produced with the same ``list_files`` tool the agent uses, so the planner
    cannot be shown a credential file the agent could not have opened -- the
    denylist is applied once, in one place, and inherited here.
    """
    context = ToolContext(workspace=workspace, policy=policy, limits=limits)
    result = ListFilesTool().run({"max_depth": limits.max_list_depth}, context)
    text = result.output if result.ok else f"(workspace listing unavailable: {result.error})"
    return text[: limits.max_plan_context_chars]


def run_coding_task(
    *,
    task_text: str,
    workspace_path: Path,
    gateway: LLMGateway,
    model: str,
    judge_model: str,
    provider_name: str = "anthropic",
    limits: Limits = DEFAULT_LIMITS,
    policy: CommandPolicy = DEFAULT_POLICY,
    planned_budget: Decimal = Decimal("1.00"),
    max_tokens: int = 100_000,
    task_id: str | None = None,
    artifacts_root: Path | None = None,
    db_path: Path | None = None,
    skill_roots: Sequence[SkillRoot] = (),
    skill_bounds: SkillBounds | None = None,
    detect_tests: bool = False,
    include_builtin_skills: bool = False,
) -> CodeRunResult:
    """Run one task end to end and return its report and exit code.

    Raises ``WorkspaceRejected`` before any model call if the workspace is
    unusable. Every other failure -- provider, tool, verifier, budget -- is
    already a status rather than an exception by the time it reaches here, so
    this function returns a report in all of those cases instead of raising.
    """
    workspace = validate_workspace(workspace_path, max_files_changed=limits.max_files_changed)
    # Capabilities are assembled here, before anything that can edit exists:
    # build_capabilities snapshots every skill root and only then builds the
    # tools that serve them. A mutating tool object therefore cannot be created
    # before the skill content was read, which is what makes a skill root inside
    # the workspace safe rather than merely permitted. No roots -- the default --
    # yields an empty bundle and today's behaviour exactly.
    capabilities = build_capabilities(
        skill_roots=skill_roots,
        bounds=skill_bounds,
        detect_tests=detect_tests,
        include_builtin_skills=include_builtin_skills,
        # So a first-party root that happens to sit inside the target workspace
        # -- AgentGate debugging its own repository -- is recorded as overlapping
        # rather than mistaken for an external one.
        workspace_root=workspace.root,
    )
    session_id = task_id or f"cd-{uuid.uuid4().hex[:8]}"

    artifacts_dir: Path | None = None
    log_path: Path | None = None
    if artifacts_root is not None:
        artifacts_dir = Path(artifacts_root) / session_id
        log_path = artifacts_dir / "session.jsonl"

    log = SessionLog(log_path)
    # The token ceiling is the budget's, not an agent bound: BudgetController
    # already owns it and enforces it before every call.
    budget = BudgetController(max_tokens=max_tokens, planned_budget=planned_budget)

    if db_path is None:
        run = _execute(
            task_text, workspace, gateway, budget, model, judge_model, session_id,
            limits, policy, log, run_id=None, conn=None, capabilities=capabilities,
        )
    else:
        # Same tables engine run already writes: one row in `runs`, and one row
        # per LLM call in `agent_execution_metrics` recorded by the Gateway
        # itself. No schema change, no new writer.
        with db.connect(Path(db_path)) as conn:
            run_id = db.create_run(conn, task_text, provider_name, model)
            run = _execute(
                task_text, workspace, gateway, budget, model, judge_model, session_id,
                limits, policy, log, run_id=run_id, conn=conn, capabilities=capabilities,
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

    return CodeRunResult(
        report=report,
        exit_code=exit_code_for(run.status),
        artifacts_dir=artifacts_dir,
        report_path=report_path,
        log_path=log_path,
    )


def _execute(
    task_text, workspace, gateway, budget, model, judge_model, session_id,
    limits, policy, log, *, run_id, conn, capabilities=None,
):  # type: ignore[no-untyped-def]
    planning = _plan(
        task_text, workspace, gateway, budget, model, session_id, limits, policy, log, run_id, conn
    )
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
        planning=planning,
        capabilities=capabilities,
    )


def _plan(
    task_text, workspace, gateway, budget, model, session_id, limits, policy, log, run_id, conn
) -> PlanOutcome:  # type: ignore[no-untyped-def]
    return make_plan(
        task_text=task_text,
        workspace=workspace,
        gateway=gateway,
        budget=budget,
        model=model,
        task_id=session_id,
        tool_names=sorted(TOOL_REGISTRY),
        repo_context=build_repo_context(workspace, limits, policy),
        run_id=run_id,
        conn=conn,
        limits=limits,
        policy=policy,
        log=log,
    )


def exit_code_for(status: SessionStatus) -> int:
    """Three truthful outcomes.

    ``UNVERIFIED`` is deliberately distinct from the aborted statuses: "the
    work was reviewed and blocked" and "the agent never got there" are
    different results, and a caller scripting this needs to tell them apart.
    """
    if status is SessionStatus.PASSED:
        return EXIT_VERIFIED
    if status is SessionStatus.UNVERIFIED:
        return EXIT_UNVERIFIED
    return EXIT_ERROR
