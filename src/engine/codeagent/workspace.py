"""Workspace isolation: the single gate every file path passes through.

Two guarantees, and nothing else:

  1. A resolved path is inside the workspace root, or the call raises.
  2. A resolved path is not a credential-shaped file, or the call raises.

Both are enforced in ``resolve()``, which every file tool must call before
touching the filesystem. A tool that builds a path any other way is a bug --
there is deliberately no second way to turn a model-supplied string into a
``Path`` in this package.

Relationship to ``orchestrator/agents/common.py:write_files``: that function
already contains the ``is_relative_to`` guard, and this module uses the same
technique. It is reimplemented rather than imported on purpose. Importing it
would make the Coding Agent depend on the legacy Research -> Coding -> Testing
execution path, which the blueprint keeps strictly separate, and would couple
a security boundary to a module that is free to change for unrelated reasons.
Duplicating eleven lines is the cheaper of the two costs.

Secret blocking covers reads as well as writes. Reading a credential is as
much a leak as writing one, because a read lands in the session transcript
and, later, in a model prompt.
"""

from pathlib import Path, PurePath

# Directory names that are never listed, searched, read, or written. ``.git``
# is denied wholesale rather than just ``.git/config`` and ``.git/hooks``:
# the agent's only legitimate git access is through the read-only subcommands
# the command policy allows, which reach the repository via git itself, not by
# opening files under ``.git``. Blocking the whole directory is simpler to
# state, simpler to test, and strictly safer than an inner allowlist.
DENIED_DIR_NAMES = frozenset(
    {".git", ".ssh", ".aws", ".gnupg", ".engine", "node_modules"}
)

# Exact filenames that are never accessible, matched case-insensitively so a
# case-insensitive filesystem cannot be used to sidestep the list.
DENIED_FILE_NAMES = frozenset(
    {
        ".env",
        ".netrc",
        "_netrc",
        ".npmrc",
        ".pypirc",
        ".htpasswd",
        "credentials",
        "credentials.json",
        "service-account.json",
    }
)

# Filename prefixes that are never accessible.
DENIED_FILE_PREFIXES = (".env", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "secrets")

# Filename suffixes that are never accessible.
DENIED_FILE_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".keystore", ".jks")

# Directories skipped when walking or searching. Not a security boundary --
# these are noise, not secrets -- so they are filtered rather than refused.
# DENIED_DIR_NAMES entries are repeated here so a walk never descends into
# one and then has to unwind a refusal per entry.
SKIPPED_DIR_NAMES = frozenset(
    {
        ".venv",
        "venv",
        "__pycache__",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        ".tox",
        "dist",
        "build",
        ".idea",
        ".vscode",
    }
) | DENIED_DIR_NAMES


class WorkspaceError(Exception):
    """Base for every refusal this module makes."""


class WorkspaceEscape(WorkspaceError):
    """The path resolved outside the workspace root."""


class ForbiddenPath(WorkspaceError):
    """The path is inside the workspace but is credential-shaped."""


class TooManyFilesChanged(WorkspaceError):
    """The session's max_files_changed ceiling was reached."""


def is_denied_name(name: str) -> bool:
    """True if ``name`` (a single path component) is credential-shaped.

    Public because directory walks and searches need to filter entries they
    are never allowed to surface, and doing that by catching ForbiddenPath
    per entry would be both slower and easy to get wrong.
    """
    lowered = name.casefold()
    if lowered in DENIED_FILE_NAMES or lowered in DENIED_DIR_NAMES:
        return True
    if lowered.startswith(DENIED_FILE_PREFIXES):
        return True
    return lowered.endswith(DENIED_FILE_SUFFIXES)


class Workspace:
    """A rooted, guarded view of one task's working directory.

    Also carries the session's mutation ledger. That is not scope creep: the
    workspace is the only object every write passes through, so it is the one
    place ``max_files_changed`` can be enforced without a tool being able to
    route around it.
    """

    def __init__(self, root: Path, *, max_files_changed: int = 20) -> None:
        resolved = Path(root).resolve()
        if not resolved.is_dir():
            raise WorkspaceError(f"workspace root is not an existing directory: {resolved}")
        self.root = resolved
        self._max_files_changed = max_files_changed
        self._changed: list[str] = []
        self._inspected: list[str] = []

    # -- path guard ---------------------------------------------------------

    def resolve(self, relative: str) -> Path:
        """Turn a model-supplied relative path into an absolute path inside
        the workspace, or raise.

        Raises:
            WorkspaceEscape: absolute, drive-qualified, or ``..``-traversing
                input, or a path (including via symlink) landing outside root.
            ForbiddenPath: a credential-shaped component anywhere in the path.
        """
        rel = self._as_relative(relative)
        candidate = (self.root / rel).resolve()

        if candidate != self.root and not candidate.is_relative_to(self.root):
            # Reached when a component is a symlink pointing outside the
            # workspace: Path.resolve() follows symlinks, so the escape shows
            # up here even though the literal string looked harmless.
            raise WorkspaceEscape(
                f"path escapes the workspace: {relative!r} -> {candidate}"
            )

        self._assert_allowed(candidate)
        return candidate

    def relative(self, path: Path) -> str:
        """Posix-style path of ``path`` relative to the root, for reporting."""
        return path.resolve().relative_to(self.root).as_posix()

    def _as_relative(self, relative: str) -> PurePath:
        if not isinstance(relative, str):
            raise WorkspaceEscape(f"path must be a string, got {type(relative).__name__}")
        # Models emit Windows-style separators regardless of host OS. Convert
        # before parsing so 'src\\mod.py' is one two-component path rather
        # than a single oddly-named file on POSIX. The cost is that a POSIX
        # filename genuinely containing a backslash is unreachable; that is
        # vanishingly rare and worth the cross-platform correctness.
        cleaned = relative.replace("\\", "/").strip()
        if cleaned in ("", "."):
            return PurePath()

        candidate = PurePath(cleaned)
        if candidate.is_absolute() or candidate.root or candidate.drive:
            # ``drive`` catches the Windows drive-relative form 'C:foo', which
            # is_absolute() reports as False.
            raise WorkspaceEscape(f"absolute paths are not allowed: {relative!r}")
        if any(part == ".." for part in candidate.parts):
            raise WorkspaceEscape(f"'..' traversal is not allowed: {relative!r}")
        return candidate

    def _assert_allowed(self, candidate: Path) -> None:
        if candidate == self.root:
            return
        for part in candidate.relative_to(self.root).parts:
            if is_denied_name(part):
                raise ForbiddenPath(
                    f"access to credential-sensitive path is refused: "
                    f"{candidate.relative_to(self.root).as_posix()}"
                )

    # -- mutation ledger ----------------------------------------------------

    @property
    def changed_files(self) -> list[str]:
        return list(self._changed)

    @property
    def inspected_files(self) -> list[str]:
        return list(self._inspected)

    def note_inspected(self, path: Path) -> None:
        rel = self.relative(path)
        if rel not in self._inspected:
            self._inspected.append(rel)

    def note_changed(self, path: Path) -> None:
        """Record a mutation, enforcing the max_files_changed ceiling.

        Called *before* the write lands, so a refused write never happens at
        all rather than being recorded and then undone.
        """
        rel = self.relative(path)
        if rel in self._changed:
            return
        if len(self._changed) >= self._max_files_changed:
            raise TooManyFilesChanged(
                f"refusing to modify a {self._max_files_changed + 1}th file "
                f"({rel}); max_files_changed is {self._max_files_changed}"
            )
        self._changed.append(rel)
