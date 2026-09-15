"""The Semgrep interface: one frozen argv template, and one output reader.

**No shell, no URL, no free-form flags.** ``build_argv`` is a template, not a
builder: every flag and every value below is written here, and the only piece a
caller contributes is ``target`` -- one workspace-relative path. There is no
parameter for a config, so a registry entry (``p/default``) or a URL, both of
which ``--config`` would accept and both of which are network fetches, is not
expressible. The ruleset is always the local directory the engine ships.

Flags, from Semgrep's CLI reference:

    --config VAL              a local directory of YAML; registry entries and
                              URLs are network fetches and are never passed
    --json                    machine-readable results
    --quiet                   only findings on stdout
    --metrics=off             no telemetry to the Semgrep service
    --disable-version-check   no update ping at start-up
    --timeout SECONDS         per rule, per file
    --max-target-bytes N      skip files larger than this
    --jobs 1                  one worker; a bounded, predictable scan

Those last four are what makes the run bounded from the inside. The wall clock
around the whole process is bounded from the outside by the caller's timeout,
and the output is bounded again on the way into context by ``MAX_FINDINGS``.

**The output is untrusted.** It is the analyser's rendering of files the agent
may itself have written. It is parsed defensively -- an entry missing a key is
skipped rather than guessed at -- and a shape this reader does not recognise
degrades to "nothing parsed" instead of raising into a session.
"""

import json
from collections.abc import Mapping
from pathlib import Path

from engine.capabilities.analysis.models import SEVERITY_ORDER, AnalysisFinding
from engine.capabilities.errors import AnalysisUnavailable

PROGRAM = "semgrep"

# Bounds on the scan itself. Semgrep's own defaults for the first two, restated
# rather than relied on, so a future default change cannot quietly widen a run.
RULE_TIMEOUT_SECONDS = 5.0
MAX_TARGET_BYTES = 1_000_000
JOBS = 1

# Bounds on what reaches the model. A scan of a large workspace can report
# hundreds of findings; twenty is an observation, and hundreds is a transcript.
MAX_FINDINGS = 20
MAX_MESSAGE_CHARS = 200
MAX_PATH_CHARS = 200

DEFAULT_TARGET = "."


def build_argv(rules: Path | str, target: str = DEFAULT_TARGET) -> list[str]:
    """The whole command. ``target`` is the only caller-supplied element."""
    return [
        PROGRAM,
        "scan",
        "--config",
        str(rules),
        "--json",
        "--quiet",
        "--metrics=off",
        "--disable-version-check",
        "--timeout",
        str(RULE_TIMEOUT_SECONDS),
        "--max-target-bytes",
        str(MAX_TARGET_BYTES),
        "--jobs",
        str(JOBS),
        target,
    ]


def parse_output(
    stdout: str, *, limit: int = MAX_FINDINGS
) -> tuple[tuple[AnalysisFinding, ...], int, int]:
    """Read ``--json`` output into bounded findings.

    Returns the findings kept, the total Semgrep reported, and the number of
    scan errors it recorded. The total is counted before the limit is applied, so
    a report can say how much was left out rather than implying twenty was all
    there was.

    Findings are sorted by severity, then path, then line, then rule -- so the
    same scan produces the same observation whatever order the analyser emitted
    them in, and the most serious ones survive the cut.

    Raises:
        AnalysisUnavailable: the output is not the documented JSON object. The
            caller records that as a failed run; guessing at an unrecognised
            shape would be worse than saying the analyser could not be read.
    """
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise AnalysisUnavailable("analyser output was not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise AnalysisUnavailable("analyser output was not a JSON object")

    raw = parsed.get("results")
    if not isinstance(raw, list):
        raise AnalysisUnavailable("analyser output carried no results array")

    findings = [
        finding for finding in (_finding(entry) for entry in raw) if finding is not None
    ]
    findings.sort(key=_order)

    errors = parsed.get("errors")
    scan_errors = len(errors) if isinstance(errors, list) else 0
    return tuple(findings[:limit]), len(findings), scan_errors


def _finding(entry: object) -> AnalysisFinding | None:
    """One result, or None if it is not shaped like one."""
    if not isinstance(entry, dict):
        return None
    rule_id = entry.get("check_id")
    path = entry.get("path")
    if not isinstance(rule_id, str) or not isinstance(path, str):
        return None

    extra = entry.get("extra")
    extra = extra if isinstance(extra, Mapping) else {}
    severity = extra.get("severity")
    message = extra.get("message")

    start = entry.get("start")
    line = start.get("line") if isinstance(start, Mapping) else None

    return AnalysisFinding(
        rule_id=_clip(rule_id, MAX_PATH_CHARS),
        severity=severity.upper() if isinstance(severity, str) and severity else "UNKNOWN",
        path=_clip(path, MAX_PATH_CHARS),
        line=line if isinstance(line, int) and not isinstance(line, bool) and line > 0 else 0,
        message=_clip(" ".join(message.split()), MAX_MESSAGE_CHARS)
        if isinstance(message, str)
        else "",
    )


def _order(finding: AnalysisFinding) -> tuple[int, str, int, str]:
    rank = (
        SEVERITY_ORDER.index(finding.severity)
        if finding.severity in SEVERITY_ORDER
        else len(SEVERITY_ORDER)
    )
    return rank, finding.path, finding.line, finding.rule_id


def _clip(text: str, ceiling: int) -> str:
    return text if len(text) <= ceiling else text[: max(0, ceiling - 1)].rstrip() + "…"


__all__ = [
    "DEFAULT_TARGET",
    "JOBS",
    "MAX_FINDINGS",
    "MAX_MESSAGE_CHARS",
    "MAX_PATH_CHARS",
    "MAX_TARGET_BYTES",
    "PROGRAM",
    "RULE_TIMEOUT_SECONDS",
    "build_argv",
    "parse_output",
]
