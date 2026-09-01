"""End-to-end composition: a reported bug in, a verified fix or a refusal out.

Wiring only. Every bound comes from ``Limits``, every safety guarantee from
``Workspace``/``CommandPolicy``, the proof from ``gate.prove``'s two exit codes,
and the verdict from ``verdict.gate`` by way of ``codeagent.verify``. This
module owns exactly one thing nothing else can: the composition of two
independent booleans into a final status.

    PASSED  iff  proof == PROVEN  AND  AgentGate == OK

Everything else -- and that includes every case where a model was confident --
is UNVERIFIED or an abort. The order below is the whole design:

    validate workspace          nothing spent if the target is unusable
    freeze repro + suite        both policy-checked before anything can edit
    reproduce                   no observed failure -> ABORTED_NO_REPRO
    diagnose                    no validated cause  -> ABORTED_NO_ROOT_CAUSE
    fix + prove                 D3's bounded loop; exit codes decide
    verify                      AgentGate, unchanged, only on a PROVEN fix
    report                      three separated categories of claim

**AgentGate runs only on a proven fix, and this is not a weakening.** ``PASSED``
already requires both, so verifying an unproven patch cannot change the run's
status -- it can only spend three judge calls to produce a verdict the report is
forbidden to act on. The blueprint (S7) puts the fix gate before AgentGate and
gives it the power to withhold a pass, never to grant one; skipping a call whose
answer is already unusable is that rule applied, not an exception to it.

**Verification is terminal.** D3 already owns the repair rounds and spends the
single shared ``max_repair_rounds`` budget against deterministic proof failures.
The blueprint is explicit that this is "one budget, not two", and a second
repair loop around AgentGate would have to hand a model edit tools with
verification prose as its brief -- weaker feedback than a failing command, and a
second fixing system the D4 instructions rule out. When AgentGate blocks a
proven fix, the run reports UNVERIFIED with the defects attached.
"""

import sqlite3
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from engine.capabilities.external.config import ExternalConfig, load_external_config
from engine.capabilities.skills import SkillBounds, SkillRoot
from engine.codeagent.app import (
    EXIT_ERROR,
    EXIT_UNVERIFIED,
    EXIT_VERIFIED,
    WorkspaceRejected,
    exit_code_for,
    validate_workspace,
)
from engine.codeagent.capabilities import CapabilityBundle, build_capabilities
from engine.codeagent.limits import Limits
from engine.codeagent.log import SessionLog
from engine.codeagent.policy import DEFAULT_POLICY, CommandPolicy
from engine.codeagent.state import Phase, SessionStatus
from engine.codeagent.verify import OK, verify_workspace
from engine.codeagent.workspace import Workspace
from engine.debugagent.fix import ProofStatus, run_fix_loop
from engine.debugagent.gate import freeze_suite
from engine.debugagent.limits import DEBUG_LIMITS
from engine.debugagent.report import (
    DebugReport,
    DebugRun,
    build_debug_report,
    render_debug_report,
)
from engine.debugagent.repro import FrozenRepro, freeze_repro, reproduce
from engine.debugagent.rootcause import diagnose
from engine.runtime.budget import BudgetController
from engine.runtime.gateway import LLMGateway
from engine.state import db

# The regression command used when the caller names none. Stated here rather
# than hidden in argparse so the report and the docs can both quote one source.
DEFAULT_SUITE_ARGV: tuple[str, ...] = ("python", "-m", "pytest", "-q")


@dataclass(frozen=True)
class DebugRunResult:
    report: DebugReport
    exit_code: int
    artifacts_dir: Path | None = None
    report_path: Path | None = None
    log_path: Path | None = None


