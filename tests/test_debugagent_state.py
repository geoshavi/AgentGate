"""D1: the minimal Debug Agent state record.

Small on purpose. D1 owns exactly one decision -- did the reported failure
reproduce -- so the state it carries is the evidence for that decision, the
terminal status it implies, and the mutation ledger proving nothing was edited.
Everything else (plan, turns, root cause, verdict) belongs to later phases and
is deliberately absent rather than present-and-empty.
"""

import json
from pathlib import Path

from engine.codeagent.limits import Limits
from engine.codeagent.policy import DEFAULT_POLICY
from engine.codeagent.state import Phase, SessionStatus
from engine.codeagent.workspace import Workspace
from engine.debugagent.repro import freeze_repro, reproduce
from engine.debugagent.state import DebugState

FAILING = "raise ValueError('boom')\n"
PASSING = "print('ok')\n"


def _ws(tmp_path: Path, files: dict[str, str]) -> Workspace:
    root = tmp_path / "ws"
    root.mkdir(exist_ok=True)
    for relative, content in files.items():
        (root / relative).write_text(content, encoding="utf-8")
    return Workspace(root)


def _state(tmp_path: Path, script: str) -> DebugState:
    ws = _ws(tmp_path, {"s.py": script})
    repro = freeze_repro(["python", "s.py"])
    outcome = reproduce(
        repro=repro, workspace=ws, policy=DEFAULT_POLICY, limits=Limits(repro_timeout_seconds=30)
    )
    return DebugState.from_repro(task_id="dbg-test", workspace=ws, repro=repro, outcome=outcome)


def test_reproduced_state_is_running_and_says_so(tmp_path: Path) -> None:
    state = _state(tmp_path, FAILING)

    assert state.reproduced is True
    assert state.status is SessionStatus.RUNNING
    assert state.phase is Phase.REPRODUCING


def test_not_reproduced_state_is_terminal(tmp_path: Path) -> None:
    state = _state(tmp_path, PASSING)

    assert state.reproduced is False
    assert state.status is SessionStatus.ABORTED_NO_REPRO


def test_state_records_zero_files_changed(tmp_path: Path) -> None:
    assert _state(tmp_path, PASSING).files_changed == []
    assert _state(tmp_path, FAILING).files_changed == []


def test_state_records_the_frozen_argv(tmp_path: Path) -> None:
    assert _state(tmp_path, FAILING).repro_argv == ["python", "s.py"]


def test_state_serializes_to_json(tmp_path: Path) -> None:
    payload = json.loads(_state(tmp_path, FAILING).to_json())

    assert payload["status"] == "RUNNING"
    assert payload["phase"] == "REPRODUCING"
    assert payload["reproduced"] is True
    assert payload["evidence"]["exception_type"] == "ValueError"


def test_aborted_state_serializes_the_terminal_status(tmp_path: Path) -> None:
    payload = json.loads(_state(tmp_path, PASSING).to_json())

    assert payload["status"] == "ABORTED_NO_REPRO"
    assert payload["reproduced"] is False


def test_state_carries_no_reasoning_or_verdict_fields(tmp_path: Path) -> None:
    """D1 has no model and no verdict; the shape must not imply otherwise."""
    payload = _state(tmp_path, FAILING).to_dict()
    forbidden = {"reasoning", "thinking", "root_cause", "verification_status", "defects"}

    assert forbidden.isdisjoint(payload)


def test_denied_repro_state_has_no_evidence(tmp_path: Path) -> None:
    """Nothing ran, so an evidence record would be a fabrication."""
    ws = _ws(tmp_path, {"s.py": FAILING})
    repro = freeze_repro(["curl", "http://example.com"])
    outcome = reproduce(repro=repro, workspace=ws, policy=DEFAULT_POLICY, limits=Limits())
    state = DebugState.from_repro(
        task_id="dbg-denied", workspace=ws, repro=repro, outcome=outcome
    )

    assert state.status is SessionStatus.ABORTED_NO_REPRO
    assert state.evidence is None
    assert state.to_dict()["evidence"] is None
