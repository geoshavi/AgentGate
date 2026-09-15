"""Real command execution, policy-checked and bounded.

Real means real: this module runs the process and reports what it actually
returned. There is no path here that fabricates output, and none that reports
success for a command that did not run. A denial, a timeout and a non-zero
exit are three distinct, truthful outcomes.

A non-zero exit is ``ok=True`` with the exit code attached, not ``ok=False``.
The distinction that matters to the loop is "did the tool do its job" versus
"did the command succeed" -- a failing test suite is a successful
``run_command`` and is precisely the observation the agent needs in order to
repair. ``ok=False`` is reserved for the command never having run.
"""

import subprocess
import time
from dataclasses import dataclass
from typing import Any

from engine.codeagent.policy import scrub_env
from engine.codeagent.state import CommandRun, ToolResult
from engine.codeagent.tools.base import (
    ToolContext,
    argv_arg,
    failed,
    guarded,
    truncate,
)


@dataclass(frozen=True)
class CompletedCommand:
    """One executed command, with its streams still separate.

    ``execute`` immediately combines stdout and stderr because that is the shape
    a model observation needs. The Debug Agent's evidence record needs them
    apart, so the raw form is exposed here rather than reconstructed by parsing
    the combined text -- and, more importantly, rather than by giving the Debug
    Agent a second subprocess call of its own. There is exactly one place in
    this codebase that spawns a child process, and this is it.

    ``exit_code`` is None exactly when the command produced no status:
    ``timed_out`` or ``unavailable`` says which.
    """

    argv: list[str]
    stdout: str
    stderr: str
    exit_code: int | None
    timed_out: bool
    unavailable: str | None
    duration_ms: int


def run_argv(
    argv: list[str], ctx: ToolContext, *, timeout_seconds: float | None = None
) -> CompletedCommand:
    """Policy-check and run ``argv`` inside the workspace, returning raw streams.

    Raises ``CommandDenied`` if the policy refuses -- a refusal happens before
    anything is spawned, so a denied command never becomes a CompletedCommand.
    """
    resolved = ctx.policy.check(argv)
    timeout = ctx.limits.command_timeout_seconds if timeout_seconds is None else timeout_seconds
    started = time.monotonic()

    def _elapsed() -> int:
        return int((time.monotonic() - started) * 1000)

    try:
        completed = subprocess.run(
            resolved,
            cwd=ctx.workspace.root,
            env=scrub_env(),
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return CompletedCommand(argv, "", "", None, True, None, _elapsed())
    except FileNotFoundError as exc:
        return CompletedCommand(argv, "", "", None, False, str(exc), _elapsed())

    return CompletedCommand(
        argv=argv,
        stdout=completed.stdout,
        stderr=completed.stderr,
        exit_code=completed.returncode,
        timed_out=False,
        unavailable=None,
        duration_ms=_elapsed(),
    )


def execute(argv: list[str], ctx: ToolContext) -> tuple[ToolResult, CommandRun]:
    """Policy-check and run ``argv`` inside the workspace.

    Returns the tool result and a ``CommandRun`` record for the session state.
    Raises ``CommandDenied`` if the policy refuses -- callers reach this
    through ``guarded``, which turns that into an error result.
    """
    done = run_argv(argv, ctx)
    timeout = ctx.limits.command_timeout_seconds

    if done.timed_out:
        record = CommandRun(
            argv=argv, exit_code=None, timed_out=True, duration_ms=done.duration_ms
        )
        return (
            failed(f"command timed out after {timeout}s: {' '.join(argv)}"),
            record,
        )
    if done.unavailable is not None:
        record = CommandRun(
            argv=argv, exit_code=None, timed_out=False, duration_ms=done.duration_ms
        )
        return failed(f"program not found: {done.unavailable}"), record

    # mypy: neither timed out nor unavailable, so a status exists.
    assert done.exit_code is not None
    elapsed = done.duration_ms
    body = _combine(done.stdout, done.stderr, done.exit_code)
    clipped, was_truncated = truncate(body, ctx.limits.max_tool_output_bytes)
    record = CommandRun(
        argv=argv,
        exit_code=done.exit_code,
        timed_out=False,
        duration_ms=elapsed,
        output_truncated=was_truncated,
    )
    result = ToolResult(
        ok=True,
        output=clipped,
        truncated=was_truncated,
        exit_code=done.exit_code,
    )
    return result, record


def _combine(stdout: str, stderr: str, returncode: int) -> str:
    parts = [f"exit {returncode}"]
    if stdout.strip():
        parts.append(f"--- stdout ---\n{stdout.rstrip()}")
    if stderr.strip():
        parts.append(f"--- stderr ---\n{stderr.rstrip()}")
    if len(parts) == 1:
        # Same reasoning as verification/automated.py: a command that exits
        # without writing a byte must not be collapsed to something that reads
        # as success. The exit status is the only information there is.
        parts.append("(no output)")
    return "\n".join(parts)


class RunCommandTool:
    name = "run_command"
    description = (
        "Run an allowlisted command inside the workspace. Args: argv (list of "
        "strings, e.g. ['python', '-m', 'pytest', '-q'])."
    )

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        def _run() -> ToolResult:
            argv = argv_arg(args, "argv")
            result, record = execute(argv, ctx)
            ctx.command_log.append(record)
            return result

        return guarded(_run)


class RunTestsTool:
    name = "run_tests"
    description = "Run the workspace test suite (pytest -q). Args: none."

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        def _run() -> ToolResult:
            result, record = execute(["python", "-m", "pytest", "-q"], ctx)
            ctx.command_log.append(record)
            return result

        return guarded(_run)


__all__ = ["CompletedCommand", "RunCommandTool", "RunTestsTool", "execute", "run_argv"]
