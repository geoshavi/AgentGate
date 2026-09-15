"""Content search across the workspace.

Fixed-string by default; ``regex: true`` opts into a pattern. An invalid
regex is an argument error the model can correct, not a crash -- the same
treatment a missing file gets.
"""

import re
from pathlib import Path
from typing import Any

from engine.codeagent.state import ToolResult
from engine.codeagent.tools.base import (
    ToolContext,
    ToolError,
    bool_arg,
    guarded,
    ok,
    str_arg,
)
from engine.codeagent.workspace import SKIPPED_DIR_NAMES, is_denied_name

# Suffixes worth searching. An allowlist rather than a binary sniff: the
# purpose is to find code, and a repository's binaries and lockfiles are noise
# that would consume the result cap without informing an edit.
SEARCHABLE_SUFFIXES = frozenset(
    {".py", ".pyi", ".md", ".txt", ".toml", ".cfg", ".ini", ".json", ".yaml", ".yml", ".sh"}
)


class SearchFilesTool:
    name = "search_files"
    description = (
        "Search workspace file contents. Args: pattern, regex (default false), "
        "suffix (e.g. '.py')."
    )

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        def _run() -> ToolResult:
            pattern = str_arg(args, "pattern")
            use_regex = bool_arg(args, "regex", False)
            suffix = str_arg(args, "suffix", "")
            if not pattern:
                raise ToolError("argument 'pattern' must not be empty")

            matcher = _build_matcher(pattern, use_regex)
            hits: list[str] = []
            capped = False

            for path in _searchable_files(ctx.workspace.root, suffix):
                try:
                    text = path.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                relative = path.relative_to(ctx.workspace.root).as_posix()
                for lineno, line in enumerate(text.splitlines(), start=1):
                    if not matcher(line):
                        continue
                    if len(hits) >= ctx.limits.max_search_results:
                        capped = True
                        break
                    hits.append(f"{relative}:{lineno}: {line.strip()}")
                if capped:
                    break

            if not hits:
                return ok(f"no matches for {pattern!r}", ctx)
            body = "\n".join(hits)
            if capped:
                body += f"\n... [capped at {ctx.limits.max_search_results} matches]"
            return ok(body, ctx)

        return guarded(_run)


def _build_matcher(pattern: str, use_regex: bool) -> Any:
    if not use_regex:
        return lambda line: pattern in line
    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        raise ToolError(f"invalid regex {pattern!r}: {exc}") from exc
    return lambda line: compiled.search(line) is not None


def _searchable_files(root: Path, suffix: str) -> list[Path]:
    found: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        parts = path.relative_to(root).parts
        if any(part in SKIPPED_DIR_NAMES or is_denied_name(part) for part in parts):
            continue
        if suffix:
            if path.suffix != suffix:
                continue
        elif path.suffix not in SEARCHABLE_SUFFIXES:
            continue
        found.append(path)
    return found
