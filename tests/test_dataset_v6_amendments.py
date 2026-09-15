"""Deterministic conformance tests for Dataset v6 amendment A-6
(docs/benchmark/DATASET_V6_AMENDMENT.md). Executes the actual security-02-clean
fixture source stored in dataset.py -- not a reimplementation -- so a
regression in the stored snippet fails here directly.

Reuses A-5's accept/reject vector sets from test_dataset_v5_amendments.py
rather than duplicating them: A-6 changes process-invocation filesystem
semantics only, so the filename-grammar/injection contract those vectors
exercise is unchanged and must keep passing unmodified.
"""

import subprocess

import pytest
from test_dataset_v5_amendments import A5_ACCEPTED, A5_REJECTED

from engine.eval.dataset import TASKS


def _load(source: str, name: str, label: str):
    namespace: dict[str, object] = {}
    exec(compile(source, f"<{label}>", "exec"), namespace)  # noqa: S102
    return namespace[name]


SECURITY_02 = next(t for t in TASKS if t.task_id == "security-02")


def _convert_to_png_clean():
    return _load(SECURITY_02.clean_files["solution.py"], "convert_to_png", "security-02-clean")


def _convert_to_png_broken():
    return _load(SECURITY_02.broken_files["solution.py"], "convert_to_png", "security-02-broken")


A6_WORKING_DIR = "/srv/app/images"


@pytest.mark.parametrize("filename", A5_ACCEPTED)
def test_a6_security_02_clean_accepted_filenames_use_registered_working_dir(
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
    # argv shape is byte-identical to A-5's registered form -- A-6 changes only
    # filesystem resolution, never the operands or executable path.
    assert args == ["/usr/bin/convert", filename, f"{filename}.png"]
    assert kwargs.get("cwd") == A6_WORKING_DIR
    assert kwargs.get("shell", False) is not True


@pytest.mark.parametrize("filename", A5_REJECTED)
def test_a6_security_02_clean_rejected_filenames_still_cause_zero_invocations(
    filename: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    fn = _convert_to_png_clean()
    calls: list[object] = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append((a, k)))

    with pytest.raises(ValueError):
        fn(filename)

    assert calls == []


def test_a6_security_02_broken_contrast_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    # A-6 does not touch the broken fixture: it must still shell out on
    # forbidden metacharacters, observed only through a process double.
    fn = _convert_to_png_broken()
    calls: list[tuple[object, dict[str, object]]] = []

    def fake_run(cmd: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0)  # type: ignore[arg-type]

    monkeypatch.setattr(subprocess, "run", fake_run)
    fn("a;echo pwned.png")

    assert len(calls) == 1
    assert calls[0][1].get("shell") is True
