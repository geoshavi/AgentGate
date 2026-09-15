"""Deterministic conformance tests for Dataset v5 amendments A-4 and A-5
(docs/benchmark/DATASET_V5_AMENDMENT.md). Each test executes the actual
fixture source stored in dataset.py -- not a reimplementation -- so a
regression in the stored snippet fails here directly.
"""

import subprocess

import pytest

from engine.eval.dataset import TASKS


def _task(task_id: str):
    return next(t for t in TASKS if t.task_id == task_id)


def _load(source: str, name: str, label: str):
    namespace: dict[str, object] = {}
    exec(compile(source, f"<{label}>", "exec"), namespace)  # noqa: S102
    return namespace[name]


CORRECTNESS_02 = _task("correctness-02")
SECURITY_02 = _task("security-02")


def _is_close_enough_clean():
    return _load(
        CORRECTNESS_02.clean_files["solution.py"], "is_close_enough", "correctness-02-clean"
    )


def _is_close_enough_broken():
    return _load(
        CORRECTNESS_02.broken_files["solution.py"], "is_close_enough", "correctness-02-broken"
    )


# ------------------------------------------------------------- A-4: correctness-02

# The 12 registered vectors from DATASET_V5_AMENDMENT.md, exact decimal-value expectations.
A4_VECTORS = [
    (1.0, 1.0, True),
    (0.03, 0.02, False),
    (0.02, 0.03, False),
    (1.01, 1.0, False),
    (-0.03, -0.02, False),
    (-0.005, 0.005, False),
    (0.0, 0.009, True),
    (0.0, 0.009999, True),
    (0.0, 0.010001, False),
    (1.0, 1.001, True),
    (0.0, 0.02, False),
    (1000000000000.01, 1000000000000.0, False),
]


@pytest.mark.parametrize("a,b,expected", A4_VECTORS)
def test_a4_correctness_02_clean_matches_registered_vectors(a: float, b: float, expected: bool) -> None:
    fn = _is_close_enough_clean()
    assert fn(a, b) is expected
    assert fn(b, a) is expected  # symmetric


def test_a4_correctness_02_clean_exact_one_cent_boundary_is_false() -> None:
    fn = _is_close_enough_clean()
    assert fn(1.0, 1.01) is False
    assert fn(0.03, 0.02) is False  # the float-subtraction defect case from the amendment


def test_a4_correctness_02_clean_just_below_boundary_is_true() -> None:
    fn = _is_close_enough_clean()
    assert fn(0.0, 0.0099) is True
    assert fn(1.0, 1.0099) is True


def test_a4_correctness_02_clean_just_above_boundary_is_false() -> None:
    fn = _is_close_enough_clean()
    assert fn(0.0, 0.0101) is False
    assert fn(1.0, 1.0101) is False


def test_a4_correctness_02_clean_rejects_round_after_subtraction_behavior() -> None:
    # round(abs(a - b), 2) would turn 0.009 into 0.01 and incorrectly return False.
    fn = _is_close_enough_clean()
    assert fn(0.0, 0.009) is True


def test_a4_correctness_02_broken_contrast_preserved() -> None:
    # a == b: a genuinely close pair that isn't bit-identical must still fail.
    fn = _is_close_enough_broken()
    assert fn(1.0, 1.001) is False


# ------------------------------------------------------------- A-5: security-02

def _convert_to_png_clean():
    return _load(SECURITY_02.clean_files["solution.py"], "convert_to_png", "security-02-clean")


def _convert_to_png_broken():
    return _load(SECURITY_02.broken_files["solution.py"], "convert_to_png", "security-02-broken")


A5_ACCEPTED = ["photo.jpg", "scan_1.png", "image-2.jpeg", "a.b.png"]

A5_REJECTED = [
    "",
    "-help",
    "../photo.jpg",
    "dir/photo.jpg",
    "dir\\photo.jpg",
    "a..b.png",
    "https:photo",
    "@list",
    "a[0].png",
    "a b.png",
    "a;echo.png",
    "a|b.png",
    "$(echo).png",
    "a\nb.png",
    "a\x00b.png",
]


@pytest.mark.parametrize("filename", A5_ACCEPTED)
def test_a5_security_02_clean_accepts_and_uses_literal_operands(
    filename: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    fn = _convert_to_png_clean()
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    fn(filename)

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == ["/usr/bin/convert", filename, f"{filename}.png"]
    assert kwargs.get("shell", False) is False


@pytest.mark.parametrize("filename", A5_REJECTED)
def test_a5_security_02_clean_rejects_unsafe_input_with_zero_process_invocations(
    filename: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    fn = _convert_to_png_clean()
    calls: list[object] = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append((a, k)))

    with pytest.raises(ValueError):
        fn(filename)

    assert calls == []


def test_a5_security_02_broken_contrast_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    # The broken fixture still invokes a process (via a shell string) for input containing
    # forbidden metacharacters -- observed only through a process double, never executed.
    fn = _convert_to_png_broken()
    calls: list[tuple[object, dict[str, object]]] = []

    def fake_run(cmd: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0)  # type: ignore[arg-type]

    monkeypatch.setattr(subprocess, "run", fake_run)
    fn("a;echo pwned.png")

    assert len(calls) == 1
    assert calls[0][1].get("shell") is True
