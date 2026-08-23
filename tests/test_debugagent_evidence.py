"""D1: deterministic failure evidence.

Every test here is offline and model-free by construction: nothing in this
module imports a gateway, a provider, or a budget. ``build_evidence`` is a pure
function of the strings a command produced, so the same failure yields byte-
identical evidence on every run -- which is the property that makes these
assertions exact rather than approximate.
"""

import json
from pathlib import Path

import pytest

from engine.codeagent.limits import Limits
from engine.codeagent.workspace import Workspace
from engine.debugagent.evidence import Frame, build_evidence, render_evidence


def _ws(tmp_path: Path, files: dict[str, str] | None = None) -> Workspace:
    root = tmp_path / "ws"
    root.mkdir(exist_ok=True)
    for relative, content in (files or {}).items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return Workspace(root)


def _evidence(workspace: Workspace, *, stdout: str = "", stderr: str = "", exit_code: int = 1, **kw):
    defaults: dict = {
        "argv": ["python", "-m", "pytest", "-q"],
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": exit_code,
        "timed_out": False,
        "duration_ms": 12,
        "workspace": workspace,
        "limits": Limits(),
    }
    defaults.update(kw)
    return build_evidence(**defaults)


def _traceback(root: Path) -> str:
    return (
        "Traceback (most recent call last):\n"
        f'  File "{root / "cart.py"}", line 11, in cart_total\n'
        "    return subtotal - _discount(items)\n"
        f'  File "{root / "cart.py"}", line 23, in _discount\n'
        "    cheapest = min(i.price for i in items)\n"
        "ValueError: min() arg is an empty sequence\n"
    )


# -- reproduction flag ------------------------------------------------------


def test_non_zero_exit_is_reproduced(tmp_path: Path) -> None:
    assert _evidence(_ws(tmp_path), exit_code=1).reproduced is True


def test_zero_exit_is_not_reproduced(tmp_path: Path) -> None:
    assert _evidence(_ws(tmp_path), exit_code=0).reproduced is False


def test_timeout_is_not_reproduced(tmp_path: Path) -> None:
    ev = _evidence(_ws(tmp_path), exit_code=None, timed_out=True)
    assert ev.reproduced is False
    assert ev.timed_out is True


# -- traceback frame extraction ---------------------------------------------


def test_extracts_in_workspace_frames(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"cart.py": "x = 1\n" * 30})
    ev = _evidence(ws, stderr=_traceback(ws.root))

    assert ev.frames == [
        Frame(file="cart.py", line=11, function="cart_total"),
        Frame(file="cart.py", line=23, function="_discount"),
    ]


def test_suspect_is_the_last_in_workspace_frame(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"cart.py": "x = 1\n" * 30})
    ev = _evidence(ws, stderr=_traceback(ws.root))

    assert ev.suspect == Frame(file="cart.py", line=23, function="_discount")


def test_frame_outside_the_workspace_is_dropped(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"cart.py": "x = 1\n" * 30})
    outside = tmp_path / "elsewhere" / "secrets.py"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_text("x = 1\n", encoding="utf-8")

    text = (
        "Traceback (most recent call last):\n"
        f'  File "{outside}", line 3, in leak\n'
        f'  File "{ws.root / "cart.py"}", line 23, in _discount\n'
        "ValueError: boom\n"
    )
    ev = _evidence(ws, stderr=text)

    assert ev.frames == [Frame(file="cart.py", line=23, function="_discount")]
    assert all("secrets" not in f.file for f in ev.frames)


def test_stdlib_frame_is_dropped(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"cart.py": "x = 1\n" * 30})
    text = (
        "Traceback (most recent call last):\n"
        '  File "/usr/lib/python3.14/random.py", line 100, in choice\n'
        f'  File "{ws.root / "cart.py"}", line 23, in _discount\n'
        "IndexError: boom\n"
    )
    assert _evidence(ws, stderr=text).frames == [
        Frame(file="cart.py", line=23, function="_discount")
    ]


def test_credential_shaped_frame_is_rejected(tmp_path: Path) -> None:
    """A frame naming a secret file is refused even though it IS in-workspace."""
    ws = _ws(tmp_path, {".env": "ANTHROPIC_API_KEY=sk-real\n", "cart.py": "x = 1\n"})
    text = (
        "Traceback (most recent call last):\n"
        f'  File "{ws.root / ".env"}", line 1, in load\n'
        f'  File "{ws.root / "cart.py"}", line 1, in _discount\n'
        "ValueError: boom\n"
    )
    ev = _evidence(ws, stderr=text)

    assert ev.frames == [Frame(file="cart.py", line=1, function="_discount")]
    assert ".env" not in ev.referenced_files


