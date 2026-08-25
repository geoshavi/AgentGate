"""What a static-analysis run found, and what it is allowed to claim.

A value, not a decision -- the same contract ``capabilities/testenv/models.py``
holds to. ``AnalysisRun`` records what was executed and what came back; nothing
here decides anything, and nothing downstream is obliged to act on it. AgentGate
verdicts, judge lenses, severity thresholds and the Debug Agent's frozen
reproduction and suite are settled by other components entirely and never consult
this value.

**A finding's severity is Semgrep's word, not AgentGate's.** The string is
carried through verbatim and deliberately never mapped onto
``verification/rubric.py``'s severity scale: two vocabularies that look alike are
exactly how advisory evidence turns into a verdict input by accident.

``as_dict`` is metadata only -- counts, rule ids, exit status, timing. No
message, no file content, no raw tool output. A report should be able to say what
was run and what came back without becoming a transcript of the analyser.
"""

from collections.abc import Mapping
from dataclasses import dataclass

# Severities Semgrep emits, ordered most serious first. Used only for
# presentation and counting; no threshold anywhere is derived from it.
SEVERITY_ORDER = ("ERROR", "WARNING", "INFO")


@dataclass(frozen=True)
class AnalysisFinding:
    """One finding, already bounded.

    ``message`` is **untrusted text**: it comes from a rule file and quotes
    nothing from the scanned source. ``path`` is workspace-relative, because an
    absolute one would put this machine's directory layout into a report.
    """

    rule_id: str
    severity: str
    path: str
    line: int
    message: str


@dataclass(frozen=True)
class AnalysisRun:
    """One analyser invocation, whatever became of it.

    ``ok`` is not "no findings were reported" -- findings are the successful
    case. It means the analyser ran and produced a result that could be read.
    ``available`` is False only when the program itself could not be started,
    which is a different fact from a run that failed, and a report keeps them
    apart.
    """

    tool: str
    target: str
    ruleset: str = ""
    available: bool = True
    exit_code: int | None = None
    timed_out: bool = False
    duration_ms: int = 0
    findings: tuple[AnalysisFinding, ...] = ()
    findings_total: int = 0
    findings_truncated: bool = False
    scan_errors: int = 0
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.available and not self.timed_out

    def severity_counts(self) -> dict[str, int]:
        """Counts over the findings actually reported, in a stable key order."""
        counts: dict[str, int] = {}
        for finding in self.findings:
            counts[finding.severity] = counts.get(finding.severity, 0) + 1
        ordered = {name: counts[name] for name in SEVERITY_ORDER if name in counts}
        ordered.update({name: counts[name] for name in sorted(counts) if name not in ordered})
        return ordered

    def rule_ids(self) -> tuple[str, ...]:
        """Distinct rules that matched, sorted. Names, never messages."""
        return tuple(sorted({finding.rule_id for finding in self.findings}))

    def as_dict(self) -> Mapping[str, object]:
        """Serializable metadata for a report. No messages, no source, no output."""
        return {
            "tool": self.tool,
            "target": self.target,
            "ruleset": self.ruleset,
            "available": self.available,
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "duration_ms": self.duration_ms,
            "findings_total": self.findings_total,
            "findings_reported": len(self.findings),
            "findings_truncated": self.findings_truncated,
            "severity_counts": self.severity_counts(),
            "rules": list(self.rule_ids()),
            "scan_errors": self.scan_errors,
            "error": self.error,
        }


__all__ = ["SEVERITY_ORDER", "AnalysisFinding", "AnalysisRun"]
