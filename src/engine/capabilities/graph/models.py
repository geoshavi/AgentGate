"""What the repository graph found, and what it is allowed to claim.

A value, not a decision -- the same contract ``capabilities/testenv/models.py``
and ``capabilities/analysis/models.py`` hold to. ``RepoGraph`` records what a
deterministic AST/import scan of the workspace found; nothing here decides
anything, and nothing downstream is obliged to act on it. AgentGate verdicts,
judge lenses, severity thresholds and the Debug Agent's frozen reproduction and
suite are settled by other components entirely and never consult this value.

**References are token-based, not type-resolved.** ``find_references`` matches
a bare identifier against every ``Name``/``Attribute`` load in the repository;
it cannot tell one ``run`` from another. That is stated in every rendered
result rather than left implicit, because a silently over-broad answer is worse
than an honestly coarse one.

``as_dict`` on every value here is metadata only -- paths, names, line numbers,
counts. No source line is ever carried, because a graph exists to reduce reads,
and quoting source back into context would defeat that.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SymbolDef:
    """One function, class or method definition, already bounded."""

    name: str
    kind: str  # "function" | "class" | "method"
    qualname: str
    path: str  # workspace-relative, POSIX separators
    line: int

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "kind": self.kind,
            "qualname": self.qualname,
            "path": self.path,
            "line": self.line,
        }


@dataclass(frozen=True)
class ImportEdge:
    """One module's import statements, resolved as far as the scan can tell.

    ``resolved`` holds workspace-relative paths of imports the scan could match
    to a scanned file. ``external`` holds every other imported name verbatim --
    a stdlib or third-party module, or one outside the scan's bounds -- because
    "not in this repository" is itself useful evidence and silently dropping it
    would understate a module's real dependencies.
    """

    path: str
    resolved: tuple[str, ...] = ()
    external: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "resolved": list(self.resolved),
            "external": list(self.external),
        }


@dataclass(frozen=True)
class RepoGraph:
    """One deterministic scan of a workspace's Python source.

    Frozen, and every collection inside it is a tuple or an already-sorted
    mapping, so the same tree scanned twice produces an equal value -- the
    determinism this capability promises is a property of the type, not a
    convention callers must remember to preserve.

    ``modules`` is every scanned file, sorted. ``symbols`` maps a bare name to
    every definition found for it, each list already bounded and sorted by
    ``(path, line)``. ``imports`` maps a module path to its own ``ImportEdge``.
    ``dependents`` is the reverse of ``imports``' resolved edges, precomputed
    once here rather than in every tool call.
    """

    root_files_scanned: int = 0
    files_skipped_bound: bool = False
    modules: tuple[str, ...] = ()
    symbols: dict[str, tuple[SymbolDef, ...]] = field(default_factory=dict)
    imports: dict[str, ImportEdge] = field(default_factory=dict)
    dependents: dict[str, tuple[str, ...]] = field(default_factory=dict)
    errors: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        """Summary metadata for a report -- counts and error notes only."""
        return {
            "modules_scanned": len(self.modules),
            "symbols_indexed": sum(len(v) for v in self.symbols.values()),
            "files_skipped_bound": self.files_skipped_bound,
            "parse_errors": len(self.errors),
        }


__all__ = ["ImportEdge", "RepoGraph", "SymbolDef"]
