"""What counts as a documentation or config-doc file this agent may write.

A filename-pattern check, not a directory rule: a `.py` file placed under
`docs/` is still refused, and a `README.md` outside any `docs/` directory is
still allowed. That is deliberate -- "documentation" is a property of what a
file is, not of where it happens to sit, and a directory-based rule would be a
loophole (write production code, just put it under `docs/`) this one closes
by construction.

This is a content-type filter layered on top of the existing path safety in
``Workspace.resolve`` -- it does not replace it. ``tools.py`` checks a path
against this *before* delegating to the real ``WriteFileTool``/
``ReplaceExactTool``, which still resolves and contains the path exactly as
it does for every other caller.
"""

from pathlib import PurePosixPath

DOC_EXTENSIONS = frozenset({".md", ".rst", ".txt"})
# Matched on the filename with its extension stripped, case-insensitively --
# covers README, README.md, README.rst, etc. in one rule.
DOC_STEMS = frozenset(
    {"readme", "changelog", "license", "notice", "authors", "contributing", "handover"}
)
# Exact filenames, checked case-insensitively, for conventions that are not
# prose but exist to document configuration for a human reader.
DOC_EXACT_NAMES = frozenset({".env.example"})


def is_doc_path(raw_path: str) -> bool:
    """True if ``raw_path``'s filename looks like a documentation or
    config-doc file this agent is allowed to write.

    Judged on the final path component only, so a caller does not need the
    path resolved or normalised first -- Windows or POSIX separators both
    work, since only the basename is examined.
    """
    if not isinstance(raw_path, str) or not raw_path.strip():
        return False
    name = PurePosixPath(raw_path.replace("\\", "/").strip()).name
    if not name:
        return False
    lowered = name.lower()
    if lowered in DOC_EXACT_NAMES:
        return True
    parsed = PurePosixPath(lowered)
    if parsed.suffix in DOC_EXTENSIONS:
        return True
    return parsed.stem in DOC_STEMS


__all__ = ["DOC_EXACT_NAMES", "DOC_EXTENSIONS", "DOC_STEMS", "is_doc_path"]