def test_parent_traversal_frame_is_dropped(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"cart.py": "x = 1\n"})
    text = f'  File "{ws.root}/../outside.py", line 2, in escape\nValueError: boom\n'

    assert _evidence(ws, stderr=text).frames == []


def test_frame_for_a_nonexistent_workspace_file_is_dropped(tmp_path: Path) -> None:
    """A traceback from another machine can name files that are not here."""
    ws = _ws(tmp_path, {"cart.py": "x = 1\n"})
    text = f'  File "{ws.root / "ghost.py"}", line 4, in vanished\nValueError: boom\n'

    assert _evidence(ws, stderr=text).frames == []


def test_relative_frame_paths_are_accepted(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"pkg/mod.py": "x = 1\n" * 10})
    text = '  File "pkg/mod.py", line 4, in handler\nValueError: boom\n'

    assert _evidence(ws, stderr=text).frames == [
        Frame(file="pkg/mod.py", line=4, function="handler")
    ]


def test_frames_are_bounded_keeping_the_deepest(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"cart.py": "x = 1\n" * 60})
    lines = "".join(
        f'  File "{ws.root / "cart.py"}", line {n}, in fn{n}\n' for n in range(1, 21)
    )
    ev = _evidence(ws, stderr=lines + "ValueError: boom\n", limits=Limits(max_evidence_frames=3))

    assert len(ev.frames) == 3
    assert [f.line for f in ev.frames] == [18, 19, 20]
    assert ev.suspect == Frame(file="cart.py", line=20, function="fn20")


def test_no_traceback_still_produces_valid_evidence(tmp_path: Path) -> None:
    ev = _evidence(_ws(tmp_path), stdout="make: *** [all] Error 2\n", exit_code=2)

    assert ev.reproduced is True
    assert ev.frames == []
    assert ev.suspect is None
    assert ev.exception_type is None


# -- exception parsing ------------------------------------------------------


def test_parses_exception_type_and_message(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"cart.py": "x = 1\n" * 30})
    ev = _evidence(ws, stderr=_traceback(ws.root))

    assert ev.exception_type == "ValueError"
    assert ev.exception_message == "min() arg is an empty sequence"


def test_parses_pytest_e_prefixed_exception_line(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"cart.py": "x = 1\n"})
    text = (
        "    def test_empty():\n"
        ">       cart_total([])\n"
        "E       ValueError: min() arg is an empty sequence\n"
    )
    ev = _evidence(ws, stdout=text)

    assert ev.exception_type == "ValueError"
    assert ev.exception_message == "min() arg is an empty sequence"


def test_dotted_exception_type_is_parsed(tmp_path: Path) -> None:
    ev = _evidence(_ws(tmp_path), stderr="myapp.errors.ConfigError: bad value\n")

    assert ev.exception_type == "myapp.errors.ConfigError"


def test_exception_message_is_bounded(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    ev = _evidence(
        ws, stderr="ValueError: " + "z" * 5_000 + "\n", limits=Limits(max_evidence_text_chars=40)
    )

    assert ev.exception_message is not None
    assert len(ev.exception_message) <= 40


# -- output bounds ----------------------------------------------------------


def test_output_is_captured_as_a_tail_not_a_head(tmp_path: Path) -> None:
    """A pytest failure puts the useful part at the END of the output."""
    body = "".join(f"line {n}\n" for n in range(2_000)) + "FINAL MARKER\n"
    ev = _evidence(_ws(tmp_path), stdout=body, limits=Limits(max_repro_output_bytes=100))

    assert "FINAL MARKER" in ev.stdout_tail
    assert "line 0\n" not in ev.stdout_tail
    assert len(ev.stdout_tail) <= 100


def test_stdout_and_stderr_are_bounded_independently(tmp_path: Path) -> None:
    ev = _evidence(
        _ws(tmp_path), stdout="a" * 9_000, stderr="b" * 9_000,
        limits=Limits(max_repro_output_bytes=64),
    )

    assert len(ev.stdout_tail) <= 64
    assert len(ev.stderr_tail) <= 64


def test_short_output_is_not_modified(tmp_path: Path) -> None:
    assert _evidence(_ws(tmp_path), stdout="tiny\n").stdout_tail == "tiny\n"


# -- referenced files -------------------------------------------------------


def test_referenced_files_are_deduplicated_and_relative(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"cart.py": "x = 1\n" * 30})
    ev = _evidence(ws, stderr=_traceback(ws.root))

    assert ev.referenced_files == ["cart.py"]


