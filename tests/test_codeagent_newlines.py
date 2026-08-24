"""Newline preservation for the controlled edit tools.

Every assertion here reads **raw bytes**. ``Path.read_text`` opens in universal
-newline mode, which silently turns ``\\r\\n`` into ``\\n`` on the way in -- a
test written with it passes whether or not the bug is present, which is exactly
how this shipped. ``read_bytes`` is the only way to prove the file on disk kept
its convention.

The bug these cover was observed in the D4 live demo: a one-line anchored edit
to an LF file came back as a whole-file diff because every line ending had been
rewritten to CRLF.
"""

import shutil
from pathlib import Path

from engine.codeagent.limits import Limits
from engine.codeagent.policy import DEFAULT_POLICY
from engine.codeagent.tools.base import ToolContext
from engine.codeagent.tools.registry import get_tool
from engine.codeagent.workspace import Workspace

FIXTURE = Path(__file__).resolve().parent.parent / "examples" / "cart_bug"


def _ctx(tmp_path: Path, **limit_overrides: object) -> ToolContext:
    root = tmp_path / "ws"
    root.mkdir(exist_ok=True)
    return ToolContext(
        workspace=Workspace(root),
        policy=DEFAULT_POLICY,
        limits=Limits(**limit_overrides),  # type: ignore[arg-type]
    )


def _write_bytes(ctx: ToolContext, relative: str, payload: bytes) -> Path:
    """Seed a file with an exact byte payload, bypassing any text-mode translation."""
    path = ctx.workspace.root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


# -- replace_exact ----------------------------------------------------------


