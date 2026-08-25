"""The model-facing half of static analysis: one tool, one bounded scan.

The adapter across the capability seam. ``capabilities/analysis`` builds an argv
and reads an output and knows nothing about ``Tool``, ``Workspace`` or
``CommandPolicy``; everything above this module is ordinary session machinery.

**The model chooses a target path. It chooses nothing else.** There is no
argument for a config, a ruleset, a registry entry, a URL, a flag, a timeout or a
command, and supplying one is a refusal rather than an ignored extra. The argv
comes from a frozen template in ``capabilities/analysis/semgrep.py``, and the
ruleset is always the local directory the engine ships -- so ``--config
p/default`` and ``--config https://…``, both of which Semgrep would accept and
both of which are network fetches, are not expressible here.

**No second executor.** The scan goes through ``tools/shell.py:run_argv``, the
one place in this codebase that spawns a child process, so it inherits the
forced working directory, the scrubbed child environment and the wall-clock
timeout that every other command already gets. The session's own
``CommandPolicy`` still checks the argv; the only widening is the two elements
the engine wrote -- the program name and the path to its own ruleset -- and the
target the model supplied is checked exactly as any other argument would be.

**Findings are advisory evidence.** They are an observation in a transcript.
This module holds no rubric, no severity threshold, no verdict, no judge prompt
and no reference to ``verification/``; Semgrep's severity strings are carried
through verbatim and never mapped onto AgentGate's scale. Nothing downstream is
obliged to act on a finding, and the Debug Agent's frozen reproduction and suite
are settled before any session exists.
"""

from dataclasses import replace
from typing import Any

from engine.capabilities.analysis import (
    BUILTIN_RULESET,
    DEFAULT_TARGET,
    PROGRAM,
    AnalysisRun,
    build_argv,
    builtin_ruleset,
    parse_output,
)
from engine.capabilities.errors import AnalysisUnavailable
from engine.codeagent.state import ToolResult
from engine.codeagent.tools.base import ToolContext, guarded, truncate
from engine.codeagent.tools.shell import run_argv

# Everything the model may name.
ALLOWED_ARGS = frozenset({"target"})

# Wall clock for the whole scan, distinct from Semgrep's own per-rule timeout.
# Deliberately its own number rather than ``limits.command_timeout_seconds``:
# an advisory scan that takes two minutes has already cost more than it is
# worth, whatever a test suite is allowed to take.
SCAN_TIMEOUT_SECONDS = 60.0


class AnalyzeCodeTool:
    """Run the shipped Semgrep ruleset over the workspace, within hard bounds."""

    name = "analyze_code"
    description = (
        "Run bounded static analysis (Semgrep, with the rules this engine ships) over "
        'the workspace. Args: {"target": "<optional workspace-relative file or '
        'directory; defaults to the whole workspace>"}. Read-only: it runs the analyser '
        "and reports findings, and changes nothing. The ruleset is fixed and local -- "
        "there is no way to select rules, a registry entry or a URL. Findings are "
        "advisory evidence, not a verdict. No other arguments are accepted."
    )

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        """Locate the ruleset, run the frozen argv, read the output, record it.

        Every outcome is truthful and distinct: the analyser was missing, the
        ruleset was missing, the scan timed out, it exited non-zero, or it
        produced findings. None of them fabricates a result, and each one is
        recorded with the same metadata shape so a report never has to guess
        which happened.
        """

        def _run() -> ToolResult:
            unknown = sorted(set(args) - ALLOWED_ARGS)
            if unknown:
                return _record(
                    ctx,
                    _failure(
                        DEFAULT_TARGET,
                        f"unexpected argument(s) {unknown}; analyze_code accepts only "
                        f"{sorted(ALLOWED_ARGS)}. The ruleset and every flag are fixed "
                        "and cannot be selected here.",
                    ),
                )

            raw = args.get("target", DEFAULT_TARGET)
            target = raw.strip() if isinstance(raw, str) and raw.strip() else DEFAULT_TARGET

            with builtin_ruleset() as rules:
                if rules is None:
                    return _record(
                        ctx,
                        _failure(target, "the engine's Semgrep ruleset is unavailable"),
                    )
                return _record(ctx, _scan(ctx, rules_dir=str(rules), target=target))

        return guarded(_run)


