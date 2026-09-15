"""C9: bounded static analysis -- the ruleset, the argv, the reader, the seam.

Five layers, each proving something the one below it cannot:

    ruleset    the shipped rules are locatable and structurally valid, and
               every one of them is a local file rather than a registry entry
    argv       the command is a frozen template with no config, URL or flag a
               caller can influence
    reader     Semgrep's documented JSON becomes bounded, deterministic findings
    tool       what a model may say, what is recorded, and that the session's
               own command policy still decides
    stack      a coding session and a Debug fix session gaining the tool while
               diagnosis, the frozen commands and the proof gate are untouched

**Offline throughout, and no analyser is required.** Every scan is driven
through a fake executor substituted for ``run_argv``; the one test that lets the
real executor run asserts the honest "not installed" path. No test spawns
Semgrep, and none reaches a network -- which is the whole reason the ruleset
ships as local YAML.
"""

import ast
import json
from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from codeagent_harness import (
    CLEAN_CRITIC,
    MODEL,
    DebugScenarioProvider,
    final_turn,
    tool_turn,
)
from test_codeagent_capabilities import ctx_for, run_session
from test_debugagent_app import (
    BUG,
    DIAGNOSIS,
    LENS_PROMPTS,
    REPRO,
    SOLVE_TURNS,
    SUITE,
    fixture_copy,
)

from engine.capabilities.analysis import (
    BUILTIN_RULESET,
    MAX_FINDINGS,
    PROGRAM,
    AnalysisRun,
    build_argv,
    builtin_ruleset,
    parse_output,
)
from engine.capabilities.analysis.semgrep import MAX_MESSAGE_CHARS
from engine.capabilities.errors import AnalysisUnavailable
from engine.codeagent.capabilities import build_capabilities, context_sources_from
from engine.codeagent.policy import DEFAULT_POLICY, CommandDenied, CommandPolicy
from engine.codeagent.state import SessionStatus
from engine.codeagent.tools.analysis import SCAN_TIMEOUT_SECONDS, AnalyzeCodeTool
from engine.codeagent.tools.registry import TOOL_REGISTRY
from engine.codeagent.tools.shell import CompletedCommand
from engine.debugagent.app import run_debug_task
from engine.debugagent.fix import ProofStatus
from engine.debugagent.limits import DEBUG_LIMITS
from engine.runtime.gateway import LLMGateway

RULES_DIR = "/opt/agentgate/rules"

SEVERITIES = {"ERROR", "WARNING", "INFO"}

# The keys a Semgrep rule must carry, from the rule-syntax reference. A rule also
# needs exactly one top-level matching key, which the second set enumerates.
REQUIRED_RULE_KEYS = {"id", "message", "severity", "languages"}
MATCH_KEYS = {"pattern", "patterns", "pattern-either", "pattern-regex"}


def result(*findings: dict, errors: int = 0) -> str:
    """A Semgrep ``--json`` document, in the documented shape."""
    return json.dumps(
        {"results": list(findings), "errors": [{"code": 2}] * errors, "paths": {}}
    )


def finding(
    rule: str = "agentgate.python.dangerous-eval-exec",
    *,
    path: str = "app.py",
    line: int = 3,
    severity: str = "ERROR",
    message: str = "eval runs arbitrary code",
) -> dict:
    return {
        "check_id": rule,
        "path": path,
        "start": {"line": line, "col": 1},
        "end": {"line": line, "col": 9},
        "extra": {"severity": severity, "message": message, "lines": "eval(x)"},
    }


class FakeExecutor:
    """Stands in for ``run_argv``. Spawns nothing."""

    def __init__(self, **outcome: object) -> None:
        self._outcome = {
            "stdout": result(),
            "stderr": "",
            "exit_code": 0,
            "timed_out": False,
            "unavailable": None,
            "duration_ms": 12,
            **outcome,
        }
        self.calls: list[tuple[list[str], object, float | None]] = []

    def __call__(self, argv, ctx, *, timeout_seconds=None):  # type: ignore[no-untyped-def]
        # The real executor policy-checks before spawning; so does this one, or
        # the tests below would prove nothing about the policy still applying.
        ctx.policy.check(argv)
        self.calls.append((list(argv), ctx, timeout_seconds))
        return CompletedCommand(argv=list(argv), **self._outcome)  # type: ignore[arg-type]


