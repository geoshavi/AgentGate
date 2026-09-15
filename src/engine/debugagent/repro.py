"""The reproduction gate: the Debug Agent's precondition for touching code.

One rule, and every branch here exists to enforce it:

    **No edit without an observed failure.**

A reproduction command that passes, times out, is refused by policy, or cannot
run at all produces no evidence, and a fix made against no evidence is an
unfalsifiable guess. All four cases land on ``ABORTED_NO_REPRO`` -- a terminal
status reached *before* the agent is constructed, let alone allowed to write.

This mirrors a decision ``codeagent/verify.py`` already made: when the snapshot
is too large to verify honestly it declines rather than verifying a truncated
program, because a verdict on evidence that does not exist is worse than no
verdict at all. Same shape, one phase earlier.

**Nothing here can call a model.** The signature takes no gateway, no budget and
no connection, so D1 cannot spend money or reach a provider even by mistake. The
command runs through ``tools/shell.run_argv`` -- the codebase's single
subprocess call site -- so the reproduction inherits the argv allowlist, the
forced working directory, the timeout and the scrubbed environment without this
module reimplementing any of them.
"""

from dataclasses import dataclass
from enum import Enum

from engine.codeagent.limits import DEFAULT_LIMITS, Limits
from engine.codeagent.log import SessionLog
from engine.codeagent.policy import DEFAULT_POLICY, CommandDenied, CommandPolicy
from engine.codeagent.state import SessionStatus
from engine.codeagent.tools.base import ToolContext
from engine.codeagent.tools.shell import run_argv
from engine.codeagent.workspace import Workspace
from engine.debugagent.evidence import FailureEvidence, build_evidence


class ReproStatus(str, Enum):
    """Why the gate opened or closed.

    Only ``REPRODUCED`` opens it. The other four are distinct because they need
    different messages to a human -- collapsing them into one "failed" would
    make a missing pytest indistinguishable from a bug that no longer exists.
    """

    REPRODUCED = "REPRODUCED"
    NOT_REPRODUCED = "NOT_REPRODUCED"  # the command passed: no failure to debug
    DENIED = "DENIED"  # refused by the command policy
    TIMED_OUT = "TIMED_OUT"
    UNAVAILABLE = "UNAVAILABLE"  # the program is not installed


@dataclass(frozen=True)
class FrozenRepro:
    """The reproduction command, immutable for the life of the run.

    Held as a tuple and handed out only as fresh lists, so neither a caller nor
    a later tool can narrow the command, drop a failing test id, or swap in
    something that passes. The Debug Agent's whole claim -- "this failure is
    gone" -- means nothing if the command that defines the failure can move.
    """

    argv: tuple[str, ...]

    def as_list(self) -> list[str]:
        """A fresh list every call; mutating it cannot reach the frozen argv."""
        return list(self.argv)

    def display(self) -> str:
        return " ".join(self.argv)


def freeze_repro(argv: object) -> FrozenRepro:
    """Validate a caller-supplied repro command and freeze it.

    Raises rather than returning a status: this runs at the very start of a run,
    from the CLI, where a bad argument is a usage error and not an observation
    anything downstream could act on.

    The split is the ordinary Python one. A wrong *type* is a ``TypeError`` and
    can only come from a broken caller -- argparse always yields ``list[str]``.
    An *empty* command is a ``ValueError`` because it is reachable from the
    command line, by passing ``--repro`` with nothing after it.

    Raises:
        TypeError: ``argv`` is a shell string, not a sequence, or holds a
            non-string item.
        ValueError: ``argv`` is an empty sequence.
    """
    if isinstance(argv, str):
        raise TypeError(
            "the reproduction command must be an argv list, not a shell string; "
            "pass ['python', '-m', 'pytest', '-q'] rather than 'python -m pytest -q'"
        )
    if not isinstance(argv, (list, tuple)):
        raise TypeError(
            f"the reproduction command must be a list of strings, "
            f"got {type(argv).__name__}"
        )
    if not argv:
        raise ValueError("the reproduction command must not be empty")
    if not all(isinstance(item, str) for item in argv):
        raise TypeError("every item in the reproduction command must be a string")
    return FrozenRepro(tuple(argv))


