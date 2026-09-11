"""Whether a blocking defect is admissible to block.

This layer may only ever *remove* blocking authority, and only from a defect
that is already CRITICAL or HIGH. It never reads severity for any purpose other
than deciding whether a defect is in scope at all, and it never writes severity.
An inadmissible finding stays in ``merged["defects"]``, stays in the report, and
stays in retry feedback -- only its contribution to ``verdict._has_blocking``
is dropped.

Every uncertain path ends at ``fail-closed-unresolved``, which is admissible.
Withholding evidence therefore buys a judge nothing.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from engine.verification.adjudication import (
    ADJUDICATOR_VERSION,
    CONTRADICTED,
    VERIFIED,
    Adjudication,
    Evidence,
    adjudicate,
    extract_evidence,
)
from engine.verification.rubric import BLOCKING

_STATED_PURPOSE = "stated_purpose"


@dataclass(frozen=True)
class Decision:
    admissible: bool | None  # None -> not applicable (defect is not blocking)
    rule: str
    reason: str


_NOT_APPLICABLE = Decision(None, "not-applicable", "severity is not blocking")


def _from_facts(adj: Adjudication, evidence: Evidence) -> Decision:
    # A purpose-grounded finding is never suppressed. Establishing that a stated
    # purpose does *not* imply an obligation is a semantic judgment, and nothing
    # here can make it deterministically.
    if evidence.grounding_route == _STATED_PURPOSE:
        return Decision(True, "stated-purpose-protected", "purpose-grounded findings always block")

    if adj.trigger_in_contract.status == CONTRADICTED:
        return Decision(False, "declared-interface", adj.trigger_in_contract.detail)

    if adj.premise_excluded_by_guarantee.status == VERIFIED:
        return Decision(False, "explicit-guarantee", adj.premise_excluded_by_guarantee.detail)

    if adj.violation_present_in_submitted_code.status == CONTRADICTED:
        return Decision(False, "factual-premise", adj.violation_present_in_submitted_code.detail)

    # Note: a self-retraction marker is recorded on the adjudication but never
    # acted on here. The frozen spec only lets a retraction remove authority
    # when the *source* corroborates it, and corroborating that is not something
    # this layer can do. Until it can, retraction fails safe.
    return Decision(True, "fail-closed-unresolved", "no deterministic contradiction established")


def decide(defect: dict, task_text: str, code_snapshot: str) -> Decision:
    """Decide one defect. Only CRITICAL/HIGH defects are evaluated at all."""
    if not isinstance(defect, dict) or defect.get("severity") not in BLOCKING:
        return _NOT_APPLICABLE
    evidence = extract_evidence(defect)
    return _from_facts(adjudicate(defect, evidence, task_text, code_snapshot), evidence)


def annotate(merged: dict, task_text: str, code_snapshot: str) -> dict:
    """Return a copy of ``merged`` whose defects carry an admissibility verdict.

    The input is never mutated: callers downstream of this still see exactly the
    dict they passed in, and the annotated copy is what reaches ``verdict.gate``.
    """
    defects = []
    for defect in merged.get("defects", []) or []:
        if not isinstance(defect, dict):
            defects.append(defect)
            continue
        decision = decide(defect, task_text, code_snapshot)
        defects.append(
            {
                **defect,
                "admissible_to_block": decision.admissible,
                "admissibility_rule": decision.rule,
                "admissibility_reason": decision.reason,
            }
        )
    return {**merged, "defects": defects}


def adjudication_record(defect: dict, lens: str, task_text: str, code_snapshot: str) -> dict:
    """Build the forensic row for one defect. Original evidence is never overwritten."""
    evidence = extract_evidence(defect)
    adj = adjudicate(defect, evidence, task_text, code_snapshot)
    # Same severity scope as decide(): a defect that is not blocking is never
    # evaluated, and its record says so with a NULL rather than claiming it is
    # "admissible to block". The facts above are still recorded for it, because
    # evidence availability is measured over every defect, not just blockers.
    decision = (
        _from_facts(adj, evidence)
        if defect.get("severity") in BLOCKING
        else _NOT_APPLICABLE
    )
    probe = adj.probe

    return {
        "lens": lens,
        "defect_id": str(defect.get("id", "")),
        "original_severity": str(defect.get("severity", "")),
        "evidence_json": json.dumps(asdict(evidence), sort_keys=True),
        "adjudication_json": json.dumps(
            {
                name: asdict(getattr(adj, name))
                for name in (
                    "trigger_in_contract",
                    "premise_excluded_by_guarantee",
                    "premise_depends_on_runtime_behaviour",
                    "violation_present_in_submitted_code",
                    "self_contradiction",
                )
            },
            sort_keys=True,
        ),
        "admissible_to_block": decision.admissible,
        "rule": decision.rule,
        "reason": decision.reason,
        "probe_predicate": probe.predicate if probe else None,
        "probe_argument": probe.argument if probe else None,
        "probe_result": json.dumps(probe.value) if probe else None,
        "probe_interpreter_version": probe.interpreter_version if probe else None,
        "adjudicator_version": ADJUDICATOR_VERSION,
    }
