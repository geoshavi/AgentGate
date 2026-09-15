"""The model-facing half of test detection: one tool, one observation.

The adapter across the capability seam, and the place the real command policy is
consulted. ``capabilities/testenv`` deliberately does not know what
``CommandPolicy`` is; it asks a callback whether an argv would be permitted, and
this module builds that callback **from the live policy object the session is
running under**.

That indirection is the point. The detector cannot hardcode "npm is refused",
because it does not know. If a later, separately reviewed phase widens the
policy, the same detector starts reporting ``executable=True`` with no change to
its code -- and until then, a JS suite is reported honestly with the policy's own
refusal quoted back.

The tool observes, and only observes. It runs no command, writes nothing, and
returns an ordinary ``ToolResult`` costing one ordinary ``max_tool_calls``. It
does not touch the Debug Agent's frozen reproduction or suite, which are settled
before any session exists.
"""

from typing import Any

from engine.capabilities.testenv import TestEnvironment, detect
from engine.codeagent.policy import CommandDenied, CommandPolicy
from engine.codeagent.state import ToolResult
from engine.codeagent.tools.base import ToolContext, guarded, ok


def policy_permits(policy: CommandPolicy):  # type: ignore[no-untyped-def]
    """Build the detector's ``permits`` callback from a real ``CommandPolicy``.

    Delegates the whole question to ``CommandPolicy.check``, which is the
    authority, rather than reading ``DEFAULT_ALLOWED_PROGRAMS`` and forming a
    second opinion. A second opinion is a second policy, and the two would drift.

    Returns None when the argv is permitted, or the policy's own refusal message
    -- quoted rather than paraphrased, so a report says exactly why.
    """

    def permits(argv: tuple[str, ...]) -> str | None:
        if not argv:
            return "no command to check"
        try:
            policy.check(list(argv))
        except CommandDenied as exc:
            return str(exc)
        return None

    return permits


class DetectTestsTool:
    """Report the workspace's test framework, and whether its suite may run."""

    name = "detect_tests"
    description = (
        "Identify the test framework this workspace uses, from its configuration "
        "files. Args: none. Reports the framework, the evidence for it, the suite "
        "command it implies, and whether that command is permitted here. Reads "
        "configuration only and runs nothing."
    )

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        """Detect, then render. Never executes, never writes.

        Takes no arguments: the workspace is already fixed for the session, and a
        root argument would only offer a way to point detection somewhere it has
        no business looking. Extra arguments are ignored rather than refused --
        unlike ``run_repro``, nothing here can be quietly narrowed by one, so a
        refusal would cost a turn to no purpose.
        """

        def _run() -> ToolResult:
            environment = detect(
                ctx.workspace.root,
                permits=policy_permits(ctx.policy),
                max_files=ctx.limits.max_testenv_files_read,
                max_bytes=ctx.limits.max_testenv_file_bytes,
            )
            ctx.testenv_log.append(environment)
            return ok(render(environment), ctx)

        return guarded(_run)


def render(environment: TestEnvironment) -> str:
    """The observation: structured facts, no file contents.

    Evidence lines name a file and a section -- ``pyproject.toml
    [tool.pytest.ini_options]`` -- never quote one. A configuration file can
    contain anything, including a path or a token, and this layer exists to bound
    what enters context rather than to widen it.
    """
    lines = [
        f"framework: {environment.framework or '(none detected)'}",
        f"confidence: {environment.confidence.value}",
        f"executable: {'true' if environment.executable else 'false'}",
        f"suite_argv: {list(environment.suite_argv)}",
        f"targeted_template: {list(environment.targeted_template)}",
    ]
    if environment.blocked_reason:
        lines.append(f"blocked_reason: {environment.blocked_reason}")
    lines.append("evidence:")
    lines += [f"  - {item}" for item in environment.evidence] or ["  (none)"]
    return "\n".join(lines)


__all__ = ["DetectTestsTool", "policy_permits", "render"]