@dataclass(frozen=True)
class ReproOutcome:
    """The gate's verdict, plus whatever was observed reaching it."""

    status: ReproStatus
    reason: str
    evidence: FailureEvidence | None = None

    @property
    def reproduced(self) -> bool:
        return self.status is ReproStatus.REPRODUCED

    @property
    def terminal_status(self) -> SessionStatus | None:
        """The status the run must end on, or None to continue.

        Every non-reproduced outcome maps to the same terminal status. The
        distinction between them lives in ``status`` and ``reason``, where it
        informs a human without giving the loop a second way to proceed.
        """
        return None if self.reproduced else SessionStatus.ABORTED_NO_REPRO


def reproduce(
    *,
    repro: FrozenRepro,
    workspace: Workspace,
    policy: CommandPolicy = DEFAULT_POLICY,
    limits: Limits = DEFAULT_LIMITS,
    log: SessionLog | None = None,
) -> ReproOutcome:
    """Run the frozen reproduction command once and judge what happened.

    Never raises for a command that misbehaves -- a denial, a timeout and a
    missing program are all results. Only a broken *caller* (a non-frozen argv)
    can raise, and that happens in ``freeze_repro`` before this is reached.
    """
    sink = log if log is not None else SessionLog()
    argv = repro.as_list()
    sink.emit("repro_attempt", argv=argv)

    ctx = ToolContext(workspace=workspace, policy=policy, limits=limits)

    try:
        done = run_argv(argv, ctx, timeout_seconds=limits.repro_timeout_seconds)
    except CommandDenied as exc:
        # Refused before anything spawned, so there is no evidence to build:
        # nothing ran, and an evidence record implying otherwise would lie.
        return _closed(
            sink,
            ReproStatus.DENIED,
            f"the reproduction command was refused by policy: {repro.display()} ({exc})",
        )

    evidence = build_evidence(
        argv=argv,
        stdout=done.stdout,
        stderr=done.stderr,
        exit_code=done.exit_code,
        timed_out=done.timed_out,
        duration_ms=done.duration_ms,
        workspace=workspace,
        limits=limits,
    )

    if done.timed_out:
        return _closed(
            sink,
            ReproStatus.TIMED_OUT,
            f"the reproduction command did not finish within "
            f"{limits.repro_timeout_seconds}s: {repro.display()}",
            evidence,
        )
    if done.unavailable is not None:
        return _closed(
            sink,
            ReproStatus.UNAVAILABLE,
            f"the reproduction command could not run: {done.unavailable}",
            evidence,
        )
    if not evidence.reproduced:
        return _closed(
            sink,
            ReproStatus.NOT_REPRODUCED,
            f"the reproduction command succeeded (exit {done.exit_code}); "
            "there is no failure to debug",
            evidence,
        )

    outcome = ReproOutcome(
        status=ReproStatus.REPRODUCED,
        reason=f"failure reproduced: {evidence.summary}",
        evidence=evidence,
    )
    _log_result(sink, outcome)
    return outcome


def _closed(
    sink: SessionLog,
    status: ReproStatus,
    reason: str,
    evidence: FailureEvidence | None = None,
) -> ReproOutcome:
    outcome = ReproOutcome(status=status, reason=reason, evidence=evidence)
    _log_result(sink, outcome)
    return outcome


def _log_result(sink: SessionLog, outcome: ReproOutcome) -> None:
    terminal = outcome.terminal_status
    sink.emit(
        "repro_result",
        status=outcome.status.value,
        reproduced=outcome.reproduced,
        terminal_status=None if terminal is None else terminal.value,
        reason=outcome.reason,
        exit_code=None if outcome.evidence is None else outcome.evidence.exit_code,
    )


__all__ = [
    "FrozenRepro",
    "ReproOutcome",
    "ReproStatus",
    "freeze_repro",
    "reproduce",
]
