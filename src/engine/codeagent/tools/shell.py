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


def execute(argv: list[str], ctx: ToolContext) -> tuple[ToolResult, CommandRun]:
    """Policy-check and run ``argv`` inside the workspace.

    Returns the tool result and a ``CommandRun`` record for the session state.
    Raises ``CommandDenied`` if the policy refuses -- callers reach this
    through ``guarded``, which turns that into an error result.
    """
    resolved = ctx.policy.check(argv)
    started = time.monotonic()
    timeout = ctx.limits.command_timeout_seconds

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
        elapsed = int((time.monotonic() - started) * 1000)
        record = CommandRun(argv=argv, exit_code=None, timed_out=True, duration_ms=elapsed)
        return (
            failed(f"command timed out after {timeout}s: {' '.join(argv)}"),
            record,
        )
    except FileNotFoundError as exc:
        elapsed = int((time.monotonic() - started) * 1000)
        record = CommandRun(argv=argv, exit_code=None, timed_out=False, duration_ms=elapsed)
        return failed(f"program not found: {exc}"), record

    elapsed = int((time.monotonic() - started) * 1000)
    body = _combine(completed.stdout, completed.stderr, completed.returncode)
    clipped, was_truncated = truncate(body, ctx.limits.max_tool_output_bytes)
    record = CommandRun(
        argv=argv,
        exit_code=completed.returncode,
        timed_out=False,
        duration_ms=elapsed,
        output_truncated=was_truncated,
    )
    result = ToolResult(
        ok=True,
        output=clipped,
        truncated=was_truncated,
        exit_code=completed.returncode,
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


__all__ = ["RunCommandTool", "RunTestsTool", "execute"]
