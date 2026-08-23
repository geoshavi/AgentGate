"""D1: the reproduction gate.

The rule this suite exists to prove: **the Debug Agent never edits code unless
the reported failure was first observed.** Every path that fails to reproduce --
a passing command, a timeout, a policy refusal, a missing program -- must reach
``ABORTED_NO_REPRO`` with an empty mutation ledger.

Offline by construction: no gateway, no provider, no key. The commands executed
are real subprocesses, because the point of the gate is that it ran something.
"""

import dataclasses
import subprocess
from pathlib import Path

import pytest

from engine.codeagent.limits import Limits
from engine.codeagent.policy import DEFAULT_POLICY
from engine.codeagent.state import SessionStatus
from engine.codeagent.workspace import Workspace
from engine.debugagent.repro import (
    FrozenRepro,
    ReproStatus,
    freeze_repro,
    reproduce,
)

# A script that fails with a real traceback, and one that passes.
FAILING = (
    "def _discount(items):\n"
    "    return min(i for i in items)\n"
    "\n"
    "\n"
    "def main():\n"
    "    return _discount([])\n"
    "\n"
    "\n"
    "main()\n"
)
PASSING = "print('all good')\n"
HANGING = "import time\ntime.sleep(30)\n"


def _ws(tmp_path: Path, files: dict[str, str] | None = None) -> Workspace:
    root = tmp_path / "ws"
    root.mkdir(exist_ok=True)
    for relative, content in (files or {}).items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return Workspace(root)


def _run(ws: Workspace, argv: list[str], **limit_overrides: object):
    return reproduce(
        repro=freeze_repro(argv),
        workspace=ws,
        policy=DEFAULT_POLICY,
        limits=Limits(**limit_overrides),  # type: ignore[arg-type]
    )


# -- the gate ---------------------------------------------------------------


def test_failing_command_is_reproduced(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"bug.py": FAILING})
    outcome = _run(ws, ["python", "bug.py"])

    assert outcome.status is ReproStatus.REPRODUCED
    assert outcome.reproduced is True
    assert outcome.evidence is not None
    assert outcome.evidence.exit_code != 0
    assert outcome.terminal_status is None


def test_reproduced_failure_captures_its_traceback(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"bug.py": FAILING})
    evidence = _run(ws, ["python", "bug.py"]).evidence

    assert evidence is not None
    assert evidence.exception_type == "ValueError"
    # Outermost first, deepest last -- the ordering `suspect` depends on.
    assert [f.function for f in evidence.frames] == ["<module>", "main", "_discount"]
    assert {f.file for f in evidence.frames} == {"bug.py"}
    assert evidence.suspect is not None
    assert evidence.suspect.function == "_discount"
    assert evidence.referenced_files == ["bug.py"]


def test_passing_command_aborts_no_repro(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"fine.py": PASSING})
    outcome = _run(ws, ["python", "fine.py"])

    assert outcome.status is ReproStatus.NOT_REPRODUCED
    assert outcome.reproduced is False
    assert outcome.terminal_status is SessionStatus.ABORTED_NO_REPRO


def test_timeout_aborts_no_repro(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"hang.py": HANGING})
    outcome = _run(ws, ["python", "hang.py"], repro_timeout_seconds=0.5)

    assert outcome.status is ReproStatus.TIMED_OUT
    assert outcome.terminal_status is SessionStatus.ABORTED_NO_REPRO
    assert outcome.evidence is not None
    assert outcome.evidence.timed_out is True
    assert outcome.evidence.reproduced is False


def test_policy_denied_command_aborts_no_repro(tmp_path: Path) -> None:
    outcome = _run(_ws(tmp_path), ["curl", "https://example.com"])

    assert outcome.status is ReproStatus.DENIED
    assert outcome.terminal_status is SessionStatus.ABORTED_NO_REPRO
    assert "curl" in outcome.reason


def test_shell_string_repro_is_denied(tmp_path: Path) -> None:
    """argv lists only -- a shell string must never become a command."""
    outcome = _run(_ws(tmp_path), ["python", "-c", "import os; os.system('rm -rf /')"])

    assert outcome.status is ReproStatus.DENIED
    assert outcome.terminal_status is SessionStatus.ABORTED_NO_REPRO


def test_git_write_subcommand_repro_is_denied(tmp_path: Path) -> None:
    outcome = _run(_ws(tmp_path), ["git", "push"])

    assert outcome.status is ReproStatus.DENIED
    assert outcome.terminal_status is SessionStatus.ABORTED_NO_REPRO