def _scan(ctx: ToolContext, *, rules_dir: str, target: str) -> AnalysisRun:
    """One scan, through the session's own executor and command policy."""
    argv = build_argv(rules_dir, target)

    # The two elements the engine wrote: the program, and the absolute path to
    # its own ruleset. Everything else in the argv -- including the model's
    # target -- is checked by the session's policy exactly as it always was.
    scan_ctx = replace(
        ctx,
        policy=replace(
            ctx.policy,
            allowed_programs=ctx.policy.allowed_programs | {PROGRAM},
            trusted_args=frozenset({rules_dir}),
        ),
    )

    # The scan is not appended to ``command_log``: its execution metadata --
    # exit code, duration, timeout -- is carried by the ``AnalysisRun`` instead,
    # and recording it twice would double-count one child process in a report.
    done = run_argv(argv, scan_ctx, timeout_seconds=SCAN_TIMEOUT_SECONDS)

    def run(**fields: Any) -> AnalysisRun:
        return AnalysisRun(
            tool=PROGRAM,
            target=target,
            ruleset=BUILTIN_RULESET,
            duration_ms=done.duration_ms,
            **fields,
        )

    if done.unavailable is not None:
        return run(available=False, error=f"{PROGRAM} is not installed or not on PATH")
    if done.timed_out:
        return run(timed_out=True, error=f"analysis timed out after {SCAN_TIMEOUT_SECONDS}s")

    # Semgrep exits 0 for a clean run whether or not it found anything -- the
    # `--error` flag that turns findings into exit 1 is deliberately not passed,
    # because a finding is evidence here, not a failure.
    if done.exit_code != 0:
        return run(exit_code=done.exit_code, error=f"{PROGRAM} exited {done.exit_code}")

    try:
        findings, total, scan_errors = parse_output(done.stdout)
    except AnalysisUnavailable as exc:
        return run(exit_code=done.exit_code, error=str(exc))

    return run(
        exit_code=done.exit_code,
        findings=findings,
        findings_total=total,
        findings_truncated=total > len(findings),
        scan_errors=scan_errors,
    )


def _failure(target: str, reason: str) -> AnalysisRun:
    return AnalysisRun(
        tool=PROGRAM, target=target, ruleset=BUILTIN_RULESET, available=False, error=reason
    )


def _record(ctx: ToolContext, run: AnalysisRun) -> ToolResult:
    """Log the run, then render it.

    A failed analysis is still an ``ok`` tool call: the tool did its job by
    telling the session what happened, and an advisory capability that cannot
    reach its analyser is an observation the agent can act on -- by continuing
    from the code itself -- rather than an error to retry.
    """
    ctx.analysis_log.append(run)
    body, was_truncated = truncate(render(run), ctx.limits.max_tool_output_bytes)
    return ToolResult(ok=True, output=body, truncated=was_truncated)


def render(run: AnalysisRun) -> str:
    """The observation: what ran, then one line per finding.

    A finding is a rule id, a location and the *rule's* message. The scanned
    source is never quoted: the analyser reports matching lines and this layer
    exists to bound what enters context rather than to widen it -- the agent can
    read the file it already has.
    """
    lines = [
        f"tool: {run.tool}",
        f"ruleset: {run.ruleset}",
        f"target: {run.target}",
        f"status: {'ok' if run.ok else 'unavailable'}",
        f"findings: {run.findings_total}",
        "note: advisory static-analysis evidence, not a verdict",
    ]
    if run.error:
        lines.append(f"error: {run.error}")
    if run.scan_errors:
        lines.append(f"scan_errors: {run.scan_errors}")
    if run.findings_truncated:
        lines.append(f"showing: {len(run.findings)} of {run.findings_total}")

    lines.append("results:")
    lines += [
        f"  - {f.severity} {f.path}:{f.line} [{f.rule_id}] {f.message}" for f in run.findings
    ] or ["  (none)"]
    return "\n".join(lines)


__all__ = ["ALLOWED_ARGS", "SCAN_TIMEOUT_SECONDS", "AnalyzeCodeTool", "render"]
