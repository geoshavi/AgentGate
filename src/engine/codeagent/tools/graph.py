"""The model-facing half of the repository graph: one tool, five read-only
queries over one deterministic scan.

The adapter across the capability seam, matching ``tools/analysis.py`` and
``tools/testenv.py``: ``capabilities/graph`` builds a value and knows nothing
about ``Tool``, ``Workspace`` or ``CommandPolicy``; this module resolves a
model-supplied path through ``Workspace.resolve`` -- the same guard every
other path-taking tool uses -- and renders a bounded observation.

**The model chooses an operation, a symbol name, a path, or a depth. It
chooses nothing else.** There is no argument for a root, a scan mode, a file
filter or a resolver, and supplying one is a refusal rather than an ignored
extra.

**Read-only, structural. Every result is bounded twice**: the number of
matches a query may render (``Limits.max_graph_results``) and the characters
the tool may return (``Limits.max_tool_output_bytes``), the same two-stage
bound ``tools/analysis.py`` applies to findings.

**Evidence, never a verdict.** This module holds no rubric, no severity, no
reference to ``verification/``, and never changes AgentGate's verdict, judge
or benchmark semantics. The Debug Agent's frozen reproduction and suite are
settled before any session exists; diagnosis stays a bounded no-tool call and
gains nothing from this capability, which reaches the fix session only.
"""

from typing import Any

from engine.capabilities.graph import RepoGraph, build_graph, find_references
from engine.codeagent.state import GraphQuery, ToolResult
from engine.codeagent.tools.base import ToolContext, guarded, ok, str_arg

OP_FIND_SYMBOL = "find_symbol"
OP_FIND_REFERENCES = "find_references"
OP_FIND_DEPENDENTS = "find_dependents"
OP_RELATED_FILES = "related_files"
OP_SHOW_MODULE_GRAPH = "show_module_graph"

OPS = (
    OP_FIND_SYMBOL,
    OP_FIND_REFERENCES,
    OP_FIND_DEPENDENTS,
    OP_RELATED_FILES,
    OP_SHOW_MODULE_GRAPH,
)

# Everything the model may name.
ALLOWED_ARGS = frozenset({"op", "name", "path", "depth"})
MAX_DEPTH = 2