def test_replace_exact_keeps_an_lf_file_lf(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    path = _write_bytes(ctx, "m.py", b"a = 1\nb = 2\nc = 3\n")

    result = get_tool("replace_exact").run(
        {"path": "m.py", "find": "b = 2", "replace": "b = 22"}, ctx
    )

    assert result.ok
    assert path.read_bytes() == b"a = 1\nb = 22\nc = 3\n"
    assert b"\r\n" not in path.read_bytes()


def test_replace_exact_keeps_a_crlf_file_crlf(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    path = _write_bytes(ctx, "m.py", b"a = 1\r\nb = 2\r\nc = 3\r\n")

    result = get_tool("replace_exact").run(
        {"path": "m.py", "find": "b = 2", "replace": "b = 22"}, ctx
    )

    assert result.ok
    assert path.read_bytes() == b"a = 1\r\nb = 22\r\nc = 3\r\n"
    # Every newline is still a CRLF: no lone LF was introduced anywhere.
    assert path.read_bytes().count(b"\n") == path.read_bytes().count(b"\r\n")


def test_replace_exact_matches_a_multiline_lf_anchor_against_a_crlf_file(
    tmp_path: Path,
) -> None:
    """The agent's anchor is LF because read_file returns universal newlines.

    It must still match a CRLF file, or every edit to a CRLF file fails with
    "anchor not found" -- trading a corruption bug for an unusable tool.
    """
    ctx = _ctx(tmp_path)
    path = _write_bytes(ctx, "m.py", b"def f():\r\n    x = 1\r\n    return x\r\n")

    result = get_tool("replace_exact").run(
        {"path": "m.py", "find": "    x = 1\n    return x", "replace": "    return 1"},
        ctx,
    )

    assert result.ok
    assert path.read_bytes() == b"def f():\r\n    return 1\r\n"


def test_replace_exact_does_not_normalize_the_untouched_part_of_a_mixed_file(
    tmp_path: Path,
) -> None:
    """One replacement rewrites one span, never the whole file."""
    ctx = _ctx(tmp_path)
    path = _write_bytes(ctx, "m.py", b"a = 1\r\nb = 2\nc = 3\r\nd = 4\n")

    result = get_tool("replace_exact").run(
        {"path": "m.py", "find": "c = 3", "replace": "c = 33"}, ctx
    )

    assert result.ok
    # Byte-for-byte identical outside the replaced anchor -- both conventions survive.
    assert path.read_bytes() == b"a = 1\r\nb = 2\nc = 33\r\nd = 4\n"


def test_replace_exact_preserves_a_file_with_no_trailing_newline(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    path = _write_bytes(ctx, "m.py", b"a = 1")

    result = get_tool("replace_exact").run(
        {"path": "m.py", "find": "a = 1", "replace": "a = 2"}, ctx
    )

    assert result.ok
    assert path.read_bytes() == b"a = 2"


# -- write_file -------------------------------------------------------------


def test_write_file_overwrite_keeps_an_lf_file_lf(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    path = _write_bytes(ctx, "m.py", b"old = 1\nold = 2\n")

    result = get_tool("write_file").run(
        {"path": "m.py", "content": "new = 1\nnew = 2\n", "overwrite": True}, ctx
    )

    assert result.ok
    assert path.read_bytes() == b"new = 1\nnew = 2\n"


def test_write_file_overwrite_keeps_a_crlf_file_crlf(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    path = _write_bytes(ctx, "m.py", b"old = 1\r\nold = 2\r\n")

    result = get_tool("write_file").run(
        {"path": "m.py", "content": "new = 1\nnew = 2\n", "overwrite": True}, ctx
    )

    assert result.ok
    assert path.read_bytes() == b"new = 1\r\nnew = 2\r\n"


# -- write_file: max_write_bytes measures the serialized payload ------------
#
# Content arrives LF-separated. Writing it into a CRLF file adds one byte per
# line, so a cap applied to the pre-conversion string is a cap on the wrong
# number: the write passes the check and then lands over the ceiling.


def test_write_file_accepts_an_lf_overwrite_exactly_at_the_limit(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, max_write_bytes=8)
    path = _write_bytes(ctx, "m.py", b"old\n")

    result = get_tool("write_file").run(
        {"path": "m.py", "content": "abc\ndef\n", "overwrite": True}, ctx
    )

    assert result.ok, result.error
    assert path.read_bytes() == b"abc\ndef\n"
    assert len(path.read_bytes()) == 8


def test_write_file_rejects_a_crlf_expansion_that_exceeds_the_limit(tmp_path: Path) -> None:
    """The same 8-byte LF content serialises to 10 bytes into a CRLF file."""
    ctx = _ctx(tmp_path, max_write_bytes=8)
    _write_bytes(ctx, "m.py", b"old\r\n")

    result = get_tool("write_file").run(
        {"path": "m.py", "content": "abc\ndef\n", "overwrite": True}, ctx
    )

    assert not result.ok
    assert "max_write_bytes" in (result.error or "")
    # The refusal names the real serialized size, not the LF undercount.
    assert "10 B" in (result.error or "")


def test_write_file_rejection_leaves_the_original_bytes_untouched(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, max_write_bytes=8)
    original = b"old\r\nkeep\r\n"
    path = _write_bytes(ctx, "m.py", original)

    result = get_tool("write_file").run(
        {"path": "m.py", "content": "abc\ndef\n", "overwrite": True}, ctx
    )

    assert not result.ok
    assert path.read_bytes() == original
    # A refused write is not a mutation, so it must not reach the ledger.
    assert ctx.workspace.changed_files == []


def test_write_file_accepts_crlf_content_within_the_serialized_limit(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, max_write_bytes=10)
    path = _write_bytes(ctx, "m.py", b"old\r\n")

    result = get_tool("write_file").run(
        {"path": "m.py", "content": "abc\ndef\n", "overwrite": True}, ctx
    )

    assert result.ok, result.error
    assert path.read_bytes() == b"abc\r\ndef\r\n"
    assert len(path.read_bytes()) == 10


def test_write_file_creates_new_files_with_lf(tmp_path: Path) -> None:
    """A file that does not exist has no convention to preserve; LF is the default."""
    ctx = _ctx(tmp_path)

    result = get_tool("write_file").run({"path": "new.py", "content": "x = 1\ny = 2\n"}, ctx)

    assert result.ok
    assert (ctx.workspace.root / "new.py").read_bytes() == b"x = 1\ny = 2\n"


# -- the live-demo scenario, offline ----------------------------------------


def test_cart_bug_edit_is_not_a_whole_file_newline_rewrite(tmp_path: Path) -> None:
    """The exact D4 live-demo edit, replayed through the real controlled tool.

    The live run produced a diff in which all 33 lines showed as changed. Only
    the three lines the agent actually moved may differ.
    """
    ctx = _ctx(tmp_path)
    shutil.copytree(FIXTURE / "tests", ctx.workspace.root / "tests")
    shutil.copy2(FIXTURE / "cart.py", ctx.workspace.root / "cart.py")
    target = ctx.workspace.root / "cart.py"

    before = target.read_bytes()
    assert b"\r\n" not in before, "fixture precondition: cart.py is LF in the repository"

    result = get_tool("replace_exact").run(
        {
            "path": "cart.py",
            "find": (
                "    cheapest = min(item.price for item in items)\n"
                "    if sum(item.qty for item in items) < BULK_UNITS:\n"
                "        return 0.0"
            ),
            "replace": (
                "    if not items or sum(item.qty for item in items) < BULK_UNITS:\n"
                "        return 0.0\n"
                "    cheapest = min(item.price for item in items)"
            ),
        },
        ctx,
    )

    assert result.ok
    after = target.read_bytes()

    # 1. No newline conversion anywhere in the file.
    assert b"\r\n" not in after

    # 2. A raw byte-level line diff touches only the intended logical lines.
    before_lines = before.split(b"\n")
    after_lines = after.split(b"\n")
    assert len(before_lines) == len(after_lines)
    changed = [
        (i, b, a)
        for i, (b, a) in enumerate(zip(before_lines, after_lines))
        if b != a
    ]
    # 0-indexed 23..25 == cart.py lines 24-26, the body of _discount and
    # nothing else. 33 lines in the file; the live run showed all 33 as changed.
    assert [i for i, _, _ in changed] == [23, 24, 25], changed
    assert len(changed) == 3, f"expected a 3-line change, got {len(changed)}: {changed}"

    # 3. The fix is real: the empty cart no longer raises.
    assert b"if not items or sum(item.qty for item in items) < BULK_UNITS:" in after
