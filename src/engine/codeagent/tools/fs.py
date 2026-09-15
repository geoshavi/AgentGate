"""Filesystem tools: list, read, write, and anchored replace.

Editing is anchored exact replacement, never full-file rewrite and never
unified diff. The anchor must match exactly once; zero matches and multiple
matches are both explicit errors. "Replace the first match" is not offered as
a behaviour, because a model that supplied an ambiguous anchor did not decide
which occurrence it meant -- picking one for it is a silent edit to code the
agent was not asked to touch.

**Edits preserve the file's newline convention.** Python's text mode translates
on both ends: reading turns every CRLF into LF, and writing turns every LF into
``os.linesep``. Together that rewrites every line ending in a file on any write
-- to CRLF on Windows, to LF elsewhere -- so a one-line anchored edit lands as a
whole-file diff. Editing therefore goes through ``_read_raw``/``_write_raw``,
which disable translation, and the agent's LF-separated anchor is re-expressed
in the file's own convention by ``_as_newline`` before it is matched.
"""

from pathlib import Path
from typing import Any

from engine.codeagent.state import ToolResult
from engine.codeagent.tools.base import (
    ToolContext,
    ToolError,
    bool_arg,
    failed,
    guarded,
    int_arg,
    ok,
    str_arg,
)
from engine.codeagent.workspace import SKIPPED_DIR_NAMES, is_denied_name


def _read_text(path: Path) -> str:
    """Universal-newline read: what the *model* is shown, always LF."""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ToolError(f"{path.name} is not UTF-8 text") from exc


def _read_raw(path: Path) -> str:
    """The file exactly as stored, with its newlines untranslated."""
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            return handle.read()
    except UnicodeDecodeError as exc:
        raise ToolError(f"{path.name} is not UTF-8 text") from exc


def _write_raw(path: Path, text: str) -> None:
    """Write ``text`` verbatim. ``newline=""`` is what disables translation."""
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def _dominant_newline(raw: str) -> str:
    """The newline convention ``raw`` already uses; LF when it has none.

    Counted rather than taken from the first match, so a CRLF file carrying one
    stray LF still round-trips as CRLF. Ties go to CRLF, which only arise in
    files that are already mixed.
    """
    crlf = raw.count("\r\n")
    counts = {"\r\n": crlf, "\n": raw.count("\n") - crlf, "\r": raw.count("\r") - crlf}
    best = max(counts, key=lambda newline: counts[newline])
    return best if counts[best] else "\n"


def _as_newline(text: str, newline: str) -> str:
    """Re-express LF-separated agent text in the file's own convention."""
    if newline == "\n":
        return text
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", newline)


class ListFilesTool:
    name = "list_files"
    description = "List files under a workspace-relative directory. Args: path, max_depth."

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        def _run() -> ToolResult:
            rel = str_arg(args, "path", "")
            max_depth = int_arg(args, "max_depth", ctx.limits.max_list_depth)
            root = ctx.workspace.resolve(rel)
            if not root.is_dir():
                return failed(f"not a directory: {rel or '.'}")

            entries: list[str] = []
            hit_cap = _walk(root, root, 0, max_depth, ctx.limits.max_list_entries, entries)
            body = "\n".join(entries) if entries else "(empty)"
            if hit_cap:
                body += f"\n... [listing capped at {ctx.limits.max_list_entries} entries]"
            return ok(body, ctx)

        return guarded(_run)


def _walk(
    current: Path, base: Path, depth: int, max_depth: int, cap: int, out: list[str]
) -> bool:
    """Depth-first listing. Returns True if the entry cap was reached."""
    if depth > max_depth:
        return False
    try:
        children = sorted(current.iterdir(), key=lambda p: (p.is_file(), p.name))
    except OSError:
        return False
    for child in children:
        if is_denied_name(child.name) or child.name in SKIPPED_DIR_NAMES:
            continue
        if len(out) >= cap:
            return True
        relative = child.relative_to(base).as_posix()
        if child.is_dir():
            out.append(f"{relative}/")
            if _walk(child, base, depth + 1, max_depth, cap, out):
                return True
        else:
            try:
                size = child.stat().st_size
            except OSError:
                size = 0
            out.append(f"{relative}  ({size} B)")
    return False