def run_debug_task(
    *,
    task_text: str,
    workspace_path: Path,
    repro_argv: object,
    gateway: LLMGateway,
    model: str,
    judge_model: str,
    suite_argv: object = DEFAULT_SUITE_ARGV,
    provider_name: str = "anthropic",
    limits: Limits = DEBUG_LIMITS,
    policy: CommandPolicy = DEFAULT_POLICY,
    planned_budget: Decimal = Decimal("1.00"),
    max_tokens: int = 100_000,
    task_id: str | None = None,
    artifacts_root: Path | None = None,
    db_path: Path | None = None,
    clock: Callable[[], float] = time.monotonic,
    skill_roots: Sequence[SkillRoot] = (),
    skill_bounds: SkillBounds | None = None,
    detect_tests: bool = False,
    analyze: bool = False,
    graph: bool = False,
    include_builtin_skills: bool = False,
    capabilities_config: Path | None = None,
    external_config: ExternalConfig | None = None,
) -> DebugRunResult:
    """Debug one reported failure end to end.

    Raises before any model call -- ``WorkspaceRejected`` for an unusable
    workspace, ``TypeError``/``ValueError`` for a malformed or refused command --
    because those are caller errors with nothing observed to report on. Every
    other failure is already a status by the time it arrives here: a provider
    outage, an exhausted budget, a verifier exception and an unproven fix all
    return a report rather than raising, because the caller's next move is the
    same in each case and it is not "retry".
    """
    workspace = validate_workspace(workspace_path, max_files_changed=limits.max_files_changed)
    repro = freeze_repro(repro_argv)
    # Policy-checked here, while the workspace is still untouched: a suite
    # command that could never run must be refused before an edit exists, not
    # discovered after one.
    suite = freeze_suite(suite_argv, policy)

    # Capabilities are assembled AFTER both commands are frozen and before any
    # model call. The order is the whole of the guarantee: by the time a skill or
    # a detection exists, the two commands this run will be judged by are already
    # immutable, so there is no point at which either could be reached. The
    # snapshot itself happens inside build_capabilities, before any tool object
    # that could edit the workspace is constructed.
    # Same operator-owned config as the Coding Agent, and the same closed
    # default. It reaches the FIX session only -- diagnosis stays a bounded
    # no-tool call -- and it is read after both commands are already frozen.
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

    session_id = task_id or f"dbg-{uuid.uuid4().hex[:8]}"
    artifacts_dir: Path | None = None
    log_path: Path | None = None
    if artifacts_root is not None:
        artifacts_dir = Path(artifacts_root) / session_id
        log_path = artifacts_dir / "session.jsonl"

    log = SessionLog(log_path)
    budget = BudgetController(max_tokens=max_tokens, planned_budget=planned_budget)

    if db_path is None:
        run = _execute(
            task_text=task_text,
            workspace=workspace,
            repro=repro,
            suite=suite,
            gateway=gateway,
            budget=budget,
            model=model,
            judge_model=judge_model,
            session_id=session_id,
            limits=limits,
            policy=policy,
            log=log,
            clock=clock,
            run_id=None,
            conn=None,
            capabilities=capabilities,
        )
    else:
        # The same tables `engine code` writes: one row in `runs`, one row per
        # LLM call in `agent_execution_metrics` written by the Gateway itself.
        # No schema change, no new writer.
        with db.connect(Path(db_path)) as conn:
            run_id = db.create_run(conn, task_text, provider_name, model)
            run = _execute(
                task_text=task_text,
                workspace=workspace,
                repro=repro,
                suite=suite,
                gateway=gateway,
                budget=budget,
                model=model,
                judge_model=judge_model,
                session_id=session_id,
                limits=limits,
                policy=policy,
                log=log,
                clock=clock,
                run_id=run_id,
                conn=conn,
                capabilities=capabilities,
            )
            db.finish_run(
                conn,
                run_id,
                "passed" if run.status is SessionStatus.PASSED else "failed",
                # Fixing sessions, matching what `engine code` records: the
                # first attempt plus each proof-driven repair. A run that never
                # reached the fix phase made none.
                0 if run.fix is None else 1 + run.fix.repairs_used,
            )

    report = build_debug_report(run)
    report_path: Path | None = None
    if artifacts_dir is not None:
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        report_path = artifacts_dir / "report.json"
        report_path.write_text(report.to_json(), encoding="utf-8")

    return DebugRunResult(
        report=report,
        exit_code=exit_code_for(run.status),
        artifacts_dir=artifacts_dir,
        report_path=report_path,
        log_path=log_path,
    )


