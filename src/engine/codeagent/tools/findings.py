"""The one tool a read-only review agent (Security, Architecture, ...) calls
to record a finding.

**It never executes anything and never writes a file.** ``report_finding``
appends a validated, bounded record to the session's own sink
(``ToolContext.review_findings_log``) -- the same pattern ``tools/graph.py``
and ``tools/analysis.py`` already use, applied to a model's own structured
claim instead of a scan's output. Nothing here maps a finding onto AgentGate's
verdict, severity threshold, or judge lenses; see ``codeagent/state.py``'s
``ReviewFinding`` docstring for why the vocabulary is deliberately its own.

Shared rather than defined per agent: Security (C14) and Architecture (C15)
both need "record one bounded, structured claim about the code," and the
claim's shape -- category, severity, rationale, location, evidence,
recommendation, basis -- does not change with what kind of review produced
it. ``category`` is the one field left as free text for exactly that reason:
each agent's own prompt suggests its own taxonomy, and a fixed enum shared
across two unrelated review domains would either be too broad to mean
anything or too narrow to fit both.

``severity`` and ``basis`` are validated against fixed sets and rejected
outright when they are not one of them, because both carry structural
meaning: "how bad" and "confirmed or suspected" are exactly the two things a
reader needs to triage a list of findings, and a value outside the set would
silently break that triage. Every other required field is bounded by
clipping, not refusal, matching ``plan.py``'s own rule -- shortening a
too-long sentence keeps what the model meant, where rejecting an over-long
field would mean guessing what to do with it.

A refusal is never logged as a finding. ``max_review_findings`` counts real,
recorded findings only, so a malformed call cannot spend a curated agent's
budget on noise -- the cap exists to keep the *deliverable* bounded, not to
throttle chatter.
"""

from typing import Any

from engine.codeagent.state import REVIEW_BASES, REVIEW_SEVERITIES, ReviewFinding, ToolResult
from engine.codeagent.tools.base import ToolContext, guarded, ok, str_arg

# Everything the model may name. Anything else is refused -- a silently
# dropped extra key would leave a model believing it had recorded a field
# that was never stored.
ALLOWED_ARGS = frozenset(
    {"category", "severity", "rationale", "location", "evidence", "recommendation", "basis"}
)


class ReportFindingTool:
    """Record one bounded, structured review finding."""

    name = "report_finding"
    description = (
        "Record one review finding. Args: "
        '{"category": "<a short label for what kind of finding this is -- see this '
        'session\'s own instructions for the suggested taxonomy>", '
        '"severity": "<one of ' + "/".join(sorted(REVIEW_SEVERITIES)) + '>", '
        '"rationale": "<why this severity, optional>", '
        '"location": "<workspace-relative path[:line]>", '
        '"evidence": "<what you actually observed -- a code reference, a Semgrep '
        'rule id, a repo_graph result, a quoted condition>", '
        '"recommendation": "<advisory suggestion, optional>", '
        '"basis": "<one of ' + "/".join(sorted(REVIEW_BASES)) + '>"}. '
        "category, severity, location, evidence and basis are required. This tool "
        "only records a claim -- it changes nothing, runs nothing, and decides "
        "nothing; the finding is advisory evidence for a person to read, not a "
        "verdict."
    )

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        def _run() -> ToolResult:
            unknown = sorted(set(args) - ALLOWED_ARGS)
            if unknown:
                return self._refuse(
                    ctx,
                    f"unexpected argument(s) {unknown}; report_finding accepts only "
                    f"{sorted(ALLOWED_ARGS)}.",
                )

            if len(ctx.review_findings_log) >= ctx.limits.max_review_findings:
                return self._refuse(
                    ctx,
                    f"max_review_findings ({ctx.limits.max_review_findings}) already "
                    "recorded for this session; stop and summarise rather than adding more.",
                )

            # Required fields: str_arg with no default raises ToolError, which
            # guarded() turns into an ordinary failed ToolResult -- the same
            # convention every other tool follows for a missing required
            # argument (see tools/graph.py).
            category = str_arg(args, "category").strip()
            severity = str_arg(args, "severity").strip().upper()
            location = str_arg(args, "location").strip()
            evidence = str_arg(args, "evidence").strip()
            basis = str_arg(args, "basis").strip().lower()

            if severity not in REVIEW_SEVERITIES:
                return self._refuse(
                    ctx, f"severity {severity!r} is not one of {sorted(REVIEW_SEVERITIES)}."
                )
            if basis not in REVIEW_BASES:
                return self._refuse(
                    ctx, f"basis {basis!r} is not one of {sorted(REVIEW_BASES)}."
                )
            if not category or not location or not evidence:
                return self._refuse(
                    ctx, "'category', 'location' and 'evidence' must not be empty."
                )

            cap = ctx.limits.max_review_finding_field_chars
            finding = ReviewFinding(
                category=_clip(category, cap),
                severity=severity,
                rationale=_clip(str_arg(args, "rationale", ""), cap),
                location=_clip(location, cap),
                evidence=_clip(evidence, cap),
                recommendation=_clip(str_arg(args, "recommendation", ""), cap),
                basis=basis,
            )
            ctx.review_findings_log.append(finding)
            count = len(ctx.review_findings_log)
            return ok(
                f"recorded finding #{count}: [{finding.severity}/{finding.basis}] "
                f"{finding.category} @ {finding.location}",
                ctx,
            )

        return guarded(_run)

    def _refuse(self, ctx: ToolContext, reason: str) -> ToolResult:
        return ok(f"error: {reason}", ctx)


def _clip(value: str, limit: int) -> str:
    return " ".join(value.split())[:limit]


__all__ = ["ALLOWED_ARGS", "ReportFindingTool"]
