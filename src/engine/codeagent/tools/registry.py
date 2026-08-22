"""Tool registry.

Shape deliberately mirrors ``orchestrator/agents/registry.py`` -- a dict of
instances plus a ``get_*`` that raises a ValueError naming the known keys --
so the two registries read the same way. That is a convention match, not a
dependency: nothing here imports the agent registry, and the Coding Agent's
tools are unrelated to the legacy agent roles.
"""

from engine.codeagent.tools.base import Tool
from engine.codeagent.tools.fs import (
    ListFilesTool,
    ReadFileTool,
    ReplaceExactTool,
    WriteFileTool,
)
from engine.codeagent.tools.git import GitDiffTool, GitStatusTool
from engine.codeagent.tools.search import SearchFilesTool
from engine.codeagent.tools.shell import RunCommandTool, RunTestsTool

TOOL_REGISTRY: dict[str, Tool] = {
    "list_files": ListFilesTool(),
    "read_file": ReadFileTool(),
    "search_files": SearchFilesTool(),
    "write_file": WriteFileTool(),
    "replace_exact": ReplaceExactTool(),
    "run_command": RunCommandTool(),
    "run_tests": RunTestsTool(),
    "git_diff": GitDiffTool(),
    "git_status": GitStatusTool(),
}


def get_tool(name: str) -> Tool:
    try:
        return TOOL_REGISTRY[name]
    except KeyError:
        raise ValueError(
            f"Unknown tool: {name!r}. Registered tools: {sorted(TOOL_REGISTRY)}"
        ) from None
