"""Deterministic, read-only Python AST/import scan of a workspace.

The contract matches ``capabilities/testenv/detect.py``: the same tree
produces the same ``RepoGraph``, every time. A sorted directory walk, bounded
reads, and a fixed two-pass structure (definitions and the module index first,
edges second) rather than anything that could depend on filesystem iteration
order or on how much memory happened to be free.

**It never runs anything.** No subprocess, no import of the scanned code, no
mutation -- only ``ast.parse`` over text already read. Reading is bounded by
file count and by bytes per file, and every path is screened by
``capabilities/paths.py`` before it is opened, the same screen
``capabilities/testenv`` uses.

**Import resolution is module-level and deliberately shallow.** An absolute
import (``import a.b.c`` or ``from a.b import c`` with no leading dots) is
resolved to a scanned file only when its dotted name exactly matches one this
scan already indexed -- from the workspace root, or from a ``src/`` layout,
which is what this repository and most Python projects use. A relative import
(``from . import x``) is recorded as an unresolved external reference rather
than walked through package semantics: nothing in this repository uses one,
and getting that resolution wrong would be a worse answer than an honestly
unresolved one. Both are choices proportionate to what this capability is for
-- reducing reads before a real edit -- not a claim of import-system fidelity.

**References are name-based, not scope- or type-resolved.** ``find_references``
matches a bare identifier against every ``Name``/``Attribute`` load in the
repository. Two unrelated functions named ``run`` are indistinguishable to it.
That is a stated limitation, not a bug: real symbol resolution needs a type
checker, and this capability's job is to be right about what it can be right
about -- syntax and import graphs -- and honest about what it approximates.
"""

import ast
import os
from pathlib import Path, PurePosixPath

from engine.capabilities.graph.models import ImportEdge, RepoGraph, SymbolDef
from engine.capabilities.paths import contained, is_denied_name, is_noise_dir

# Approved bounds, mirroring capabilities/testenv/detect.py's ceilings. Large
# enough for a real project's Python source, small enough that a pathological
# tree cannot turn a bounded tool call into an unbounded scan.
MAX_GRAPH_FILES_SCANNED = 3000
MAX_GRAPH_FILE_BYTES = 300_000
MAX_REFERENCE_HITS = 200

_DEF_KIND_FUNCTION = "function"
_DEF_KIND_CLASS = "class"
_DEF_KIND_METHOD = "method"


def build_graph(
    root: Path,
    *,
    max_files: int = MAX_GRAPH_FILES_SCANNED,
    max_file_bytes: int = MAX_GRAPH_FILE_BYTES,
) -> RepoGraph:
    """Scan ``root`` for ``.py`` files and index their symbols and imports.

    Never raises for an unusable tree: a missing root, an unreadable file or a
    syntax error all become recorded evidence rather than an exception --
    matching ``capabilities/testenv/detect.py``'s contract, for the same
    reason: the caller's next move is the same either way, and a scan gone
    silent should still hand back what it could establish.
    """
    if not root.is_dir():
        return RepoGraph(errors=("root: not an existing directory",))

    paths = _walk_python_files(root, max_files)
    truncated = len(paths) >= max_files

    parsed: list[tuple[str, ast.Module]] = []
    errors: list[str] = []
    module_index: dict[str, str] = {}
    for rel_path in paths:
        text = _read_bounded(root / rel_path, max_file_bytes)
        if text is None:
            errors.append(f"{rel_path}: unreadable")
            continue
        try:
            tree = ast.parse(text, filename=rel_path)
        except (SyntaxError, ValueError) as exc:
            errors.append(f"{rel_path}: unparsable ({type(exc).__name__})")
            continue
        parsed.append((rel_path, tree))
        for dotted in _dotted_names(rel_path):
            module_index.setdefault(dotted, rel_path)

    symbols: dict[str, list[SymbolDef]] = {}
    imports: dict[str, ImportEdge] = {}
    dependents: dict[str, set[str]] = {}
    for rel_path, tree in parsed:
        for definition in _collect_symbols(rel_path, tree):
            symbols.setdefault(definition.name, []).append(definition)

        edge = _collect_imports(rel_path, tree, module_index)
        imports[rel_path] = edge
        for target in edge.resolved:
            dependents.setdefault(target, set()).add(rel_path)

    return RepoGraph(
        root_files_scanned=len(paths),
        files_skipped_bound=truncated,
        modules=tuple(rel_path for rel_path, _ in parsed),
        symbols={
            name: tuple(sorted(defs, key=lambda d: (d.path, d.line)))
            for name, defs in symbols.items()
        },
        imports=imports,
        dependents={path: tuple(sorted(sources)) for path, sources in dependents.items()},
        errors=tuple(errors),
    )