def test_missing_program_aborts_no_repro(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An allowlisted program that is not installed must not look like a pass."""
    from engine.codeagent.tools import shell

    def _boom(*args: object, **kwargs: object) -> object:
        raise FileNotFoundError("pytest not installed")

    monkeypatch.setattr(shell.subprocess, "run", _boom)
    outcome = _run(_ws(tmp_path), ["pytest", "-q"])

    assert outcome.status is ReproStatus.UNAVAILABLE
    assert outcome.terminal_status is SessionStatus.ABORTED_NO_REPRO
    assert outcome.evidence is not None
    assert outcome.evidence.reproduced is False


@pytest.mark.parametrize(
    "argv",
    [["python", "fine.py"], ["curl", "x"], ["git", "push"], ["python", "hang.py"]],
)
def test_no_files_are_changed_when_repro_is_not_established(
    tmp_path: Path, argv: list[str]
) -> None:
    """The whole point of the gate: no edit without observed evidence."""
    ws = _ws(tmp_path, {"fine.py": PASSING, "hang.py": HANGING})
    outcome = reproduce(
        repro=freeze_repro(argv),
        workspace=ws,
        policy=DEFAULT_POLICY,
        limits=Limits(repro_timeout_seconds=0.5),
    )

    assert outcome.reproduced is False
    assert ws.changed_files == []


def test_reproduction_changes_no_files_either(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"bug.py": FAILING})
    _run(ws, ["python", "bug.py"])

    assert ws.changed_files == []


def test_repro_runs_inside_the_workspace(tmp_path: Path) -> None:
    """cwd is the workspace, so a relative script path resolves."""
    ws = _ws(tmp_path, {"sub/deep.py": FAILING})
    outcome = _run(ws, ["python", "sub/deep.py"])

    assert outcome.status is ReproStatus.REPRODUCED


def test_repro_output_is_bounded(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"loud.py": "for n in range(20000):\n    print('noise', n)\nraise SystemExit(1)\n"})
    outcome = _run(ws, ["python", "loud.py"], max_repro_output_bytes=200)

    assert outcome.evidence is not None
    assert len(outcome.evidence.stdout_tail) <= 200


def test_child_environment_has_no_api_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The repro runs through the same scrubbed environment as every command."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-leak")
    ws = _ws(
        tmp_path,
        {"leak.py": "import os\nprint('KEY=' + os.environ.get('ANTHROPIC_API_KEY', 'ABSENT'))\nraise SystemExit(1)\n"},
    )
    outcome = _run(ws, ["python", "leak.py"])

    assert outcome.evidence is not None
    assert "KEY=ABSENT" in outcome.evidence.stdout_tail
    assert "sk-should-not-leak" not in outcome.evidence.stdout_tail


# -- the frozen command -----------------------------------------------------


def test_frozen_repro_rejects_an_empty_argv() -> None:
    with pytest.raises(ValueError):
        freeze_repro([])


def test_frozen_repro_rejects_a_shell_string() -> None:
    with pytest.raises(TypeError):
        freeze_repro("python -m pytest")  # type: ignore[arg-type]


def test_frozen_repro_rejects_non_string_items() -> None:
    with pytest.raises(TypeError):
        freeze_repro(["python", 3])  # type: ignore[list-item]


def test_frozen_argv_cannot_be_mutated_through_the_returned_list() -> None:
    frozen = freeze_repro(["python", "-m", "pytest", "-q", "test_x.py::test_y"])

    borrowed = frozen.as_list()
    borrowed.append("--deselect")
    borrowed[0] = "rm"

    assert frozen.as_list() == ["python", "-m", "pytest", "-q", "test_x.py::test_y"]


def test_frozen_argv_is_unaffected_by_mutating_the_source_list() -> None:
    source = ["python", "bug.py"]
    frozen = freeze_repro(source)
    source.append("--narrow")

    assert frozen.as_list() == ["python", "bug.py"]


def test_frozen_repro_is_immutable() -> None:
    frozen = freeze_repro(["python", "bug.py"])

    with pytest.raises(dataclasses.FrozenInstanceError):
        frozen.argv = ("rm", "-rf")  # type: ignore[misc]


def test_evidence_records_the_frozen_argv(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"bug.py": FAILING})
    outcome = _run(ws, ["python", "bug.py"])

    assert outcome.evidence is not None
    assert outcome.evidence.argv == ["python", "bug.py"]


def test_frozen_repro_equality_is_by_value() -> None:
    assert freeze_repro(["python", "a.py"]) == freeze_repro(["python", "a.py"])
    assert freeze_repro(["python", "a.py"]) != freeze_repro(["python", "b.py"])


# -- D1 makes no model call -------------------------------------------------


def test_d1_modules_cannot_reach_a_model_or_provider() -> None:
    """Structural proof, not a promise: D1 imports no gateway, budget or SDK."""
    import ast

    from engine import debugagent

    root = Path(debugagent.__file__).parent
    banned = ("engine.runtime", "engine.providers", "anthropic", "openai", "httpx")
    violations: list[str] = []

    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                if name.startswith(banned):
                    violations.append(f"{path.name}: {name}")

    assert violations == []


def test_reproduce_needs_no_gateway_argument() -> None:
    """The signature itself makes a model call impossible in D1."""
    import inspect

    params = set(inspect.signature(reproduce).parameters)

    assert {"gateway", "model", "budget", "conn"}.isdisjoint(params)


def test_frozen_repro_is_exported() -> None:
    assert FrozenRepro is not None
    assert subprocess is not None  # import kept meaningful for the monkeypatch test
