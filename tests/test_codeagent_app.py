"""End-to-end offline acceptance for `engine code`.

Every test here drives the whole real flow -- plan, session, real tools, real
subprocesses, real AgentGate verification, real verdict.gate -- with only the
model replaced by a scripted provider. No API key, no network, no spend.
"""

import json
import shutil
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest
from codeagent_harness import (
    CLEAN_CRITIC,
    MODEL,
    ScenarioProvider,
    critic,
    final_turn,
    plan_block,
    tool_turn,
)

from engine import cli
from engine.codeagent.app import (
    EXIT_ERROR,
    EXIT_UNVERIFIED,
    EXIT_VERIFIED,
    WorkspaceRejected,
    build_repo_context,
    exit_code_for,
    run_coding_task,
    validate_workspace,
)
from engine.codeagent.limits import DEFAULT_LIMITS, Limits
from engine.codeagent.state import SessionStatus
from engine.runtime.gateway import LLMGateway
from engine.verification.judge import LENSES

FIXTURES = Path(__file__).resolve().parent.parent / "examples"
LENS_PROMPTS = tuple(LENSES.values())

GOOD_FIX = (
    'def parse_due_date(raw: str) -> tuple[int, int, int]:\n'
    '    """Parse an ISO date of the form YYYY-MM-DD into (year, month, day)."""\n'
    '    if not raw.strip():\n'
    '        raise ValueError("due date must not be empty")\n'
    '    parts = raw.split("-")\n'
    "    return int(parts[0]), int(parts[1]), int(parts[2])\n"
)
NAIVE_FIX = (
    'def parse_due_date(raw: str) -> tuple[int, int, int]:\n'
    '    """Parse an ISO date of the form YYYY-MM-DD into (year, month, day)."""\n'
    "    if len(raw) != 10:\n"
    '        raise ValueError("due date must not be empty")\n'
    '    parts = raw.split("-")\n'
    "    return int(parts[0]), int(parts[1]), int(parts[2])\n"
)
REGRESSION_TEST = (
    "import pytest\n\nfrom todo import parse_due_date\n\n\n"
    "def test_empty_is_rejected() -> None:\n"
    "    with pytest.raises(ValueError):\n"
    '        parse_due_date("")\n'
)

PLAN = plan_block(
    goal="make parse_due_date reject empty input",
    steps=["read todo.py", "add a guard", "add a regression test", "run the tests"],
    likely_files=["todo.py"],
    validation_commands=[["python", "-m", "pytest", "-q"]],
    completion_criteria="pytest passes and empty input raises ValueError",
)

TASK = (
    "parse_due_date('') fails with an unhelpful error. Make it raise "
    "ValueError('due date must not be empty') for empty input, and add a regression test."
)


def fixture_copy(tmp_path: Path, name: str = "todo_cli") -> Path:
    workspace = tmp_path / "ws"
    shutil.copytree(FIXTURES / name, workspace)
    return workspace


def provider(agent_turns: list[str], judge_rounds: list[str] | None = None) -> ScenarioProvider:
    return ScenarioProvider(
        agent_turns=agent_turns,
        plan_turns=[PLAN],
        judge_rounds=judge_rounds or [CLEAN_CRITIC],
        lens_prompts=LENS_PROMPTS,
    )


SOLVE_TURNS = [
    tool_turn("list_files"),
    tool_turn("read_file", {"path": "todo.py"}),
    tool_turn("write_file", {"path": "todo.py", "content": GOOD_FIX, "overwrite": True}),
    tool_turn("write_file", {"path": "test_due_date.py", "content": REGRESSION_TEST}),
    tool_turn("run_tests"),
    final_turn("guarded empty input and added a regression test", ["todo.py"]),
]


def go(
    tmp_path: Path,
    agent_turns: list[str],
    *,
    judge_rounds: list[str] | None = None,
    limits: Limits | None = None,
    workspace: Path | None = None,
    artifacts: Path | None = None,
    budget: str = "10.00",
):  # type: ignore[no-untyped-def]
    fake = provider(agent_turns, judge_rounds)
    result = run_coding_task(
        task_text=TASK,
        workspace_path=workspace if workspace is not None else fixture_copy(tmp_path),
        gateway=LLMGateway(fake),
        model=MODEL,
        judge_model=MODEL,
        limits=limits if limits is not None else DEFAULT_LIMITS,
        planned_budget=Decimal(budget),
        task_id="cd-app",
        artifacts_root=artifacts,
    )
    return result, fake