def test_referenced_files_are_bounded(tmp_path: Path) -> None:
    files = {f"m{n}.py": "x = 1\n" for n in range(12)}
    ws = _ws(tmp_path, files)
    lines = "".join(f'  File "{ws.root / f"m{n}.py"}", line 1, in fn\n' for n in range(12))
    ev = _evidence(
        ws,
        stderr=lines + "ValueError: boom\n",
        limits=Limits(max_evidence_frames=50, max_referenced_files=4),
    )

    assert len(ev.referenced_files) == 4


# -- summary ----------------------------------------------------------------


def test_summary_names_the_exception_and_suspect(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"cart.py": "x = 1\n" * 30})
    summary = _evidence(ws, stderr=_traceback(ws.root)).summary

    assert "ValueError" in summary
    assert "cart.py:23" in summary


def test_summary_without_a_traceback_reports_the_exit_code(tmp_path: Path) -> None:
    summary = _evidence(_ws(tmp_path), stdout="nope\n", exit_code=3).summary

    assert "3" in summary


def test_summary_for_a_timeout_says_so(tmp_path: Path) -> None:
    summary = _evidence(_ws(tmp_path), exit_code=None, timed_out=True).summary

    assert "timed out" in summary.lower()


def test_summary_is_bounded(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    ev = _evidence(
        ws, stderr="ValueError: " + "q" * 4_000 + "\n", limits=Limits(max_evidence_text_chars=50)
    )

    assert len(ev.summary) <= 200


# -- serialization ----------------------------------------------------------


def test_evidence_serializes_to_json(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"cart.py": "x = 1\n" * 30})
    payload = _evidence(ws, stderr=_traceback(ws.root)).as_dict()

    assert json.loads(json.dumps(payload))["reproduced"] is True
    assert payload["frames"][0]["file"] == "cart.py"


def test_evidence_carries_no_reasoning_field(tmp_path: Path) -> None:
    """The evidence record holds observable facts only -- see state.py's rule."""
    payload = _evidence(_ws(tmp_path)).as_dict()
    forbidden = {"reasoning", "thinking", "analysis", "root_cause", "explanation"}

    assert forbidden.isdisjoint(payload)


def test_render_evidence_is_deterministic(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"cart.py": "x = 1\n" * 30})
    ev = _evidence(ws, stderr=_traceback(ws.root))

    assert render_evidence(ev) == render_evidence(ev)
    assert "cart.py:23" in render_evidence(ev)


# -- ordinary pytest failure output -----------------------------------------
#
# `pytest -q` does not print CPython's `File "...", line N, in fn` frames. It
# prints its own location lines, and a repro command that a person would
# actually type must produce usable evidence without special flags.

PYTEST_OUTPUT = (
    "F                                                                        [100%]\n"
    "=================================== FAILURES ===================================\n"
    "________________________ test_empty_cart_is_shipping_only ________________________\n"
    "\n"
    "    def test_empty_cart_is_shipping_only() -> None:\n"
    ">       assert cart_total([]) == SHIPPING_FLAT\n"
    "\n"
    "tests/test_cart.py:6: \n"
    "_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _\n"
    "cart.py:33: in cart_total\n"
    "    return round(subtotal + SHIPPING_FLAT - _discount(items), 2)\n"
    "cart.py:24: ValueError\n"
    "=========================== short test summary info ============================\n"
    "FAILED tests/test_cart.py::test_empty_cart_is_shipping_only - ValueError: min...\n"
)


def _pytest_ws(tmp_path: Path) -> Workspace:
    return _ws(
        tmp_path,
        {
            "cart.py": "x = 1\n" * 40,
            "tests/test_cart.py": "y = 2\n" * 20,
        },
    )


def test_ordinary_pytest_output_yields_in_workspace_frames(tmp_path: Path) -> None:
    ws = _pytest_ws(tmp_path)
    ev = _evidence(ws, stdout=PYTEST_OUTPUT)

    assert ev.frames != []
    assert ev.referenced_files != []
    assert "cart.py" in ev.referenced_files


def test_pytest_location_with_a_function_is_parsed(tmp_path: Path) -> None:
    ws = _pytest_ws(tmp_path)
    ev = _evidence(ws, stdout=PYTEST_OUTPUT)

    assert Frame(file="cart.py", line=33, function="cart_total") in ev.frames


