"""Path screening shared by every capability that reads a file.

Two capabilities now read from disk for different reasons -- the skills registry
snapshots authored instruction files, the test detector inspects configuration --
and both must refuse the same two things: a path that escapes its root, and a
name that looks like a credential. Those rules live here once rather than in each
reader, because two copies of a security screen is two chances to fix only one.

This is a *screen*, not a sandbox, and the honest scope is the same one
``codeagent/policy.py`` states for commands: it stops a reader from surfacing a
credential-shaped file or following a link out of its root. It does not stop
anything else on the machine from touching those files.

Deliberately reimplements ``codeagent.workspace``'s technique rather than
importing it. ``capabilities/`` is a leaf (architecture Rule H), and a capability
reader is read-only -- it has no mutation ledger and no ``max_files_changed``
ceiling to inherit, so borrowing ``Workspace`` would hand it machinery it must
never use.
"""

from pathlib import Path

# Directory names never descended into. The first six are credential stores or
# repository internals; the rest are build and dependency noise that would make
# a bounded read budget meaningless.
DENIED_DIR_NAMES = frozenset({".git", ".ssh", ".aws", ".gnupg", ".engine", "node_modules"})
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

# Exact filenames never read, matched case-insensitively so a case-insensitive
# filesystem cannot be used to sidestep the list.
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
DENIED_FILE_PREFIXES = (".env", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "secrets")
DENIED_FILE_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".keystore", ".jks")


def is_denied_name(name: str) -> bool:
    """True if ``name`` (one path component) is credential-shaped.

    Public because readers filter entries they must never surface, and doing that
    by catching a refusal per entry would be both slower and easier to get wrong.
    """
    lowered = name.casefold()
    if lowered in DENIED_FILE_NAMES or lowered in DENIED_DIR_NAMES:
        return True
    if lowered.startswith(DENIED_FILE_PREFIXES):
        return True
    return lowered.endswith(DENIED_FILE_SUFFIXES)


def is_noise_dir(name: str) -> bool:
    """True for a directory a bounded reader should not descend into."""
    return name.casefold() in SKIPPED_DIR_NAMES


def contained(root: Path, candidate: Path) -> bool:
    """True if ``candidate`` resolves inside ``root``.

    Resolution follows symlinks *before* the containment check, so a link
    pointing outside the root is caught here even though its literal path looked
    ordinary. Returns False rather than raising on an unreadable path: a caller
    screening candidates wants a verdict per entry, not an exception to unwind.
    """
    try:
        resolved = candidate.resolve()
        return resolved == root.resolve() or resolved.is_relative_to(root.resolve())
    except OSError:
        return False


__all__ = [
    "DENIED_DIR_NAMES",
    "DENIED_FILE_NAMES",
    "DENIED_FILE_PREFIXES",
    "DENIED_FILE_SUFFIXES",
    "SKIPPED_DIR_NAMES",
    "contained",
    "is_denied_name",
    "is_noise_dir",
]