def analyse(monkeypatch, tmp_path: Path, executor: FakeExecutor, **args: object):  # type: ignore[no-untyped-def]
    monkeypatch.setattr("engine.codeagent.tools.analysis.run_argv", executor)
    ctx = ctx_for(tmp_path)
    return AnalyzeCodeTool().run(args, ctx), ctx


# -- the shipped ruleset ------------------------------------------------------


def test_the_shipped_ruleset_is_locatable_as_a_real_directory() -> None:
    with builtin_ruleset() as rules:
        assert rules is not None
        assert list(rules.glob("*.yaml"))


def test_every_shipped_rule_carries_the_documented_required_fields() -> None:
    with builtin_ruleset() as rules:
        assert rules is not None
        documents = [
            yaml.safe_load(path.read_text(encoding="utf-8"))
            for path in sorted(rules.glob("*.yaml"))
        ]

    seen: set[str] = set()
    for document in documents:
        assert isinstance(document, dict) and isinstance(document.get("rules"), list)
        for rule in document["rules"]:
            missing = REQUIRED_RULE_KEYS - set(rule)
            assert not missing, f"{rule.get('id')} is missing {sorted(missing)}"
            assert rule["severity"] in SEVERITIES, rule["id"]
            assert set(rule) & MATCH_KEYS, f"{rule['id']} has no matching key"
            assert rule["id"] not in seen, f"duplicate rule id {rule['id']}"
            seen.add(rule["id"])
    assert seen, "the shipped ruleset is empty"


def test_every_shipped_rule_is_namespaced_to_this_engine() -> None:
    """So a finding's origin is legible in a transcript that may also carry
    findings from a workspace's own tooling."""
    with builtin_ruleset() as rules:
        assert rules is not None
        text = "\n".join(p.read_text(encoding="utf-8") for p in rules.glob("*.yaml"))
    for rule in yaml.safe_load(text.split("rules:", 1)[0] + "rules:" + text.split("rules:", 1)[1])[
        "rules"
    ]:
        assert rule["id"].startswith("agentgate.")


# -- the argv is a frozen template -------------------------------------------


def test_the_argv_is_exactly_the_documented_flag_set() -> None:
    assert build_argv(RULES_DIR, "src") == [
        "semgrep",
        "scan",
        "--config",
        RULES_DIR,
        "--json",
        "--quiet",
        "--metrics=off",
        "--disable-version-check",
        "--timeout",
        "5.0",
        "--max-target-bytes",
        "1000000",
        "--jobs",
        "1",
        "src",
    ]


def test_the_argv_never_names_a_registry_entry_or_a_url() -> None:
    """``--config auto`` and ``p/…`` are registry fetches; a URL is a fetch too.
    None of the three is expressible, because the config is not a parameter."""
    argv = build_argv(RULES_DIR)
    assert argv[argv.index("--config") + 1] == RULES_DIR
    assert "auto" not in argv
    assert not any(part.startswith(("p/", "r/", "http://", "https://")) for part in argv)


def test_the_only_caller_supplied_element_is_the_target() -> None:
    argv = build_argv(RULES_DIR, "pkg/mod.py")
    fixed = build_argv(RULES_DIR)
    assert argv[:-1] == fixed[:-1]
    assert argv[-1] == "pkg/mod.py"


def test_telemetry_and_the_version_check_are_off() -> None:
    """The two things that would make an otherwise local scan touch a network."""
    argv = build_argv(RULES_DIR)
    assert "--metrics=off" in argv
    assert "--disable-version-check" in argv


# -- reading the analyser's output -------------------------------------------


def test_findings_come_from_the_documented_json_shape() -> None:
    findings, total, errors = parse_output(result(finding()))
    assert total == 1 and errors == 0
    assert findings[0].rule_id == "agentgate.python.dangerous-eval-exec"
    assert (findings[0].severity, findings[0].path, findings[0].line) == ("ERROR", "app.py", 3)