def test_pytest_suspect_is_the_deepest_location(tmp_path: Path) -> None:
    """cart.py:24 is where it raised; that is the line worth reading first."""
    ws = _pytest_ws(tmp_path)
    ev = _evidence(ws, stdout=PYTEST_OUTPUT)

    assert ev.suspect is not None
    assert ev.suspect.file == "cart.py"
    assert ev.suspect.line == 24


def test_pytest_frames_keep_traceback_order(tmp_path: Path) -> None:
    ws = _pytest_ws(tmp_path)
    lines = [(f.file, f.line) for f in _evidence(ws, stdout=PYTEST_OUTPUT).frames]

    assert lines == [("tests/test_cart.py", 6), ("cart.py", 33), ("cart.py", 24)]


def test_pytest_exception_is_still_parsed(tmp_path: Path) -> None:
    ws = _pytest_ws(tmp_path)
    ev = _evidence(ws, stdout=PYTEST_OUTPUT)

    assert ev.exception_type == "ValueError"


def test_windows_separators_in_pytest_output_are_handled(tmp_path: Path) -> None:
    ws = _pytest_ws(tmp_path)
    # chr(92) is a literal backslash -- pytest prints Windows separators, and
    # writing it inline would be read as an escape by Python.
    text = "tests" + chr(92) + "test_cart.py:6: \ncart.py:24: ValueError\n"
    ev = _evidence(ws, stdout=text)

    assert ("tests/test_cart.py", 6) in [(f.file, f.line) for f in ev.frames]


def test_the_failed_summary_line_is_not_a_frame(tmp_path: Path) -> None:
    """`FAILED path::test - msg` names a file but is not a location."""
    ws = _pytest_ws(tmp_path)
    text = "FAILED tests/test_cart.py::test_empty_cart_is_shipping_only - ValueError: x\n"

    assert _evidence(ws, stdout=text).frames == []


# -- false positives --------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "cart.py:24: something went badly wrong here",  # prose after the colon
        "cart.py: ValueError",  # no line number
        "cart.py:notanumber: ValueError",  # line is not digits
        "12:30:45 cart.py started",  # a timestamp
        "note: see cart.py:24: for details",  # not at line start
        "config.yaml:10: ValueError",  # not a python source file
    ],
)
def test_colon_formatted_noise_is_not_a_frame(tmp_path: Path, line: str) -> None:
    ws = _pytest_ws(tmp_path)

    assert _evidence(ws, stdout=line + "\n").frames == []


def test_pytest_location_outside_the_workspace_is_rejected(tmp_path: Path) -> None:
    ws = _pytest_ws(tmp_path)
    text = (
        "../../../etc/secrets.py:3: in leak\n"
        "/usr/lib/python3.14/random.py:100: in choice\n"
        "cart.py:24: ValueError\n"
    )
    ev = _evidence(ws, stdout=text)

    assert [f.file for f in ev.frames] == ["cart.py"]


def test_pytest_location_naming_a_secret_file_is_rejected(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"cart.py": "x = 1\n" * 40, ".env": "ANTHROPIC_API_KEY=sk-live\n"})
    text = ".env:1: in load\ncart.py:24: ValueError\n"
    ev = _evidence(ws, stdout=text)

    assert [f.file for f in ev.frames] == ["cart.py"]
    assert ".env" not in ev.referenced_files


def test_pytest_location_for_a_missing_file_is_rejected(tmp_path: Path) -> None:
    ws = _pytest_ws(tmp_path)

    assert _evidence(ws, stdout="ghost.py:4: in vanished\n").frames == []


# -- the native parser is unchanged -----------------------------------------


def test_native_traceback_extraction_is_unchanged(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"cart.py": "x = 1\n" * 40})
    ev = _evidence(ws, stderr=_traceback(ws.root))

    assert ev.frames == [
        Frame(file="cart.py", line=11, function="cart_total"),
        Frame(file="cart.py", line=23, function="_discount"),
    ]
    assert ev.suspect == Frame(file="cart.py", line=23, function="_discount")


def test_native_frames_win_when_both_formats_are_present(tmp_path: Path) -> None:
    """Native frames name functions; the pytest form often cannot."""
    ws = _ws(tmp_path, {"cart.py": "x = 1\n" * 40})
    ev = _evidence(ws, stderr=_traceback(ws.root), stdout="cart.py:99: ValueError\n")

    assert [f.line for f in ev.frames] == [11, 23]
    assert all(f.function != "<unknown>" for f in ev.frames)