def find_references(
    root: Path,
    name: str,
    *,
    max_files: int = MAX_GRAPH_FILES_SCANNED,
    max_file_bytes: int = MAX_GRAPH_FILE_BYTES,
    max_results: int = MAX_REFERENCE_HITS,
) -> tuple[tuple[str, int], ...]:
    """Every ``(path, line)`` where the bare identifier ``name`` is loaded.

    A separate scan from ``build_graph`` rather than a field on ``RepoGraph``:
    building a reference list for every symbol up front costs work no query
    may ever ask for, while this walks the same bounded, screened file set and
    stops as soon as ``max_results`` is reached -- an early stop that stays
    deterministic because the file order it stops within is already sorted.
    """
    hits: list[tuple[str, int]] = []
    for rel_path in _walk_python_files(root, max_files):
        text = _read_bounded(root / rel_path, max_file_bytes)
        if text is None:
            continue
        try:
            tree = ast.parse(text, filename=rel_path)
        except (SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Name | ast.Attribute):
                matched = (
                    isinstance(node, ast.Name)
                    and isinstance(node.ctx, ast.Load)
                    and node.id == name
                ) or (isinstance(node, ast.Attribute) and node.attr == name)
                if matched:
                    hits.append((rel_path, node.lineno))
            if len(hits) >= max_results:
                return tuple(hits)
    return tuple(hits)


# -- bounded, screened walking -------------------------------------------------


def _walk_python_files(root: Path, max_files: int) -> tuple[str, ...]:
    """Sorted, screened, workspace-relative ``.py`` paths, capped at ``max_files``.

    Directory order and file order are both sorted, so a capped walk always
    keeps the same prefix of the same set -- the determinism guarantee holds
    even when a tree is large enough to hit the bound.
    """
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        if not contained(root, current):
            dirnames[:] = []
            continue
        dirnames[:] = sorted(d for d in dirnames if not is_noise_dir(d) and not is_denied_name(d))
        for name in sorted(filenames):
            if not name.endswith(".py") or is_denied_name(name):
                continue
            candidate = current / name
            if not contained(root, candidate):
                continue
            out.append(candidate.relative_to(root).as_posix())
            if len(out) >= max_files:
                return tuple(out)
    return tuple(out)


def _read_bounded(path: Path, max_bytes: int) -> str | None:
    try:
        with path.open("rb") as handle:
            raw = handle.read(max_bytes)
    except OSError:
        return None
    return raw.decode("utf-8", errors="replace")


# -- indexing -------------------------------------------------------------------


def _dotted_names(rel_path: str) -> tuple[str, ...]:
    """Dotted module names this file could be imported as.

    Two candidates when the file lives under ``src/``: the full path form and
    the ``src``-stripped form, because ``from engine.foo import bar`` is how
    this repository's own imports read. Both are indexed so an absolute import
    resolves regardless of which convention a scanned project uses.
    """
    parts = list(PurePosixPath(rel_path).parts)
    if not parts:
        return ()
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    elif parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]
    else:
        return ()
    if not parts:
        return ()
    names = [".".join(parts)]
    if parts[0] == "src" and len(parts) > 1:
        names.append(".".join(parts[1:]))
    return tuple(names)


def _collect_symbols(rel_path: str, tree: ast.Module) -> list[SymbolDef]:
    """Module-level functions and classes, and one level of class methods.

    Deliberately shallow: a function nested inside a function is not indexed.
    Most of what a caller looks up by name -- a public function, a class, a
    method -- lives at this depth, and indexing every nesting level would grow
    the symbol table without growing what a bounded query can usefully return.
    """
    out: list[SymbolDef] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            out.append(
                SymbolDef(
                    name=node.name,
                    kind=_DEF_KIND_FUNCTION,
                    qualname=node.name,
                    path=rel_path,
                    line=node.lineno,
                )
            )
        elif isinstance(node, ast.ClassDef):
            out.append(
                SymbolDef(
                    name=node.name,
                    kind=_DEF_KIND_CLASS,
                    qualname=node.name,
                    path=rel_path,
                    line=node.lineno,
                )
            )
            for member in node.body:
                if isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef):
                    out.append(
                        SymbolDef(
                            name=member.name,
                            kind=_DEF_KIND_METHOD,
                            qualname=f"{node.name}.{member.name}",
                            path=rel_path,
                            line=member.lineno,
                        )
                    )
    return out


def _collect_imports(
    rel_path: str, tree: ast.Module, module_index: dict[str, str]
) -> ImportEdge:
    """One module's dependency edge: which scanned files it imports, and what
    else it names that this scan could not resolve.

    Only the imported *module* is resolved, never an imported name inside it --
    ``from a.b import c`` records a dependency on ``a.b``, not a claim about
    what ``c`` is. That is the right granularity for a module dependency graph
    and sidesteps having to decide whether ``c`` is a submodule or an attribute,
    which AST alone cannot say.
    """
    resolved: set[str] = set()
    external: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                _resolve_one(alias.name, module_index, rel_path, resolved, external)
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:
                external.add(f"{'.' * node.level}{node.module or ''}")
                continue
            if node.module:
                _resolve_one(node.module, module_index, rel_path, resolved, external)
    return ImportEdge(path=rel_path, resolved=tuple(sorted(resolved)), external=tuple(sorted(external)))


def _resolve_one(
    dotted: str,
    module_index: dict[str, str],
    importing_path: str,
    resolved: set[str],
    external: set[str],
) -> None:
    target = module_index.get(dotted)
    if target is not None and target != importing_path:
        resolved.add(target)
    else:
        external.add(dotted)


__all__ = [
    "MAX_GRAPH_FILES_SCANNED",
    "MAX_GRAPH_FILE_BYTES",
    "MAX_REFERENCE_HITS",
    "build_graph",
    "find_references",
]