class RepoGraphTool:
    """Query a deterministic AST/import scan of the workspace's Python source."""

    name = "repo_graph"
    description = (
        "Read-only repository context graph, built from a local Python AST/import "
        'scan -- no network, nothing executed. Args: {"op": "<one of '
        + ", ".join(OPS)
        + '>", "name": "<symbol name, for find_symbol/find_references>", '
        '"path": "<workspace-relative file, for find_dependents/related_files/'
        'show_module_graph>", "depth": <1 or 2, for show_module_graph, default 1>}. '
        "find_symbol locates a function/class/method definition by name. "
        "find_references finds where a bare identifier is used -- name-based, not "
        "type-resolved, so it can match an unrelated symbol of the same name. "
        "find_dependents lists modules that import the given path. related_files "
        "lists a module's direct import neighborhood (what it imports and what "
        "imports it). show_module_graph summarises one module's edges, or the "
        "whole scan if path is omitted. Every result is bounded; use this before "
        "reading files to find what to read, not as a substitute for reading them. "
        "No other arguments are accepted."
    )

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        def _run() -> ToolResult:
            unknown = sorted(set(args) - ALLOWED_ARGS)
            if unknown:
                return self._refuse(
                    ctx,
                    "",
                    f"unexpected argument(s) {unknown}; repo_graph accepts only "
                    f"{sorted(ALLOWED_ARGS)}.",
                )

            op = args.get("op")
            if op not in OPS:
                return self._refuse(ctx, "", f"op must be one of {list(OPS)}, got {op!r}")

            max_results = ctx.limits.max_graph_results
            if op == OP_FIND_SYMBOL:
                return self._find_symbol(ctx, str_arg(args, "name"), max_results)
            if op == OP_FIND_REFERENCES:
                return self._find_references(ctx, str_arg(args, "name"), max_results)

            if op == OP_SHOW_MODULE_GRAPH:
                # The only op where "path" is optional -- omitted, it means
                # "the whole scan" rather than one module's neighborhood.
                rel_path = self._relative_path(ctx, str_arg(args, "path", ""))
                return self._show_module_graph(
                    ctx, rel_path, _depth_arg(args), max_results
                )

            # Workspace.resolve raises WorkspaceError for a path that escapes
            # the root or names a credential-shaped component; guarded() turns
            # that into an ordinary failed ToolResult, the same convention
            # every other path-taking tool (tools/fs.py) follows.
            rel_path = self._relative_path(ctx, str_arg(args, "path"))
            if op == OP_FIND_DEPENDENTS:
                return self._find_dependents(ctx, rel_path, max_results)
            return self._related_files(ctx, rel_path, max_results)

        return guarded(_run)

    # -- operations -----------------------------------------------------

    def _find_symbol(self, ctx: ToolContext, name: str, max_results: int) -> ToolResult:
        graph = self._graph(ctx)
        matches = graph.symbols.get(name, ())
        shown = matches[:max_results]
        lines = [f"op: {OP_FIND_SYMBOL}", f"name: {name}", f"matches: {len(matches)}"]
        if len(matches) > len(shown):
            lines.append(f"showing: {len(shown)} of {len(matches)}")
        lines.append("results:")
        lines += [f"  - {m.kind} {m.qualname} {m.path}:{m.line}" for m in shown] or ["  (none)"]
        return self._record(ctx, OP_FIND_SYMBOL, name, len(shown), len(matches), "\n".join(lines))

    def _find_references(self, ctx: ToolContext, name: str, max_results: int) -> ToolResult:
        hits = find_references(
            ctx.workspace.root,
            name,
            max_files=ctx.limits.max_graph_files_scanned,
            max_file_bytes=ctx.limits.max_graph_file_bytes,
            max_results=max_results,
        )
        lines = [
            f"op: {OP_FIND_REFERENCES}",
            f"name: {name}",
            (
                "note: name-based match, not type-resolved -- may include an "
                "unrelated symbol of the same name"
            ),
            f"matches: {len(hits)}",
            "results:",
        ]
        lines += [f"  - {path}:{line}" for path, line in hits] or ["  (none)"]
        return self._record(
            ctx, OP_FIND_REFERENCES, name, len(hits), len(hits), "\n".join(lines)
        )

    def _find_dependents(self, ctx: ToolContext, rel_path: str, max_results: int) -> ToolResult:
        graph = self._graph(ctx)
        deps = graph.dependents.get(rel_path, ())
        shown = deps[:max_results]
        lines = [f"op: {OP_FIND_DEPENDENTS}", f"path: {rel_path}", f"dependents: {len(deps)}"]
        if len(deps) > len(shown):
            lines.append(f"showing: {len(shown)} of {len(deps)}")
        lines.append("results:")
        lines += [f"  - {p}" for p in shown] or ["  (none)"]
        return self._record(
            ctx, OP_FIND_DEPENDENTS, rel_path, len(shown), len(deps), "\n".join(lines)
        )

    def _related_files(self, ctx: ToolContext, rel_path: str, max_results: int) -> ToolResult:
        graph = self._graph(ctx)
        imports = graph.imports.get(rel_path)
        depends_on = imports.resolved if imports is not None else ()
        depended_on_by = graph.dependents.get(rel_path, ())
        related = sorted({*depends_on, *depended_on_by} - {rel_path})
        shown = related[:max_results]
        lines = [f"op: {OP_RELATED_FILES}", f"path: {rel_path}", f"related: {len(related)}"]
        if len(related) > len(shown):
            lines.append(f"showing: {len(shown)} of {len(related)}")
        lines.append("results:")
        lines += [f"  - {p}" for p in shown] or ["  (none)"]
        return self._record(
            ctx, OP_RELATED_FILES, rel_path, len(shown), len(related), "\n".join(lines)
        )

    def _show_module_graph(
        self, ctx: ToolContext, rel_path: str, depth: int, max_results: int
    ) -> ToolResult:
        graph = self._graph(ctx)
        if not rel_path:
            lines = [
                f"op: {OP_SHOW_MODULE_GRAPH}",
                "path: (whole scan)",
                f"modules_scanned: {len(graph.modules)}",
                f"symbols_indexed: {sum(len(v) for v in graph.symbols.values())}",
                f"parse_errors: {len(graph.errors)}",
                f"files_skipped_bound: {'true' if graph.files_skipped_bound else 'false'}",
            ]
            hubs = sorted(graph.dependents.items(), key=lambda kv: (-len(kv[1]), kv[0]))
            shown_hubs = hubs[:max_results]
            lines.append("most-depended-on modules:")
            lines += [
                f"  - {p} ({len(deps)} dependents)" for p, deps in shown_hubs
            ] or ["  (none)"]
            return self._record(
                ctx, OP_SHOW_MODULE_GRAPH, "", len(shown_hubs), len(hubs), "\n".join(lines)
            )

        seen = {rel_path}
        frontier = {rel_path}
        for _ in range(depth):
            nxt: set[str] = set()
            for p in frontier:
                imports = graph.imports.get(p)
                nxt |= set(imports.resolved) if imports is not None else set()
                nxt |= set(graph.dependents.get(p, ()))
            nxt -= seen
            seen |= nxt
            frontier = nxt

        neighborhood = sorted(seen - {rel_path})
        shown = neighborhood[:max_results]
        imports = graph.imports.get(rel_path)
        lines = [
            f"op: {OP_SHOW_MODULE_GRAPH}",
            f"path: {rel_path}",
            f"depth: {depth}",
            f"imports: {list(imports.resolved) if imports is not None else []}",
            f"imported_by: {list(graph.dependents.get(rel_path, ()))}",
            f"neighborhood: {len(neighborhood)}",
        ]
        if len(neighborhood) > len(shown):
            lines.append(f"showing: {len(shown)} of {len(neighborhood)}")
        lines.append("results:")
        lines += [f"  - {p}" for p in shown] or ["  (none)"]
        return self._record(
            ctx, OP_SHOW_MODULE_GRAPH, rel_path, len(shown), len(neighborhood), "\n".join(lines)
        )

    # -- shared -----------------------------------------------------------

    def _graph(self, ctx: ToolContext) -> RepoGraph:
        """One fresh scan per call, like ``detect_tests``: cheap, bounded, and
        always current with whatever the agent has already edited this run."""
        return build_graph(
            ctx.workspace.root,
            max_files=ctx.limits.max_graph_files_scanned,
            max_file_bytes=ctx.limits.max_graph_file_bytes,
        )

    def _relative_path(self, ctx: ToolContext, path: str) -> str:
        if not path:
            return ""
        resolved = ctx.workspace.resolve(path)
        return ctx.workspace.relative(resolved)

    def _record(
        self,
        ctx: ToolContext,
        op: str,
        target: str,
        shown: int,
        total: int,
        text: str,
    ) -> ToolResult:
        ctx.graph_log.append(
            GraphQuery(op=op, target=target, result_count=shown, truncated=total > shown)
        )
        return ok(text, ctx)

    def _refuse(self, ctx: ToolContext, op: str, reason: str) -> ToolResult:
        ctx.graph_log.append(GraphQuery(op=op or "?", error=reason))
        return ok(f"error: {reason}", ctx)


def _depth_arg(args: dict[str, Any]) -> int:
    value = args.get("depth", 1)
    if isinstance(value, bool) or not isinstance(value, int):
        return 1
    return max(1, min(value, MAX_DEPTH))


__all__ = ["ALLOWED_ARGS", "MAX_DEPTH", "OPS", "RepoGraphTool"]
