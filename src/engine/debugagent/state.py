"""Minimal Debug Agent state for D1.

D1 answers exactly one question -- did the reported failure reproduce -- so this
record carries the evidence for that answer, the terminal status it implies, and
the mutation ledger proving nothing was edited on the way. Fields for a plan,
turns, a root cause or a verdict are **absent rather than present-and-empty**:
an empty ``verification_status`` in a D1 report would read as "verification ran
and found nothing", which is the exact confusion ``codeagent/state.py`` added
``COMPLETED_UNVERIFIED`` to avoid.

Observable facts only. There is no field for reasoning and no code path that
could write one, matching the rule the Coding Agent's state module set.
"""

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from engine.codeagent.state import Phase, SessionStatus
from engine.codeagent.workspace import Workspace
from engine.debugagent.repro import FrozenRepro, ReproOutcome
from engine.debugagent.rootcause import DiagnosisOutcome


@dataclass
class DebugState:
    """Where a debug run stands after the reproduction gate.

    ``status`` is ``RUNNING`` when the failure reproduced -- the run may
    continue into later phases -- and ``ABORTED_NO_REPRO`` when it did not.
    There is no third possibility, which is the gate's entire contract.
    """

    task_id: str
    workspace: str
    repro_argv: list[str]
    status: SessionStatus
    phase: Phase = Phase.REPRODUCING
    reproduced: bool = False
    repro_status: str = ""
    reason: str = ""
    evidence: dict[str, Any] | None = None
    files_changed: list[str] = field(default_factory=list)

    # Diagnosis (D2). ``diagnosis_status`` is "" only when diagnosis was never
    # attempted -- never as a stand-in for a failure, which has its own status.
    diagnosis_status: str = ""
    diagnosis_attempts: int = 0
    diagnosis_errors: list[str] = field(default_factory=list)
    root_cause: dict[str, Any] | None = None
    inspected_files: list[str] = field(default_factory=list)
    # Usage, totalled across every diagnosis attempt. Sourced from the gateway's
    # own GenerationResult; thinking_tokens is a count, never reasoning text.
    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0

    @classmethod
    def from_repro(
        cls,
        *,
        task_id: str,
        workspace: Workspace,
        repro: FrozenRepro,
        outcome: ReproOutcome,
    ) -> "DebugState":
        """Build the state implied by one gate outcome.

        ``files_changed`` is read from the workspace ledger rather than assumed
        to be empty. D1 never writes, so it is always empty in practice -- and
        reading it is what turns that from a claim into an assertion the tests
        can make.
        """
        terminal = outcome.terminal_status
        return cls(
            task_id=task_id,
            workspace=str(workspace.root),
            repro_argv=repro.as_list(),
            status=SessionStatus.RUNNING if terminal is None else terminal,
            phase=Phase.REPRODUCING,
            reproduced=outcome.reproduced,
            repro_status=outcome.status.value,
            reason=outcome.reason,
            evidence=None if outcome.evidence is None else outcome.evidence.as_dict(),
            files_changed=workspace.changed_files,
        )

    def record_diagnosis(self, outcome: DiagnosisOutcome) -> None:
        """Fold a diagnosis outcome into the state.

        A failed diagnosis moves the status to ``ABORTED_NO_ROOT_CAUSE`` but
        leaves ``reproduced`` and ``evidence`` exactly as they were. Losing the
        hypothesis must not lose the reproduction that earned it -- the evidence
        is the expensive, deterministic part, and it stays true regardless of
        what any model failed to conclude about it.
        """
        self.phase = Phase.DIAGNOSING
        self.diagnosis_status = outcome.status.value
        self.diagnosis_attempts = outcome.attempts
        self.diagnosis_errors = list(outcome.errors)
        self.root_cause = None if outcome.root_cause is None else outcome.root_cause.as_dict()
        self.inspected_files = list(outcome.inspected_files)
        self.model_calls = outcome.model_calls
        self.input_tokens = outcome.input_tokens
        self.output_tokens = outcome.output_tokens
        self.thinking_tokens = outcome.thinking_tokens
        terminal = outcome.terminal_status
        if terminal is not None:
            self.status = terminal

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "workspace": self.workspace,
            "repro_argv": list(self.repro_argv),
            "status": _value(self.status),
            "phase": _value(self.phase),
            "reproduced": self.reproduced,
            "repro_status": self.repro_status,
            "reason": self.reason,
            "evidence": self.evidence,
            "files_changed": list(self.files_changed),
            "diagnosis_status": self.diagnosis_status,
            "diagnosis_attempts": self.diagnosis_attempts,
            "diagnosis_errors": list(self.diagnosis_errors),
            "root_cause": self.root_cause,
            "inspected_files": list(self.inspected_files),
            "model_calls": self.model_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "thinking_tokens": self.thinking_tokens,
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=False)


def _value(item: Any) -> Any:
    return item.value if isinstance(item, Enum) else item


__all__ = ["DebugState"]
