"""Doc-scoped write tools: ``write_file`` and ``replace_exact``, narrowed.

**No second write path.** Both classes hold a real ``WriteFileTool``/
``ReplaceExactTool`` instance and delegate to it for every actual byte
written -- the mass-deletion guard, the newline convention, ``max_write_bytes``,
and ``Workspace.resolve``'s own path safety all still apply exactly as they do
for the Coding Agent. What this module adds is one refusal *before* that: a
path whose filename does not look like documentation (``scope.is_doc_path``)
is rejected without ever reaching the real tool, so "this agent writes only
docs" is a property the tool enforces, not an instruction a model could
ignore.

Registered under the same names (``write_file``, ``replace_exact``) the
Coding Agent uses, deliberately: a scoped write is still a write, and giving
it a different name would only make the model re-learn a tool it already
knows for no reason. The description states the scope explicitly, so a
refusal is never a surprise.
"""

from typing import Any

from engine.codeagent.state import ToolResult
from engine.codeagent.tools.base import ToolContext, failed
from engine.codeagent.tools.fs import ReplaceExactTool, WriteFileTool
from engine.docsagent.scope import is_doc_path

_SCOPE_NOTE = (
    "Documentation-scoped: allowed only for .md/.rst/.txt files, "
    "README/CHANGELOG/LICENSE/NOTICE/AUTHORS/CONTRIBUTING/HANDOVER (any or no "
    "extension), and .env.example. A path outside this scope is refused."
)


def _refuse_out_of_scope(rel: object) -> ToolResult:
    return failed(
        f"{rel!r} is not a documentation or config-doc path, so this agent cannot "
        f"write it. {_SCOPE_NOTE}"
    )


class DocWriteFileTool:
    """``write_file``, refusing any path that is not a documentation file."""

    name = "write_file"
    description = (
        "Create a workspace-relative documentation file. Args: path, content, "
        f"overwrite (required to replace an existing file). {_SCOPE_NOTE}"
    )

    def __init__(self) -> None:
        self._inner = WriteFileTool()

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        rel = args.get("path")
        if not isinstance(rel, str) or not is_doc_path(rel):
            return _refuse_out_of_scope(rel)
        return self._inner.run(args, ctx)


class DocReplaceExactTool:
    """``replace_exact``, refusing any path that is not a documentation file."""

    name = "replace_exact"
    description = (
        "Replace an exact anchor in a workspace-relative documentation file. "
        f"The anchor must occur exactly once. Args: path, find, replace. {_SCOPE_NOTE}"
    )

    def __init__(self) -> None:
        self._inner = ReplaceExactTool()

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        rel = args.get("path")
        if not isinstance(rel, str) or not is_doc_path(rel):
            return _refuse_out_of_scope(rel)
        return self._inner.run(args, ctx)


__all__ = ["DocReplaceExactTool", "DocWriteFileTool"]