def _execute(
    *,
    task_text: str,
    workspace: Workspace,
    repro: FrozenRepro,
    suite: FrozenRepro,
    gateway: LLMGateway,
    budget: BudgetController,
    model: str,
    judge_model: str,
    session_id: str,
    limits: Limits,
    policy: CommandPolicy,
    log: SessionLog,
    clock: Callable[[], float],
    run_id: int | None,
    conn: sqlite3.Connection | None,
    capabilities: CapabilityBundle | None = None,
) -> DebugRun:
    """The control flow. Every early return is a refusal with zero edits after it."""
    started = clock()

    def finish(
        status: SessionStatus,
        reason: str,
        phase: Phase,
        **parts: object,
    ) -> DebugRun:
        log.emit(
            "debug_result",
            status=status.value,
            phase=phase.value,
            reason=reason,
            files_changed=workspace.changed_files,
        )
        return DebugRun(
            task_id=session_id,
            workspace=str(workspace.root),
            task_text=task_text,
            repro=repro,
            suite=suite,
            status=status,
            reason=reason,
            phase=phase,
            # The ledger, in both directions: what was read and what was
            # written are records the workspace kept, not claims anyone made.
            files_changed=workspace.changed_files,
            files_inspected=workspace.inspected_files,
            elapsed_ms=int((clock() - started) * 1000),
            tokens_spent=budget.spent_tokens,
            spend=budget.spent_amount,
            run_id=run_id,
            **parts,  # type: ignore[arg-type]
        )

    # (D) reproduce. No model has been called yet, and none will be if this
    # gate closes.
    repro_outcome = reproduce(
        repro=repro, workspace=workspace, policy=policy, limits=limits, log=log
    )
    if not repro_outcome.reproduced:
        return finish(
            SessionStatus.ABORTED_NO_REPRO,
            repro_outcome.reason,
            Phase.REPRODUCING,
            repro_outcome=repro_outcome,
        )
    assert repro_outcome.evidence is not None  # REPRODUCED implies evidence

    # (F, G) evidence-first context and the diagnosis. build_context runs
    # inside diagnose(), reading only the files the failure itself named.
    diagnosis = diagnose(
        task_text=task_text,
        evidence=repro_outcome.evidence,
        repro=repro,
        workspace=workspace,
        gateway=gateway,
        budget=budget,
        model=model,
        task_id=session_id,
        run_id=run_id,
        conn=conn,
        limits=limits,
        policy=policy,
        log=log,
    )
    if not diagnosis.ok:
        return finish(
            SessionStatus.ABORTED_NO_ROOT_CAUSE,
            diagnosis.reason,
            Phase.DIAGNOSING,
            repro_outcome=repro_outcome,
            diagnosis=diagnosis,
        )
    assert diagnosis.root_cause is not None  # ok implies a validated cause

    # (I) the only phase permitted to edit, and the only one that can prove.
    fix = run_fix_loop(
        task_text=task_text,
        evidence=repro_outcome.evidence,
        root_cause=diagnosis.root_cause,
        repro=repro,
        suite_argv=suite.as_list(),
        workspace=workspace,
        gateway=gateway,
        budget=budget,
        model=model,
        task_id=session_id,
        run_id=run_id,
        conn=conn,
        limits=limits,
        policy=policy,
        log=log,
        # Diagnosis (D2) deliberately does NOT receive these: it is a single
        # bounded evidence-first call with no tool loop, so a catalogue there
        # would inflate every diagnosis prompt for a capability the phase
        # cannot use.
        capabilities=capabilities,
    )
    if fix.status is ProofStatus.ABORTED:
        return finish(
            fix.session_status,
            fix.reason,
            Phase.EDITING,
            repro_outcome=repro_outcome,
            diagnosis=diagnosis,
            fix=fix,
        )

    # (J) an unproven fix cannot become PASSED however AgentGate votes, so the
    # judges are not called. See the module docstring.
    if not fix.proven:
        return finish(
            SessionStatus.UNVERIFIED,
            f"the fix was not proven, so AgentGate verification was not run: {fix.reason}",
            Phase.TESTING,
            repro_outcome=repro_outcome,
            diagnosis=diagnosis,
            fix=fix,
        )

    # (K) AgentGate, unchanged: the same caller-side seam `engine code` uses,
    # which calls verification.pipeline.run_verification with its own signature
    # and reads verdict.gate's answer without reinterpreting it.
    verification = verify_workspace(
        workspace=workspace,
        task_text=_verification_task(task_text, repro, suite),
        gateway=gateway,
        budget=budget,
        judge_model=judge_model,
        task_id=session_id,
        run_id=run_id,
        conn=conn,
        limits=limits,
        changed_files=fix.files_changed,
        log=log,
    )

    # (L) the composition. Both booleans, or nothing.
    passed = verification.status == OK and fix.proven
    return finish(
        SessionStatus.PASSED if passed else SessionStatus.UNVERIFIED,
        (
            "the reproduction passes, the regression suite is green, and AgentGate verified "
            "the change"
            if passed
            else verification.reason
        ),
        Phase.DONE if passed else Phase.VERIFYING,
        repro_outcome=repro_outcome,
        diagnosis=diagnosis,
        fix=fix,
        verification=verification,
    )


def _verification_task(task_text: str, repro: FrozenRepro, suite: FrozenRepro) -> str:
    """What the judges are told the change was for.

    The reported bug plus the two frozen commands, and nothing else. The root
    cause is deliberately withheld: handing three judges the fixing agent's own
    explanation invites them to review the explanation instead of the diff, and
    AgentGate's job is to look at the code with fresh eyes.
    """
    return (
        f"Debug task -- fix a reported failure.\n\n"
        f"REPORTED BUG\n{task_text.strip()}\n\n"
        f"REPRODUCTION COMMAND\n{repro.display()}\n"
        f"REGRESSION SUITE\n{suite.display()}"
    )


__all__ = [
    "DEFAULT_SUITE_ARGV",
    "EXIT_ERROR",
    "EXIT_UNVERIFIED",
    "EXIT_VERIFIED",
    "DebugRunResult",
    "WorkspaceRejected",
    "build_debug_report",
    "exit_code_for",
    "render_debug_report",
    "run_debug_task",
    "validate_workspace",
]
