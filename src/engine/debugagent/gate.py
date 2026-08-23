"""The proof gate: two commands that decide whether a fix worked.

Deterministic, model-free, and the only thing in D3 permitted to say a fix is
proven. The agent's final message is a claim about effort; these exit codes are
the claim about correctness.

Two commands, in this order:

1. **The frozen reproduction.** Must now exit 0. If it does not, the bug the
   run was sent to fix is still there, and nothing else matters -- the suite is
   not run at all, because its answer could not change the verdict and the
   clearer feedback is "the reproduction still fails".

2. **The full regression suite.** Must exit 0. This is what catches the classic
   debugging failure: the targeted test goes green and a neighbour breaks. A
   targeted-only gate would report that as success.

Both frozen before the fixing session starts. The suite argv is policy-checked
at freeze time, so a suite command that could never run is refused while nothing
has been edited -- not discovered after the workspace has been changed.
"""

from dataclasses import dataclass

from engine.codeagent.limits import DEFAULT_LIMITS, Limits
from engine.codeagent.policy import DEFAULT_POLICY, CommandDenied, CommandPolicy
from engine.codeagent.state import CommandRun
from engine.codeagent.tools.base import ToolContext
from engine.codeagent.tools.shell import execute
from engine.codeagent.workspace import Workspace
from engine.debugagent.repro import FrozenRepro

# Bounds the failure output pasted back into a repair prompt. Not a Limits
# field: it shapes one message, not what the agent may do.
MAX_FEEDBACK_CHARS = 2_000


@dataclass(frozen=True)
class ProofResult:
    """What the two commands said, and what that means.

    ``suite_after`` is None when the reproduction failed -- the suite genuinely
    did not run, and a fabricated record would imply it had.
    """

    proven: bool
    stage: str  # REPRO | SUITE | PROVEN
    reason: str
    repro_after: CommandRun | None = None
    suite_after: CommandRun | None = None
    repro_output: str = ""
    suite_output: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "proven": self.proven,
            "stage": self.stage,
            "reason": self.reason,
            "repro_after": None if self.repro_after is None else _command_dict(self.repro_after),
            "suite_after": None if self.suite_after is None else _command_dict(self.suite_after),
        }


def _command_dict(record: CommandRun) -> dict[str, object]:
    return {
        "argv": list(record.argv),
        "exit_code": record.exit_code,
        "timed_out": record.timed_out,
        "duration_ms": record.duration_ms,
    }


def freeze_suite(argv: object, policy: CommandPolicy = DEFAULT_POLICY) -> FrozenRepro:
    """Validate and freeze the regression command.

    Reuses ``FrozenRepro`` rather than adding a second freeze type: the property
    wanted is identical -- an argv list that is validated once and cannot be
    replaced afterwards -- and a parallel class would be two things to keep in
    step for no behavioural gain.

    Policy-checked here, before the fixing session exists, so ``git push`` as a
    "regression suite" is refused while the workspace is still untouched.

    Raises:
        TypeError: not a list of strings.
        ValueError: empty, or refused by the command policy.
    """
    from engine.debugagent.repro import freeze_repro

    frozen = freeze_repro(argv)
    try:
        policy.check(frozen.as_list())
    except CommandDenied as exc:
        raise ValueError(f"the regression command is not allowed: {frozen.display()} ({exc})") from exc
    return frozen


def prove(
    *,
    repro: FrozenRepro,
    suite: FrozenRepro,
    workspace: Workspace,
    policy: CommandPolicy = DEFAULT_POLICY,
    limits: Limits = DEFAULT_LIMITS,
) -> ProofResult:
    """Run the two proof commands and decide. Never edits, never raises."""
    ctx = ToolContext(workspace=workspace, policy=policy, limits=limits)

    repro_result, repro_record = execute(repro.as_list(), ctx)
    if repro_record.exit_code != 0:
        return ProofResult(
            proven=False,
            stage="REPRO",
            reason=(
                f"the reproduction command still fails after the change "
                f"(exit {repro_record.exit_code})"
            ),
            repro_after=repro_record,
            repro_output=repro_result.output[-MAX_FEEDBACK_CHARS:],
        )

    suite_result, suite_record = execute(suite.as_list(), ctx)
    if suite_record.exit_code != 0:
        return ProofResult(
            proven=False,
            stage="SUITE",
            reason=(
                f"the reproduction now passes, but the regression suite does not "
                f"(exit {suite_record.exit_code})"
            ),
            repro_after=repro_record,
            suite_after=suite_record,
            repro_output=repro_result.output[-MAX_FEEDBACK_CHARS:],
            suite_output=suite_result.output[-MAX_FEEDBACK_CHARS:],
        )

    return ProofResult(
        proven=True,
        stage="PROVEN",
        reason="the reproduction passes and the regression suite is green",
        repro_after=repro_record,
        suite_after=suite_record,
        repro_output=repro_result.output[-MAX_FEEDBACK_CHARS:],
        suite_output=suite_result.output[-MAX_FEEDBACK_CHARS:],
    )


def render_repair_feedback(proof: ProofResult) -> str:
    """Turn a failed proof into the next round's opening context.

    Deterministic evidence, cited by command and exit code. This is better
    repair input than any prose critique: it names something the agent can
    re-run itself with ``run_repro``.
    """
    if proof.stage == "SUITE":
        return (
            "FIX NOT PROVEN -- THE SUITE BROKE\n"
            "The reproduction now passes, but the full regression suite does not. "
            "Your change fixed the reported bug and broke something else.\n"
            f"command : {' '.join(proof.suite_after.argv) if proof.suite_after else ''}\n"
            f"exit    : {proof.suite_after.exit_code if proof.suite_after else '?'}\n"
            f"--- output ---\n{proof.suite_output.strip()}\n"
            "Repair the regression without reintroducing the original bug."
        )
    return (
        "FIX NOT PROVEN -- THE BUG IS STILL THERE\n"
        "The reproduction command still fails after your change.\n"
        f"command : {' '.join(proof.repro_after.argv) if proof.repro_after else ''}\n"
        f"exit    : {proof.repro_after.exit_code if proof.repro_after else '?'}\n"
        f"--- output ---\n{proof.repro_output.strip()}\n"
        "Read the failure above and correct the fix."
    )


__all__ = ["MAX_FEEDBACK_CHARS", "ProofResult", "freeze_suite", "prove", "render_repair_feedback"]
