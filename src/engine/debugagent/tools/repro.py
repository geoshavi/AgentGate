"""The frozen reproduction tool.

One tool, and its entire design is a refusal: **it takes no arguments.**

An agent that could pass its own argv could quietly narrow the failing test
until it passed -- deselect a case, target a different node id, swap pytest for
something that exits 0 -- and the report would read as a fix. So the command is
captured at construction and held by the tool.

Supplying an argument is **refused**, not ignored. Those are different things:
ignoring would leave a model believing it had narrowed the reproduction while
the tool kept reporting exit 0 for something else entirely, which is a silent
failure of exactly the kind this phase exists to prevent. A refusal is a normal
tool error the session hands straight back, and the model can correct itself.

Execution goes through ``tools/shell.execute`` -- the same policy check, the
same timeout, the same scrubbed environment, the same ``CommandRun`` record as
every other command in the codebase. This module adds a constraint; it does not
add an execution path.
"""

from typing import Any

from engine.codeagent.state import ToolResult
from engine.codeagent.tools.base import ToolContext, failed, guarded
from engine.codeagent.tools.shell import execute
from engine.debugagent.repro import FrozenRepro


class RunReproTool:
    """Re-run the reproduction command that defined the bug. Nothing else."""

    name = "run_repro"
    description = (
        "Re-run the frozen reproduction command that defines this bug. Takes NO "
        "arguments -- the command cannot be changed, narrowed, or replaced, and "
        "passing any argument is an error rather than being ignored. Exit 0 "
        "means the reported failure is gone."
    )

    def __init__(self, repro: FrozenRepro) -> None:
        self._repro = repro

    @property
    def argv(self) -> list[str]:
        """The frozen command, as a fresh list. For reporting, not for editing."""
        return self._repro.as_list()

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        """Run the frozen command, or refuse if any argument was supplied.

        Refusing rather than ignoring is the important part. Silently discarding
        an argv would let a model spend the rest of the session believing it had
        narrowed the reproduction and been told it passed -- the tool would keep
        reporting exit 0 for a command the model did not think it was running.
        An explicit error is a usable observation: it names the fault, and the
        session's ordinary tool-error path hands it straight back.

        The frozen command is never touched on this path. Nothing runs at all.
        """
        if args:
            supplied = ", ".join(sorted(repr(key) for key in args))
            return failed(
                f"run_repro takes no arguments and received {supplied}. The "
                "reproduction command is frozen for this run and cannot be "
                "narrowed, redirected, or replaced. Call it again with no "
                f"arguments to run: {self._repro.display()}"
            )

        def _run() -> ToolResult:
            result, record = execute(self._repro.as_list(), ctx)
            ctx.command_log.append(record)
            return result

        return guarded(_run)


__all__ = ["RunReproTool"]