# -- workspace validation ----------------------------------------------------


def test_a_missing_workspace_is_refused(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceRejected, match="does not exist"):
        validate_workspace(tmp_path / "nope")


def test_a_file_workspace_is_refused(tmp_path: Path) -> None:
    target = tmp_path / "a.txt"
    target.write_text("x", encoding="utf-8")

    with pytest.raises(WorkspaceRejected, match="not a directory"):
        validate_workspace(target)


def test_the_engines_own_tree_is_refused(tmp_path: Path) -> None:
    """An agent that could edit verdict.py could edit its own judge."""
    marker = tmp_path / "src" / "engine" / "verification"
    marker.mkdir(parents=True)
    (marker / "verdict.py").write_text("# the real one\n", encoding="utf-8")

    with pytest.raises(WorkspaceRejected, match="own source tree"):
        validate_workspace(tmp_path)


def test_a_rejected_workspace_costs_nothing(tmp_path: Path) -> None:
    fake = provider(SOLVE_TURNS)

    with pytest.raises(WorkspaceRejected):
        run_coding_task(
            task_text=TASK,
            workspace_path=tmp_path / "missing",
            gateway=LLMGateway(fake),
            model=MODEL,
            judge_model=MODEL,
        )

    assert fake.plan_calls == 0
    assert fake.agent_calls == 0
    assert fake.judge_calls == 0


# -- bounded repository context ----------------------------------------------


def test_repo_context_lists_files_without_contents(tmp_path: Path) -> None:
    workspace = validate_workspace(fixture_copy(tmp_path))

    context = build_repo_context(workspace)

    assert "todo.py" in context
    assert "test_todo.py" in context
    # Names and sizes only -- the planner never sees source.
    assert "def parse_due_date" not in context


def test_repo_context_hides_secrets(tmp_path: Path) -> None:
    root = fixture_copy(tmp_path)
    (root / ".env").write_text("ANTHROPIC_API_KEY=sk-secret\n", encoding="utf-8")
    (root / "id_rsa").write_text("PRIVATE KEY\n", encoding="utf-8")

    context = build_repo_context(validate_workspace(root))

    assert ".env" not in context
    assert "id_rsa" not in context
    assert "sk-secret" not in context


def test_repo_context_is_bounded(tmp_path: Path) -> None:
    root = fixture_copy(tmp_path)
    for i in range(300):
        (root / f"mod{i}.py").write_text("x = 1\n", encoding="utf-8")

    context = build_repo_context(validate_workspace(root), Limits(max_plan_context_chars=200))

    assert len(context) <= 200


# -- the full flow -----------------------------------------------------------


def test_the_flow_plans_edits_tests_and_verifies(tmp_path: Path) -> None:
    workspace = fixture_copy(tmp_path)

    result, fake = go(tmp_path, SOLVE_TURNS, workspace=workspace)
    report = result.report

    # Planning ran and validated.
    assert fake.plan_calls == 1
    assert report.planning_status == "OK"
    assert report.plan is not None
    assert report.plan["goal"].startswith("make parse_due_date")

    # Real tools really ran, and the file on disk really changed.
    assert report.tool_calls == 5
    assert (workspace / "todo.py").read_text(encoding="utf-8") == GOOD_FIX
    assert (workspace / "test_due_date.py").exists()

    # A real subprocess ran the real test suite.
    assert report.commands_run
    assert report.commands_run[0]["argv"] == ["python", "-m", "pytest", "-q"]
    assert report.commands_run[0]["exit_code"] == 0

    # AgentGate really ran: three lenses plus the automated gates.
    assert fake.judge_calls == len(LENSES)
    assert report.verification_ran
    assert {gate["gate"] for gate in report.automated_gates} == {"ruff", "mypy", "pytest"}

    assert report.status == "PASSED"
    assert result.exit_code == EXIT_VERIFIED


