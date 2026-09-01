"""Shared tool machinery: the contract, argument coercion, and truncation.

Every tool returns a ``ToolResult`` and raises nothing the caller must catch.
That is a deliberate inversion of normal Python style: in P2 a tool result
becomes the next observation handed back to the model, so a refusal has to be
a *value* the loop can render, not an exception the loop has to translate.
``guarded`` performs that translation once, here, instead of in seven tools.

The exception is the primitives themselves -- ``Workspace.resolve`` and
``CommandPolicy.check`` raise, because they are also used outside the tool
layer and a silent falsy return there would be a security bug waiting for a
caller who forgets to check.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from engine.capabilities.analysis import AnalysisRun
from engine.capabilities.testenv import TestEnvironment
from engine.codeagent.limits import Limits
from engine.codeagent.policy import CommandDenied, CommandPolicy
from engine.codeagent.state import (
    CapabilityEvent,
    CommandRun,
    ExternalEvent,
    GraphQuery,
    SecurityFinding,
    ToolResult,
)
from engine.codeagent.workspace import Workspace, WorkspaceError


class ToolError(Exception):
    """A tool was called with arguments it cannot use."""


@dataclass(frozen=True)
class ToolContext:
    """Everything a tool is allowed to reach. Passing this rather than module
    globals is what lets a test construct a tiny-limit context without
    monkeypatching, and what keeps a tool from acquiring a hidden dependency.
    """

    workspace: Workspace
    policy: CommandPolicy
    limits: Limits
    # Commands that actually executed, appended by tools/shell.py and drained
    # by the session into TaskState. A sink rather than a second return value
    # because ``Tool.run`` returns exactly one ToolResult -- the loop needs one
    # shape from every tool -- while a command carries facts no ToolResult has
    # room for (its argv, whether it timed out, how long it took). A refused
    # command never reaches here: the policy check raises before the record
    # exists, so this list means "ran", not "was asked for".
    command_log: list[CommandRun] = field(default_factory=list)
    # Capability disclosures, appended by tools/skills.py and drained by the
    # session into TaskState. The same sink pattern as command_log above, and
    # for the same reason: ``Tool.run`` returns exactly one ToolResult, while a
    # disclosure carries facts no ToolResult has room for -- which skill, which
    # reference, how many characters, and the snapshot digest they came from.
    capability_log: list[CapabilityEvent] = field(default_factory=list)
    # Test-detection results, appended by tools/testenv.py. A separate sink from
    # capability_log because a detection is a structured value rather than a
    # disclosure event, and collapsing the two would mean one of them had to be
    # stringified to fit the other.
    testenv_log: list[TestEnvironment] = field(default_factory=list)
    # External-capability calls, appended by tools/docs.py. A third sink beside
    # command_log and capability_log because an external call is a different
    # kind of fact from a local disclosure: it left the machine, it cost a budget
    # nothing else spends, and it can fail in ways no local tool can.
    external_log: list[ExternalEvent] = field(default_factory=list)
    # Static-analysis runs, appended by tools/analysis.py. A sink of its own for
    # the same reason testenv_log is: an AnalysisRun is a structured value with
    # facts no ToolResult has room for -- exit status, duration, how many
    # findings existed before the reported ones were cut -- and it is advisory
    # evidence rather than a disclosure, a command ledger entry or an egress.
    analysis_log: list[AnalysisRun] = field(default_factory=list)
    # Repository-graph queries, appended by tools/graph.py. A sink of its own
    # for the same reason analysis_log is: a GraphQuery is a structured fact --
    # which operation, which target, how many results -- that ToolResult has no
    # room for, and it is evidence about what the agent looked up rather than a
    # command, a disclosure or an egress.
    graph_log: list[GraphQuery] = field(default_factory=list)
    # Security-review findings, appended by the Security Review Agent's own
    # report_finding tool (securityagent/tools/finding.py). A sink of its own
    # for the same reason graph_log is: a SecurityFinding is a structured fact
    # -- category, severity, evidence, recommendation -- ToolResult has no room
    # for, and it is advisory evidence a person reads, never a verdict input.
    security_findings_log: list[SecurityFinding] = field(default_factory=list)


class Tool(Protocol):
    name: str
    description: str

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult: ...


def truncate(text: str, limit: int) -> tuple[str, bool]:
    """Clip ``text`` to ``limit`` characters, reporting whether it was clipped.

    The marker is appended inside the returned string as well as signalled by
    the flag, because the model sees the string and the loop sees the flag.
    """
    if len(text) <= limit:
        return text, False
    kept = text[:limit]
    return f"{kept}\n... [truncated: {len(text)} chars total, showing {limit}]", True


def ok(output: str, ctx: ToolContext, *, exit_code: int | None = None) -> ToolResult:
    clipped, was_truncated = truncate(output, ctx.limits.max_tool_output_bytes)
    return ToolResult(ok=True, output=clipped, truncated=was_truncated, exit_code=exit_code)


def failed(message: str, *, exit_code: int | None = None) -> ToolResult:
    return ToolResult(ok=False, output="", truncated=False, error=message, exit_code=exit_code)


def guarded(fn: Callable[[], ToolResult]) -> ToolResult:
    """Run ``fn``, converting every expected refusal into an error result.

    ``OSError`` is included because a missing file or a permission denial is
    an ordinary observation for an agent exploring a repository, not a session
    failure. Genuinely unexpected exceptions are left to propagate -- turning
    every bug into a polite message to the model is how a broken tool gets
    retried twenty times instead of crashing loudly.
    """
    try:
        return fn()
    except (WorkspaceError, CommandDenied, ToolError) as exc:
        return failed(f"{type(exc).__name__}: {exc}")
    except OSError as exc:
        return failed(f"OSError: {exc}")


def str_arg(args: dict[str, Any], key: str, default: str | None = None) -> str:
    value = args.get(key, default)
    if value is None:
        raise ToolError(f"missing required argument {key!r}")
    if not isinstance(value, str):
        raise ToolError(f"argument {key!r} must be a string, got {type(value).__name__}")
    return value


def bool_arg(args: dict[str, Any], key: str, default: bool = False) -> bool:
    value = args.get(key, default)
    if not isinstance(value, bool):
        raise ToolError(f"argument {key!r} must be a boolean, got {type(value).__name__}")
    return value


def int_arg(args: dict[str, Any], key: str, default: int) -> int:
    value = args.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolError(f"argument {key!r} must be an integer, got {type(value).__name__}")
    return value


def argv_arg(args: dict[str, Any], key: str) -> list[str]:
    value = args.get(key)
    if isinstance(value, str):
        raise ToolError(
            f"argument {key!r} must be a list of strings, not a shell string; "
            "pass ['python', '-m', 'pytest'] rather than 'python -m pytest'"
        )
    if not isinstance(value, list) or not value:
        raise ToolError(f"argument {key!r} must be a non-empty list of strings")
    return value