class ReadFileTool:
    name = "read_file"
    description = "Read a workspace-relative file with line numbers. Args: path, start, end."

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        def _run() -> ToolResult:
            rel = str_arg(args, "path")
            start = int_arg(args, "start", 1)
            end = int_arg(args, "end", 0)  # 0 means "to the end"
            path = ctx.workspace.resolve(rel)
            if not path.is_file():
                return failed(f"not a file: {rel}")
            if start < 1:
                raise ToolError("argument 'start' must be >= 1")

            raw = _read_text(path)
            byte_len = len(raw.encode("utf-8"))
            clipped = byte_len > ctx.limits.max_read_bytes
            if clipped:
                raw = raw.encode("utf-8")[: ctx.limits.max_read_bytes].decode("utf-8", "ignore")

            lines = raw.splitlines()
            last = len(lines) if end <= 0 else min(end, len(lines))
            selected = lines[start - 1 : last]
            numbered = "\n".join(f"{start + i:>6}| {line}" for i, line in enumerate(selected))
            if clipped:
                numbered += f"\n... [file is {byte_len} B, read capped at {ctx.limits.max_read_bytes} B]"

            ctx.workspace.note_inspected(path)
            return ok(numbered if selected else "(empty)", ctx)

        return guarded(_run)


class WriteFileTool:
    name = "write_file"
    description = (
        "Create a workspace-relative file. Args: path, content, overwrite "
        "(required to replace an existing file)."
    )

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        def _run() -> ToolResult:
            rel = str_arg(args, "path")
            content = str_arg(args, "content")
            overwrite = bool_arg(args, "overwrite", False)
            path = ctx.workspace.resolve(rel)

            # LF for a file that does not exist yet: there is no existing
            # convention to preserve, and the repository's own is LF.
            newline = "\n"
            if path.exists():
                if not overwrite:
                    return failed(
                        f"{rel} already exists; pass overwrite=true to replace it, or use "
                        "replace_exact for a targeted edit"
                    )
                # errors="ignore" as before: the truncation guard must still
                # answer for a file this tool would refuse to read as text.
                with path.open(encoding="utf-8", errors="ignore", newline="") as handle:
                    existing = handle.read()
                if existing.strip() and not content.strip():
                    return failed(
                        f"refusing to truncate non-empty file {rel} to empty content"
                    )
                newline = _dominant_newline(existing)

            # The cap is measured on what actually reaches the disk, not on the
            # LF form the agent sent. Writing into a CRLF file adds a byte per
            # line, so checking the pre-conversion string would let a write
            # through and then serialise it over the ceiling.
            output = _as_newline(content, newline)
            size = len(output.encode("utf-8"))
            if size > ctx.limits.max_write_bytes:
                return failed(
                    f"refusing to write {size} B; max_write_bytes is {ctx.limits.max_write_bytes}"
                )

            ctx.workspace.note_changed(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            _write_raw(path, output)
            return ok(f"wrote {rel} ({size} B)", ctx)

        return guarded(_run)


class ReplaceExactTool:
    name = "replace_exact"
    description = (
        "Replace an exact anchor in a workspace-relative file. The anchor must "
        "occur exactly once. Args: path, find, replace."
    )

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        def _run() -> ToolResult:
            rel = str_arg(args, "path")
            find = str_arg(args, "find")
            replacement = str_arg(args, "replace")
            if not find:
                raise ToolError("argument 'find' must not be empty")

            path = ctx.workspace.resolve(rel)
            if not path.is_file():
                return failed(f"not a file: {rel}")

            # Raw, so every byte outside the anchor survives the write. The
            # anchor arrives LF-separated because read_file shows the model a
            # universal-newline view, so it is re-expressed in the file's own
            # convention before matching -- otherwise no edit to a CRLF file
            # could ever find its anchor.
            content = _read_raw(path)
            newline = _dominant_newline(content)
            find = _as_newline(find, newline)
            replacement = _as_newline(replacement, newline)
            occurrences = content.count(find)
            if occurrences == 0:
                return failed(
                    f"anchor not found in {rel}; read the file and copy the exact text, "
                    "including indentation"
                )
            if occurrences > 1:
                return failed(
                    f"anchor occurs {occurrences} times in {rel}; extend it with surrounding "
                    "lines until it is unique. This edit was NOT applied."
                )
            if not replacement.strip() and len(find) > ctx.limits.max_delete_bytes:
                return failed(
                    f"refusing to delete {len(find)} B in one edit; max_delete_bytes is "
                    f"{ctx.limits.max_delete_bytes}"
                )

            ctx.workspace.note_changed(path)
            _write_raw(path, content.replace(find, replacement, 1))
            delta = len(replacement) - len(find)
            return ok(f"replaced 1 occurrence in {rel} ({delta:+d} chars)", ctx)

        return guarded(_run)