def test_findings_are_ordered_by_severity_then_location() -> None:
    findings, _, _ = parse_output(
        result(
            finding(path="z.py", severity="INFO"),
            finding(path="b.py", severity="ERROR", line=9),
            finding(path="a.py", severity="ERROR", line=2),
            finding(path="m.py", severity="WARNING"),
        )
    )
    assert [(f.severity, f.path) for f in findings] == [
        ("ERROR", "a.py"),
        ("ERROR", "b.py"),
        ("WARNING", "m.py"),
        ("INFO", "z.py"),
    ]


def test_the_reported_findings_are_capped_but_the_total_is_not() -> None:
    payload = result(*[finding(path=f"f{i}.py") for i in range(MAX_FINDINGS + 5)])
    findings, total, _ = parse_output(payload)
    assert len(findings) == MAX_FINDINGS
    assert total == MAX_FINDINGS + 5


def test_a_malformed_entry_is_skipped_rather_than_guessed_at() -> None:
    findings, total, _ = parse_output(
        result({"check_id": "x"}, "not-an-object", {"path": "a.py"}, finding())
    )
    assert total == 1
    assert findings[0].path == "app.py"


def test_a_missing_severity_or_line_degrades_rather_than_raises() -> None:
    entry = finding()
    del entry["extra"]["severity"]
    del entry["start"]
    findings, _, _ = parse_output(result(entry))
    assert findings[0].severity == "UNKNOWN"
    assert findings[0].line == 0


def test_a_long_message_is_clipped() -> None:
    findings, _, _ = parse_output(result(finding(message="x" * 900)))
    assert len(findings[0].message) <= MAX_MESSAGE_CHARS


def test_scan_errors_are_counted() -> None:
    _, _, errors = parse_output(result(finding(), errors=3))
    assert errors == 3


@pytest.mark.parametrize("payload", ["", "not json", "[]", '"text"', '{"no": "results"}'])
def test_unreadable_output_is_one_refusal(payload: str) -> None:
    with pytest.raises(AnalysisUnavailable):
        parse_output(payload)


# -- what a run is allowed to claim ------------------------------------------


def test_the_recorded_metadata_carries_no_message_and_no_source() -> None:
    findings, total, _ = parse_output(result(finding(), finding(path="b.py", severity="INFO")))
    run = AnalysisRun(
        tool=PROGRAM,
        target=".",
        ruleset=BUILTIN_RULESET,
        exit_code=0,
        findings=findings,
        findings_total=total,
    )
    recorded = run.as_dict()

    assert recorded["findings_total"] == 2
    assert recorded["severity_counts"] == {"ERROR": 1, "INFO": 1}
    assert recorded["rules"] == ["agentgate.python.dangerous-eval-exec"]
    rendered = json.dumps(recorded)
    assert "eval runs arbitrary code" not in rendered
    assert "eval(x)" not in rendered


# -- the model-facing tool ----------------------------------------------------