def test_passed_comes_only_from_agentgate(tmp_path: Path) -> None:
    """The agent says done in both runs; only the verdict differs."""
    blocked = critic(
        [
            {
                "id": "C1",
                "category": "CORRECTNESS",
                "severity": "HIGH",
                "grounding_status": "in_contract_reachable",
                "violated_requirement": "the task requires this behaviour",
                "code_path": "solution.py:1",
                "trigger": "the documented input",
                "location": "todo.py:3",
                "fix": "the guard rejects valid dates",
            }
        ]
    )

    ok_result, _ = go(tmp_path / "a", SOLVE_TURNS, judge_rounds=[CLEAN_CRITIC])
    blocked_result, _ = go(
        tmp_path / "b",
        SOLVE_TURNS,
        judge_rounds=[blocked],
        limits=Limits(max_repair_rounds=0),
    )

    assert ok_result.report.agent_status == blocked_result.report.agent_status
    assert ok_result.report.status == "PASSED"
    assert blocked_result.report.status == "UNVERIFIED"
    assert blocked_result.exit_code == EXIT_UNVERIFIED


def test_the_report_uses_the_ledger_not_the_models_claim(tmp_path: Path) -> None:
    turns = [
        tool_turn("write_file", {"path": "todo.py", "content": GOOD_FIX, "overwrite": True}),
        final_turn("done", ["invented.py", "never_touched.py"]),
    ]

    result, _ = go(tmp_path, turns)

    assert result.report.files_changed == ["todo.py"]
    assert "invented.py" not in result.report.files_changed


def test_an_automated_gate_failure_blocks(tmp_path: Path) -> None:
    """The agent writes code whose own test suite fails; ruff/mypy/pytest are real."""
    broken = "from todo import parse_due_date\n\n\ndef test_broken() -> None:\n    assert parse_due_date('2026-08-21') == (1, 1, 1)\n"
    turns = [
        tool_turn("write_file", {"path": "test_broken.py", "content": broken}),
        final_turn("added a test", ["test_broken.py"]),
    ]

    result, _ = go(tmp_path, turns, limits=Limits(max_repair_rounds=0))

    failed = [g["gate"] for g in result.report.automated_gates if not g["passed"]]
    assert "pytest" in failed
    assert result.report.status == "UNVERIFIED"
    assert result.exit_code == EXIT_UNVERIFIED


# -- repair ------------------------------------------------------------------


def test_a_repair_round_preserves_earlier_workspace_changes(tmp_path: Path) -> None:
    """The naive length guard breaks the whitespace test; the agent repairs it
    and the first round's regression test survives."""
    workspace = fixture_copy(tmp_path, "todo_cli_repair")
    naive_turns = [
        tool_turn("write_file", {"path": "todo.py", "content": NAIVE_FIX, "overwrite": True}),
        tool_turn("write_file", {"path": "test_due_date.py", "content": REGRESSION_TEST}),
        tool_turn("run_tests"),
        final_turn("added a guard", ["todo.py"]),
        # Repair round: fix the guard, keep everything else.
        tool_turn("write_file", {"path": "todo.py", "content": GOOD_FIX, "overwrite": True}),
        tool_turn("run_tests"),
        final_turn("repaired the guard", ["todo.py"]),
    ]

    result, fake = go(tmp_path, naive_turns, workspace=workspace, limits=Limits(max_repair_rounds=2))

    assert result.report.repairs_used == 1
    # The regression test written in round one was NOT wiped by the repair.
    assert (workspace / "test_due_date.py").exists()
    assert (workspace / "todo.py").read_text(encoding="utf-8") == GOOD_FIX
    assert result.report.status == "PASSED"
    assert fake.judge_calls == 2 * len(LENSES)


