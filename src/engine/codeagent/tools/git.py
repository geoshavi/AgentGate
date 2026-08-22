"""Read-only git inspection.

Both tools route through the same policy-checked executor as every other
command, so ``git`` here is subject to the identical subcommand allowlist. No
separate, more-trusting path to git exists -- that is the point: a second
executor is how a write subcommand eventually slips through.
"""

from typing import Any

from engine.codeagent.state import ToolResult
from engine.codeagent.tools.base import ToolContext, bool_arg, guarded
from engine.codeagent.tools.shell import execute


class GitDiffTool:
    name = "git_diff"
    description = "Show the working-tree diff. Args: stat (default false)."

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        def _run() -> ToolResult:
            argv = ["git", "diff"]
            if bool_arg(args, "stat", False):
                argv.append("--stat")
            result, _record = execute(argv, ctx)
            return result

        return guarded(_run)


class GitStatusTool:
    name = "git_status"
    description = "Show the working-tree status in porcelain form. Args: none."

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        def _run() -> ToolResult:
            result, _record = execute(["git", "status", "--porcelain"], ctx)
            return result

        return guarded(_run)