def test_a_scan_reports_findings_and_records_one_run(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    executor = FakeExecutor(stdout=result(finding()))
    outcome, ctx = analyse(monkeypatch, tmp_path, executor)

    assert outcome.ok
    assert "ERROR app.py:3 [agentgate.python.dangerous-eval-exec]" in outcome.output
    assert "note: advisory static-analysis evidence, not a verdict" in outcome.output
    assert len(ctx.analysis_log) == 1
    assert ctx.analysis_log[0].as_dict()["findings_total"] == 1


def test_the_scan_runs_the_frozen_argv_under_its_own_wall_clock(
    monkeypatch, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    executor = FakeExecutor()
    analyse(monkeypatch, tmp_path, executor, target="src")

    argv, _, timeout = executor.calls[0]
    assert argv[:2] == ["semgrep", "scan"]
    assert argv[-1] == "src"
    assert timeout == SCAN_TIMEOUT_SECONDS


def test_an_unexpected_argument_is_refused_rather_than_ignored(
    monkeypatch, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    executor = FakeExecutor()
    outcome, ctx = analyse(monkeypatch, tmp_path, executor, config="p/default")

    assert executor.calls == []
    assert "config" in outcome.output
    assert ctx.analysis_log[0].error is not None


def test_a_timeout_is_reported_and_recorded(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    executor = FakeExecutor(timed_out=True, exit_code=None, stdout="")
    outcome, ctx = analyse(monkeypatch, tmp_path, executor)

    assert "timed out" in outcome.output
    assert ctx.analysis_log[0].timed_out is True
    assert ctx.analysis_log[0].ok is False


def test_a_non_zero_exit_is_reported_and_recorded(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    executor = FakeExecutor(exit_code=7, stdout="")
    _, ctx = analyse(monkeypatch, tmp_path, executor)

    recorded = ctx.analysis_log[0]
    assert recorded.exit_code == 7
    assert recorded.error is not None and recorded.ok is False


def test_unreadable_analyser_output_is_a_failed_run_not_a_crash(
    monkeypatch, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    executor = FakeExecutor(stdout="<html>not semgrep</html>")
    outcome, ctx = analyse(monkeypatch, tmp_path, executor)

    assert outcome.ok
    assert ctx.analysis_log[0].error is not None


def test_a_missing_analyser_is_reported_honestly(tmp_path: Path) -> None:
    """The real executor, no monkeypatch: Semgrep is not installed in the test
    environment, and the tool says so rather than fabricating a clean scan."""
    ctx = ctx_for(tmp_path)
    outcome = AnalyzeCodeTool().run({}, ctx)

    recorded = ctx.analysis_log[0]
    assert recorded.available is False
    assert recorded.findings == ()
    assert "unavailable" in outcome.output


# -- the session's command policy still decides ------------------------------


def test_a_model_supplied_target_is_policy_checked(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """The engine's own ruleset path is trusted; the model's target is not."""
    executor = FakeExecutor()
    outcome, _ = analyse(monkeypatch, tmp_path, executor, target="../../etc/passwd")

    assert outcome.ok is False
    assert "CommandDenied" in (outcome.error or "")
    assert executor.calls == []


@pytest.mark.parametrize("target", ["/etc/passwd", "a; rm -rf /", "x | y"])
def test_a_target_that_escapes_or_smuggles_is_refused(
    monkeypatch, tmp_path: Path, target: str
) -> None:  # type: ignore[no-untyped-def]
    executor = FakeExecutor()
    outcome, _ = analyse(monkeypatch, tmp_path, executor, target=target)
    assert outcome.ok is False
    assert executor.calls == []


def test_the_widening_is_scoped_to_the_scan(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """The session policy is never mutated: semgrep stays unrunnable through
    run_command, and the ruleset path stays untrusted everywhere else."""
    executor = FakeExecutor()
    _, ctx = analyse(monkeypatch, tmp_path, executor)

    assert PROGRAM not in ctx.policy.allowed_programs
    assert ctx.policy.trusted_args == frozenset()

    denied = TOOL_REGISTRY["run_command"].run(
        {"argv": ["semgrep", "scan", "--config", "p/default", "."]}, ctx
    )
    assert denied.ok is False


def test_a_trusted_argument_is_exempt_but_nothing_else_is() -> None:
    policy = CommandPolicy(
        allowed_programs=DEFAULT_POLICY.allowed_programs | {"semgrep"},
        trusted_args=frozenset({RULES_DIR}),
    )
    assert policy.check(["semgrep", "scan", "--config", RULES_DIR, "."])

    with pytest.raises(CommandDenied):
        policy.check(["semgrep", "scan", "--config", "/etc/other-rules", "."])


def test_the_default_policy_trusts_nothing() -> None:
    """The field is additive: a policy nobody widened behaves as it always did."""
    assert DEFAULT_POLICY.trusted_args == frozenset()
    with pytest.raises(CommandDenied):
        DEFAULT_POLICY.check(["semgrep", "scan", "."])


# -- advisory only ------------------------------------------------------------


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_the_analysis_layer_never_reaches_verification_or_eval() -> None:
    """Structural, not a promise: no module in this capability imports the
    verification, eval or judging packages, so a finding has no path by which it
    could become a verdict input, a severity threshold or a benchmark number."""
    roots = [
        Path("src/engine/capabilities/analysis"),
        Path("src/engine/codeagent/tools/analysis.py"),
    ]
    modules = [
        path
        for root in roots
        for path in ([root] if root.is_file() else sorted(root.glob("*.py")))
    ]
    assert modules

    forbidden = ("engine.verification", "engine.eval", "engine.debugagent")
    for path in modules:
        offending = {
            name
            for name in _imports(path)
            if name.startswith(forbidden)
        }
        assert not offending, f"{path}: imports {sorted(offending)}"


def test_the_capability_layer_stays_a_leaf() -> None:
    """Architecture Rule H, for the new package: capabilities/ must not import
    an agent package."""
    for path in sorted(Path("src/engine/capabilities/analysis").glob("*.py")):
        agent_imports = {
            name
            for name in _imports(path)
            if name.startswith(("engine.codeagent", "engine.debugagent"))
        }
        assert not agent_imports, f"{path}: imports {sorted(agent_imports)}"


# -- the bundle and the report ------------------------------------------------


def test_the_tool_is_absent_unless_requested() -> None:
    assert "analyze_code" not in build_capabilities().tools


def test_requesting_analysis_registers_exactly_one_tool() -> None:
    bundle = build_capabilities(analyze=True)
    assert set(bundle.tools) == {"analyze_code"}


def test_context_sources_is_none_when_nothing_was_analysed(tmp_path: Path) -> None:
    state, _ = run_session(tmp_path, [final_turn("done")], bundle=build_capabilities())
    assert context_sources_from([state])["analysis"] is None


def test_a_session_records_its_scans_in_context_sources(
    monkeypatch, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "engine.codeagent.tools.analysis.run_argv", FakeExecutor(stdout=result(finding()))
    )
    state, _ = run_session(
        tmp_path,
        [tool_turn("analyze_code", {}), final_turn("done")],
        bundle=build_capabilities(analyze=True),
    )

    recorded = context_sources_from([state])["analysis"]
    assert isinstance(recorded, list) and len(recorded) == 1
    assert recorded[0]["tool"] == "semgrep"
    assert recorded[0]["ruleset"] == BUILTIN_RULESET
    assert recorded[0]["findings_total"] == 1
    assert state.status is SessionStatus.COMPLETED_UNVERIFIED


# -- the Debug Agent keeps every guarantee it had ------------------------------


def run_debug(tmp_path: Path, fix_turns, **kwargs):  # type: ignore[no-untyped-def]
    fake = DebugScenarioProvider(
        diagnosis_turns=[DIAGNOSIS],
        fix_turns=fix_turns,
        judge_rounds=[CLEAN_CRITIC],
        lens_prompts=LENS_PROMPTS,
    )
    result_ = run_debug_task(
        task_text=BUG,
        workspace_path=fixture_copy(tmp_path),
        repro_argv=REPRO,
        suite_argv=SUITE,
        gateway=LLMGateway(fake),
        model=MODEL,
        judge_model=MODEL,
        limits=DEBUG_LIMITS,
        planned_budget=Decimal("10.00"),
        task_id="dbg-c9",
        **kwargs,
    )
    return result_, fake


def test_a_debug_fix_session_can_analyse_and_diagnosis_cannot(
    monkeypatch, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "engine.codeagent.tools.analysis.run_argv", FakeExecutor(stdout=result(finding()))
    )
    outcome, fake = run_debug(
        tmp_path, [tool_turn("analyze_code", {}), *SOLVE_TURNS], analyze=True
    )

    fix_system = next(
        s for s in fake.seen_systems if s and s.startswith("You are a debugging agent")
    )
    assert "analyze_code" in fix_system

    diagnosis_system = next(
        s for s in fake.seen_systems if s and s.startswith("You are diagnosing a reproduced")
    )
    assert "analyze_code" not in diagnosis_system

    report = outcome.report
    assert list(report.repro_command) == REPRO
    assert list(report.suite_command) == SUITE
    assert report.observed.proof_status == ProofStatus.PROVEN.value
    assert report.status == SessionStatus.PASSED.value


def test_a_debug_run_without_analysis_never_learns_the_tool_existed(tmp_path: Path) -> None:
    _, fake = run_debug(tmp_path, SOLVE_TURNS)

    fix_system = next(
        s for s in fake.seen_systems if s and s.startswith("You are a debugging agent")
    )
    assert "analyze_code" not in fix_system