def test_the_naive_fix_really_fails_the_existing_test(tmp_path: Path) -> None:
    """Proves the repair fixture earns its name rather than being decorative."""
    workspace = fixture_copy(tmp_path, "todo_cli_repair")
    (workspace / "todo.py").write_text(NAIVE_FIX, encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert completed.returncode != 0
    assert "test_tolerates_surrounding_whitespace" in completed.stdout


def test_repair_feedback_reaches_the_agent(tmp_path: Path) -> None:
    blocked = critic(
        [
            {
                "id": "C1",
                "category": "CORRECTNESS",
                "severity": "HIGH",
                "grounding_status": "in_contract_reachable",
                "violated_requirement": "the task requires this behaviour",
                "code_path": "solution.py:1",
                "trigger": "the documented input",
                "location": "todo.py:3",
                "fix": "use raw.strip() instead of a length check",
            }
        ]
    )
    turns = [*SOLVE_TURNS, final_turn("second pass")]

    _, fake = go(tmp_path, turns, judge_rounds=[blocked, CLEAN_CRITIC])

    repair_openings = [
        messages[0].content
        for messages, system in zip(fake.seen_messages, fake.seen_systems, strict=True)
        if system is not None and "coding agent" in system and "failed verification" in messages[0].content
    ]
    assert repair_openings
    assert "use raw.strip() instead of a length check" in repair_openings[0]


# -- refusals and failures are surfaced --------------------------------------


def test_a_snapshot_that_is_too_large_is_surfaced_not_hidden(tmp_path: Path) -> None:
    turns = [
        tool_turn("write_file", {"path": "big.py", "content": "x = 1\n" * 5_000}),
        final_turn("wrote a big file", ["big.py"]),
    ]

    result, fake = go(tmp_path, turns, limits=Limits(max_snapshot_bytes=200))

    assert result.report.status == "UNVERIFIED"
    assert not result.report.verification_ran
    assert "over max_snapshot_bytes" in result.report.verification_reason
    assert fake.judge_calls == 0  # never asked
    assert result.exit_code == EXIT_UNVERIFIED


def test_an_agent_that_changes_nothing_is_not_verified(tmp_path: Path) -> None:
    result, fake = go(tmp_path, [tool_turn("list_files"), final_turn("looked around")])

    assert result.report.status == "UNVERIFIED"
    assert "changed no files" in result.report.verification_reason
    assert fake.judge_calls == 0


def test_a_provider_failure_is_truthful(tmp_path: Path) -> None:
    class Exploding:
        name = "exploding"

        def generate(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise RuntimeError("connection reset")

    result = run_coding_task(
        task_text=TASK,
        workspace_path=fixture_copy(tmp_path),
        gateway=LLMGateway(Exploding()),
        model=MODEL,
        judge_model=MODEL,
        task_id="cd-app",
    )

    # Planning degrades to UNAVAILABLE; the session then fails and says so.
    assert result.report.planning_status == "UNAVAILABLE"
    assert result.report.agent_status == "ERROR"
    assert result.report.status == "ERROR"
    assert result.exit_code == EXIT_ERROR


def test_a_session_abort_is_reported_as_an_error_not_a_block(tmp_path: Path) -> None:
    result, _ = go(tmp_path, ["prose with no block"], limits=Limits(max_parse_errors=1))

    assert result.report.agent_status == "ABORTED_PROTOCOL"
    assert result.exit_code == EXIT_ERROR


def test_exit_codes_are_distinct_and_truthful() -> None:
    assert exit_code_for(SessionStatus.PASSED) == EXIT_VERIFIED
    assert exit_code_for(SessionStatus.UNVERIFIED) == EXIT_UNVERIFIED
    for status in (
        SessionStatus.ABORTED_TURNS,
        SessionStatus.ABORTED_BUDGET,
        SessionStatus.ABORTED_PROTOCOL,
        SessionStatus.ERROR,
    ):
        assert exit_code_for(status) == EXIT_ERROR


# -- safety holds end to end -------------------------------------------------


def test_nothing_outside_the_workspace_is_touched(tmp_path: Path) -> None:
    outside = tmp_path / "outside.py"
    outside.write_text("SECRET = 1\n", encoding="utf-8")
    turns = [
        tool_turn("write_file", {"path": "../outside.py", "content": "hacked", "overwrite": True}),
        tool_turn("read_file", {"path": "../outside.py"}),
        tool_turn("write_file", {"path": "todo.py", "content": GOOD_FIX, "overwrite": True}),
        final_turn("done", ["todo.py"]),
    ]

    result, _ = go(tmp_path, turns)

    assert outside.read_text(encoding="utf-8") == "SECRET = 1\n"
    assert result.report.files_changed == ["todo.py"]


def test_secrets_in_the_workspace_are_never_read(tmp_path: Path) -> None:
    workspace = fixture_copy(tmp_path)
    (workspace / ".env").write_text("ANTHROPIC_API_KEY=sk-supersecret\n", encoding="utf-8")
    turns = [
        tool_turn("read_file", {"path": ".env"}),
        tool_turn("write_file", {"path": "todo.py", "content": GOOD_FIX, "overwrite": True}),
        final_turn("done", ["todo.py"]),
    ]

    result, fake = go(tmp_path, turns, workspace=workspace)

    assert "sk-supersecret" not in json.dumps([m[-1].content for m in fake.seen_messages])
    assert result.report.status in ("PASSED", "UNVERIFIED")


def test_no_git_write_command_can_run(tmp_path: Path) -> None:
    workspace = fixture_copy(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=workspace, capture_output=True, check=False)
    turns = [
        tool_turn("run_command", {"argv": ["git", "push"]}),
        tool_turn("run_command", {"argv": ["git", "commit", "-m", "x"]}),
        tool_turn("run_command", {"argv": ["git", "reset", "--hard"]}),
        tool_turn("write_file", {"path": "todo.py", "content": GOOD_FIX, "overwrite": True}),
        final_turn("done", ["todo.py"]),
    ]

    result, _ = go(tmp_path, turns, workspace=workspace, limits=Limits(max_consecutive_tool_failures=9))

    denied = [c for c in result.report.commands_run]
    assert denied == []  # nothing reached the executor
    assert (workspace / "todo.py").read_text(encoding="utf-8") == GOOD_FIX


# -- artifacts ---------------------------------------------------------------


def test_artifacts_are_written(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"

    result, _ = go(tmp_path, SOLVE_TURNS, artifacts=artifacts)

    assert result.report_path is not None
    assert result.log_path is not None
    payload = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert payload["status"] == "PASSED"
    assert payload["agent_status"] == "COMPLETED_UNVERIFIED"
    kinds = [json.loads(line)["kind"] for line in
             result.log_path.read_text(encoding="utf-8").strip().splitlines()]
    # Planning shares the log and runs first, so the stream opens with it.
    assert kinds[0] == "plan_attempt"
    assert kinds.index("plan_result") < kinds.index("session_start")
    for kind in ("session_start", "tool_call", "verification_start",
                 "verification_result", "run_result"):
        assert kind in kinds, kind


def test_the_report_json_is_complete(tmp_path: Path) -> None:
    result, _ = go(tmp_path, SOLVE_TURNS)

    payload = json.loads(result.report.to_json())

    for key in (
        "task_id", "user_goal", "status", "agent_status", "stop_reason",
        "files_changed", "commands_run", "test_results", "plan", "planning_status",
        "planning_attempts", "turns_used", "tool_calls", "repairs_used",
        "tokens_spent", "spend", "verification_status", "defects",
        "automated_gates", "limits", "summary",
    ):
        assert key in payload, key
    assert payload["summary"].startswith("guarded empty input")


def test_human_output_states_both_claims(tmp_path: Path) -> None:
    from engine.codeagent.report import render_report

    result, _ = go(tmp_path, SOLVE_TURNS)
    rendered = render_report(result.report)

    assert "PASSED" in rendered
    assert "COMPLETED_UNVERIFIED" in rendered
    assert "todo.py" in rendered


# -- the CLI itself ----------------------------------------------------------


class _GatewayFactory:
    """Stands in for LLMGateway in cli.py so no API key is needed."""

    def __init__(self, fake: ScenarioProvider) -> None:
        self._fake = fake

    def from_config(self, provider_name: str, config: object) -> LLMGateway:
        return LLMGateway(self._fake)


def invoke_cli(monkeypatch, argv: list[str], fake: ScenarioProvider, tmp_path: Path) -> int:
    monkeypatch.setenv("ENGINE_DB_PATH", str(tmp_path / "state.db"))
    monkeypatch.setattr(cli, "LLMGateway", _GatewayFactory(fake))
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as exc:
        cli.main()
    return int(exc.value.code or 0)


def test_cli_runs_the_real_flow_and_exits_zero_on_verified(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    workspace = fixture_copy(tmp_path)
    fake = provider(SOLVE_TURNS)

    code = invoke_cli(
        monkeypatch,
        ["engine", "code", TASK, "--workspace", str(workspace), "--budget", "5.00"],
        fake,
        tmp_path,
    )

    assert code == EXIT_VERIFIED
    out = capsys.readouterr().out
    assert "PASSED" in out
    assert (workspace / "todo.py").read_text(encoding="utf-8") == GOOD_FIX
    assert fake.judge_calls == len(LENSES)


def test_cli_exits_one_when_verification_blocks(monkeypatch, capsys, tmp_path: Path) -> None:
    blocked = critic(
        [
            {
                "id": "C1",
                "category": "SECURITY",
                "severity": "CRITICAL",
                "grounding_status": "in_contract_reachable",
                "violated_requirement": "the task requires this behaviour",
                "code_path": "solution.py:1",
                "trigger": "the documented input",
                "location": "todo.py:1",
                "fix": "do not do that",
            }
        ]
    )
    fake = ScenarioProvider(
        agent_turns=SOLVE_TURNS,
        plan_turns=[PLAN],
        judge_rounds=[blocked],
        lens_prompts=LENS_PROMPTS,
    )

    code = invoke_cli(
        monkeypatch,
        [
            "engine", "code", TASK,
            "--workspace", str(fixture_copy(tmp_path)),
            "--max-repairs", "0",
        ],
        fake,
        tmp_path,
    )

    assert code == EXIT_UNVERIFIED
    assert "NOT VERIFIED" in capsys.readouterr().out


def test_cli_exits_two_on_a_bad_workspace(monkeypatch, capsys, tmp_path: Path) -> None:
    code = invoke_cli(
        monkeypatch,
        ["engine", "code", TASK, "--workspace", str(tmp_path / "nope")],
        provider(SOLVE_TURNS),
        tmp_path,
    )

    assert code == EXIT_ERROR
    assert "ERROR" in capsys.readouterr().out


def test_cli_requires_an_explicit_workspace(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "argv", ["engine", "code", TASK])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2  # argparse usage error


def test_cli_writes_json_when_asked(monkeypatch, tmp_path: Path) -> None:
    json_path = tmp_path / "report.json"

    invoke_cli(
        monkeypatch,
        [
            "engine", "code", TASK,
            "--workspace", str(fixture_copy(tmp_path)),
            "--json", str(json_path),
        ],
        provider(SOLVE_TURNS),
        tmp_path,
    )

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["status"] == "PASSED"
    assert payload["files_changed"] == ["todo.py", "test_due_date.py"]


def test_cli_honours_limit_flags(monkeypatch, tmp_path: Path) -> None:
    fake = provider(SOLVE_TURNS)

    code = invoke_cli(
        monkeypatch,
        [
            "engine", "code", TASK,
            "--workspace", str(fixture_copy(tmp_path)),
            "--max-turns", "2",
        ],
        fake,
        tmp_path,
    )

    # Two turns is not enough to finish, so the run aborts truthfully.
    assert code == EXIT_ERROR
    assert fake.agent_calls == 2


def test_cli_records_the_run_in_the_database(monkeypatch, tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"

    invoke_cli(
        monkeypatch,
        ["engine", "code", TASK, "--workspace", str(fixture_copy(tmp_path))],
        provider(SOLVE_TURNS),
        tmp_path,
    )

    from engine.state import db

    with db.connect(db_path) as conn:
        runs = conn.execute("SELECT id, status FROM runs").fetchall()
        metrics = conn.execute(
            "SELECT agent_name FROM agent_execution_metrics WHERE run_id = ?", (runs[0][0],)
        ).fetchall()

    assert runs[0][1] == "passed"
    names = {row[0] for row in metrics}
    assert "CodingAgent.plan" in names
    assert "CodingAgent.turn" in names
    assert any(name.startswith("judge:") for name in names)
