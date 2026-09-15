"""Bounded, read-only Python AST/import graph.

One local implementation, no dependency, evaluated against the Graphify
project (github.com/Graphify-Labs/graphify) and passed over: Graphify parses
37 languages through tree-sitter, offers Neo4j/FalkorDB backends and an
optional LLM-driven documentation pass, and ships as a ~1,600-commit external
package -- capability and dependency surface this engine's Python-only MVP has
no use for, and a network-capable code path (the LLM backend) this capability
must not have at all. ``ast`` and ``importlib``-shaped resolution, already in
the standard library, cover ``find_symbol``, ``find_references``,
``find_dependents``, ``related_files`` and ``show_module_graph`` completely.

The shape is the point, same as ``capabilities/analysis``: ``build_graph`` and
``find_references`` do the one deterministic scan this capability admits, and
``models`` fixes what a result is allowed to claim -- structure, never a
verdict.

**Nothing here executes anything.** No subprocess, no import of the scanned
code, no mutation. ``ast.parse`` over text already read, screened by the same
``capabilities/paths.py`` every other local reader uses.

A leaf, like the rest of ``capabilities/`` (architecture Rule H): no agent
package, no ``Tool``, no ``Workspace``, no ``CommandPolicy``, no provider SDK.
"""

from engine.capabilities.graph.build import (
    MAX_GRAPH_FILE_BYTES,
    MAX_GRAPH_FILES_SCANNED,
    MAX_REFERENCE_HITS,
    build_graph,
    find_references,
)
from engine.capabilities.graph.models import ImportEdge, RepoGraph, SymbolDef

__all__ = [
    "MAX_GRAPH_FILES_SCANNED",
    "MAX_GRAPH_FILE_BYTES",
    "MAX_REFERENCE_HITS",
    "ImportEdge",
    "RepoGraph",
    "SymbolDef",
    "build_graph",
    "find_references",
]
