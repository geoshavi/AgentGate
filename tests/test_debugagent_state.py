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
    """No hidden reasoning, and no verdict -- the Debug Agent does not verify.

    ``root_cause`` is deliberately NOT forbidden: it is a schema-validated
    structure whose every field survived validation, which is the opposite of
    unstructured model prose. What must never appear is free reasoning text or
    a verification field the Debug Agent has no standing to fill.
    """
    payload = _state(tmp_path, FAILING).to_dict()
    forbidden = {"reasoning", "thinking", "analysis", "verification_status", "defects"}

    assert forbidden.isdisjoint(payload)
    # Before diagnosis runs, the field exists but is honestly empty.
    assert payload["root_cause"] is None
    assert payload["diagnosis_status"] == ""


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


# -- D2: diagnosis recording ------------------------------------------------


def _diagnosed(tmp_path: Path, *, valid: bool = True) -> DebugState:
    """A state carrying a real gate outcome plus a scripted diagnosis."""
    import json as _json
    from decimal import Decimal

    from codeagent_harness import MODEL, ScriptedProvider

    from engine.debugagent.rootcause import diagnose
    from engine.runtime.budget import BudgetController
    from engine.runtime.gateway import LLMGateway

    ws = _ws(tmp_path, {"s.py": "raise ValueError('boom')\n"})
    repro = freeze_repro(["python", "s.py"])
    outcome = reproduce(repro=repro, workspace=ws, policy=DEFAULT_POLICY, limits=Limits())
    assert outcome.evidence is not None

    body = _json.dumps(
        {
            "summary": "unconditional raise",
            "mechanism": "the module raises at import time",
            "primary_file": "s.py",
            "primary_line": 1,
            "proposed_fix": "guard the raise",
            "validation_plan": [["python", "-m", "pytest", "-q"]],
        }
    )
    response = f"```rootcause\n{body}\n```" if valid else "no block here"

    diagnosis = diagnose(
        task_text="s.py explodes",
        evidence=outcome.evidence,
        repro=repro,
        workspace=ws,
        gateway=LLMGateway(ScriptedProvider([response])),
        budget=BudgetController(max_tokens=1_000_000, planned_budget=Decimal("10.00")),
        model=MODEL,
        task_id="dbg-state",
        limits=Limits(),
    )
    state = DebugState.from_repro(
        task_id="dbg-state", workspace=ws, repro=repro, outcome=outcome
    )
    state.record_diagnosis(diagnosis)
    return state


def test_diagnosis_records_the_root_cause(tmp_path: Path) -> None:
    state = _diagnosed(tmp_path)

    assert state.diagnosis_status == "OK"
    assert state.root_cause is not None
    assert state.root_cause["primary_file"] == "s.py"
    assert state.root_cause["confidence"] == "OBSERVED"


def test_diagnosis_records_attempts_and_inspected_files(tmp_path: Path) -> None:
    state = _diagnosed(tmp_path)

    assert state.diagnosis_attempts == 1
    assert state.inspected_files == ["s.py"]


def test_diagnosis_records_usage_counts(tmp_path: Path) -> None:
    state = _diagnosed(tmp_path)

    assert state.input_tokens > 0
    assert state.output_tokens > 0


def test_failed_diagnosis_is_terminal_and_records_errors(tmp_path: Path) -> None:
    state = _diagnosed(tmp_path, valid=False)

    assert state.status is SessionStatus.ABORTED_NO_ROOT_CAUSE
    assert state.root_cause is None
    assert state.diagnosis_errors != []
    assert state.phase is Phase.DIAGNOSING


def test_failed_diagnosis_preserves_d1_evidence(tmp_path: Path) -> None:
    """Losing the diagnosis must not lose the reproduction that earned it."""
    state = _diagnosed(tmp_path, valid=False)

    assert state.reproduced is True
    assert state.evidence is not None
    assert state.evidence["exception_type"] == "ValueError"


def test_diagnosis_changes_no_files(tmp_path: Path) -> None:
    assert _diagnosed(tmp_path).files_changed == []
    assert _diagnosed(tmp_path, valid=False).files_changed == []


def test_diagnosed_state_serializes(tmp_path: Path) -> None:
    payload = json.loads(_diagnosed(tmp_path).to_json())

    assert payload["diagnosis_status"] == "OK"
    assert payload["root_cause"]["primary_line"] == 1
    assert payload["phase"] == "DIAGNOSING"


def test_state_records_model_call_count_and_thinking_tokens(tmp_path: Path) -> None:
    state = _diagnosed(tmp_path)

    assert state.model_calls == 1
    assert state.thinking_tokens == 0  # ScriptedProvider does not report them


def test_state_usage_survives_serialization(tmp_path: Path) -> None:
    payload = json.loads(_diagnosed(tmp_path).to_json())

    assert payload["model_calls"] == 1
    assert payload["input_tokens"] > 0
    assert payload["thinking_tokens"] == 0
