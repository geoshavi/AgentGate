import json
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pytest
from codeagent_harness import MODEL, ScriptedProvider, StepClock, final_turn, tool_turn

from engine.codeagent import report as report_module
from engine.codeagent import verify as verify_module
from engine.codeagent.limits import Limits
from engine.codeagent.log import SessionLog
from engine.codeagent.report import build_report, render_report
from engine.codeagent.state import SessionStatus
from engine.codeagent.verify import (
    VerificationOutcome,
    render_repair_feedback,
    run_verified_session,
    sanitize_defects,
    snapshot_scope,
    verify_workspace,
)
from engine.codeagent.workspace import Workspace
from engine.llm_types import GenerationResult, Message
from engine.runtime.budget import BudgetController, BudgetExceededError
from engine.runtime.gateway import LLMGateway
from engine.state.models import VerificationResult
from engine.verification.judge import LENSES
from engine.verification.pipeline import read_code_snapshot

JUDGE_MODEL = MODEL


def ws(tmp_path: Path) -> Workspace:
    root = tmp_path / "ws"
    root.mkdir(exist_ok=True)
    return Workspace(root)


def budget(max_tokens: int = 1_000_000, planned: str = "10.00") -> BudgetController:
    return BudgetController(max_tokens=max_tokens, planned_budget=Decimal(planned))


def defect(severity: str = "HIGH", **overrides: object) -> dict:
    base = {
        "id": "C1",
        "category": "CORRECTNESS",
        "severity": severity,
        "location": "todo.py:1",
        "fix": "guard the empty string",
        "grounding_status": "in_contract_reachable",
    }
    if severity in ("CRITICAL", "HIGH"):
        base.update(
            {
                "violated_requirement": "the task requires this behaviour",
                "code_path": "todo.py:1",
                "trigger": "the documented input",
            }
        )
    base.update(overrides)
    return base


def gates(passed: bool = True) -> list[VerificationResult]:
    return [VerificationResult("ruff", passed, "All checks passed!" if passed else "E501 too long")]


class FakeVerifier:
    """Stands in for pipeline.run_verification, one scripted result per call."""

    def __init__(self, results: list[tuple[str, dict, list[VerificationResult]]]) -> None:
        self._results = results
        self.calls: list[dict] = []

    def __call__(self, workspace, gateway, budget_, judge_model, task_text, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(
            {
                "workspace": workspace,
                "judge_model": judge_model,
                "task_text": task_text,
                **kwargs,
            }
        )
        index = min(len(self.calls) - 1, len(self._results) - 1)
        return self._results[index]


class RaisingVerifier:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc
        self.calls = 0

    def __call__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        self.calls += 1
        raise self._exc


class JudgingProvider:
    """Answers agent turns and judge lens calls from one provider.

    Routes on the system prompt: a judge call carries one of LENSES' texts, an
    agent turn carries the codeagent system prompt. Lets a test drive the real
    run_verification -- real lenses, real schema validation, real verdict.gate
    -- with no network and no API key.
    """

    name = "judging"

    def __init__(self, agent_turns: list[str], judge_rounds: list[str]) -> None:
        self._agent_turns = agent_turns
        self._judge_rounds = judge_rounds
        self.agent_calls = 0
        self.judge_calls = 0

    def generate(
        self,
        messages: list[Message],
        model: str,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        timeout_seconds: float | None = None,
        thinking_disabled: bool = False,
    ) -> GenerationResult:
        is_judge = system in set(LENSES.values())
        if is_judge:
            # Three lenses per verification round.
            round_index = min(self.judge_calls // len(LENSES), len(self._judge_rounds) - 1)
            self.judge_calls += 1
            text = self._judge_rounds[round_index]
        else:
            index = min(self.agent_calls, len(self._agent_turns) - 1)
            self.agent_calls += 1
            text = self._agent_turns[index]
        return GenerationResult(
            text=text,
            model=model,
            provider=self.name,
            input_tokens=10,
            output_tokens=20,
            stop_reason="end_turn",
        )


CLEAN_CRITIC = json.dumps({"defects": [], "verdict": "OK"})
BLOCKING_CRITIC = json.dumps({"defects": [defect()], "verdict": "FAIL"})


def run(
    tmp_path: Path,
    agent_turns: list[str],
    *,
    verifier: object,
    limits: Limits | None = None,
    workspace: Workspace | None = None,
    log: SessionLog | None = None,
):  # type: ignore[no-untyped-def]
    provider = ScriptedProvider(agent_turns)
    return (
        run_verified_session(
            task_text="fix parse_due_date",
            workspace=workspace if workspace is not None else ws(tmp_path),
            gateway=LLMGateway(provider),
            budget=budget(),
            model=MODEL,
            judge_model=JUDGE_MODEL,
            task_id="cd-test",
            limits=limits if limits is not None else Limits(),
            log=log if log is not None else SessionLog(),
            clock=StepClock(step=0.0),
            verifier=verifier,  # type: ignore[arg-type]
        ),
        provider,
    )


WRITE_AND_FINISH = [
    tool_turn("write_file", {"path": "todo.py", "content": "def f() -> int:\n    return 1\n"}),
    final_turn("wrote todo.py", ["todo.py"]),
]


# -- snapshot scoping --------------------------------------------------------


def test_snapshot_scope_measures_the_same_glob_verification_inlines(tmp_path: Path) -> None:
    workspace = ws(tmp_path)
    (workspace.root / "a.py").write_text("x = 1\n", encoding="utf-8")
    (workspace.root / "pkg").mkdir()
    (workspace.root / "pkg" / "b.py").write_text("y = 2\n", encoding="utf-8")
    (workspace.root / "notes.md").write_text("ignored\n", encoding="utf-8")

    scope = snapshot_scope(workspace)

    assert scope.files == ["a.py", "pkg/b.py"]
    assert scope.total_bytes > 0
    assert scope.within_limit


def test_snapshot_scope_reports_an_empty_workspace(tmp_path: Path) -> None:
    scope = snapshot_scope(ws(tmp_path))

    assert scope.is_empty
    assert scope.files == []


def test_snapshot_scope_detects_an_oversized_workspace(tmp_path: Path) -> None:
    workspace = ws(tmp_path)
    (workspace.root / "big.py").write_text("x = 1\n" * 5_000, encoding="utf-8")

    scope = snapshot_scope(workspace, Limits(max_snapshot_bytes=100))

    assert not scope.within_limit
    assert scope.total_bytes > 100


def _write_lf(path: Path, text: str) -> None:
    """Write with LF on disk regardless of platform.

    ``Path.write_text`` translates "\\n" to os.linesep on Windows, which would
    make st_size disagree with the character count ``read_text`` yields and
    silently change the byte arithmetic these tests pin.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def test_snapshot_scope_estimate_tracks_the_real_snapshot_by_a_fixed_offset(
    tmp_path: Path,
) -> None:
    """``snapshot_scope`` estimates; ``read_code_snapshot`` builds the real
    payload. For ASCII source stored with LF the two differ by exactly
    ``2 - n_files``, because the estimator charges a flat 12 bytes of header
    per file where the real header costs 11 plus a 2-byte join between files.

    Pinned because this arithmetic is what makes a recorded ``snapshot_bytes``
    checkable against on-disk content after the fact -- the step that ruled
    staleness out of a live false-UNVERIFIED diagnosis.
    """
    workspace = ws(tmp_path)
    for count in (1, 2, 3, 5):
        for existing in workspace.root.rglob("*.py"):
            existing.unlink()
        for i in range(count):
            _write_lf(workspace.root / f"f{i}.py", f"x{i} = {i}\n")

        estimate = snapshot_scope(workspace).total_bytes
        actual = len(read_code_snapshot(workspace.root))

        assert estimate - actual == 2 - count, f"offset drifted at {count} file(s)"


def test_snapshot_scope_under_estimates_once_three_or_more_files_are_present(
    tmp_path: Path,
) -> None:
    """The direction of the error, stated explicitly.

    The ceiling is not a strict over-estimate: at three files or more the
    estimate falls below the real payload by ``n - 2`` characters, so a
    workspace can pass ``within_limit`` while the string handed to the judges
    is fractionally larger. Bounded and tiny (``max_graph_files_scanned`` caps
    a realistic tree at ~3k files against a 200k limit), but real, and the
    docstring on ``SnapshotScope`` says so rather than claiming otherwise.
    """
    workspace = ws(tmp_path)
    for i in range(4):
        _write_lf(workspace.root / f"f{i}.py", "x = 1\n")

    assert snapshot_scope(workspace).total_bytes < len(read_code_snapshot(workspace.root))


def test_a_single_non_ascii_file_still_over_estimates(tmp_path: Path) -> None:
    """The offsetting effect the docstring describes is real, just not total:
    one multi-byte file costs more on disk than in characters, which pushes the
    estimate back above the payload."""
    workspace = ws(tmp_path)
    _write_lf(workspace.root / "u.py", '# ≤≥≤≥≤≥≤≥≤≥\nx = 1\n')

    assert snapshot_scope(workspace).total_bytes > len(read_code_snapshot(workspace.root))


# -- the pre-checks refuse rather than truncate ------------------------------


def test_an_oversized_snapshot_declines_to_verify(tmp_path: Path) -> None:
    workspace = ws(tmp_path)
    (workspace.root / "big.py").write_text("x = 1\n" * 5_000, encoding="utf-8")
    verifier = FakeVerifier([(("OK"), {"defects": [], "verdict": "OK"}, gates())])

    outcome = verify_workspace(
        workspace=workspace,
        task_text="t",
        gateway=LLMGateway(ScriptedProvider([""])),
        budget=budget(),
        judge_model=JUDGE_MODEL,
        task_id="cd-test",
        limits=Limits(max_snapshot_bytes=100),
        changed_files=["big.py"],
        verifier=verifier,
    )

    assert outcome.status == "UNVERIFIED"
    assert not outcome.ran
    assert not outcome.repairable
    assert "over max_snapshot_bytes" in outcome.reason
    assert "refusing to verify rather than verify truncated source" in outcome.reason
    # The decisive assertion: the judge was never asked.
    assert verifier.calls == []


def test_no_changed_files_declines_to_verify(tmp_path: Path) -> None:
    workspace = ws(tmp_path)
    (workspace.root / "preexisting.py").write_text("x = 1\n", encoding="utf-8")
    verifier = FakeVerifier([("OK", {"defects": [], "verdict": "OK"}, gates())])

    outcome = verify_workspace(
        workspace=workspace,
        task_text="t",
        gateway=LLMGateway(ScriptedProvider([""])),
        budget=budget(),
        judge_model=JUDGE_MODEL,
        task_id="cd-test",
        changed_files=[],
        verifier=verifier,
    )

    assert outcome.status == "UNVERIFIED"
    assert not outcome.ran
    assert "changed no files" in outcome.reason
    # Pre-existing code is never verified as if the agent had written it.
    assert verifier.calls == []


def test_an_empty_workspace_declines_to_verify(tmp_path: Path) -> None:
    verifier = FakeVerifier([("OK", {"defects": [], "verdict": "OK"}, gates())])

    outcome = verify_workspace(
        workspace=ws(tmp_path),
        task_text="t",
        gateway=LLMGateway(ScriptedProvider([""])),
        budget=budget(),
        judge_model=JUDGE_MODEL,
        task_id="cd-test",
        changed_files=["notes.md"],
        verifier=verifier,
    )

    assert not outcome.ran
    assert "no Python files" in outcome.reason
    assert verifier.calls == []


# -- the adapter calls the pipeline unchanged --------------------------------


def test_the_verifier_receives_the_workspace_root_and_task(tmp_path: Path) -> None:
    workspace = ws(tmp_path)
    (workspace.root / "todo.py").write_text("x = 1\n", encoding="utf-8")
    verifier = FakeVerifier([("OK", {"defects": [], "verdict": "OK"}, gates())])

    verify_workspace(
        workspace=workspace,
        task_text="fix the guard",
        gateway=LLMGateway(ScriptedProvider([""])),
        budget=budget(),
        judge_model=JUDGE_MODEL,
        task_id="cd-42",
        run_id=7,
        changed_files=["todo.py"],
        verifier=verifier,
    )

    call = verifier.calls[0]
    assert call["workspace"] == workspace.root
    assert call["task_text"] == "fix the guard"
    assert call["judge_model"] == JUDGE_MODEL
    assert call["task_id"] == "cd-42"
    assert call["run_id"] == 7
    # No new parameters and no hooks are introduced by this client.
    assert set(call) == {
        "workspace",
        "judge_model",
        "task_text",
        "run_id",
        "task_id",
        "conn",
        "timeout_seconds",
    }


def test_a_verifier_exception_fails_closed(tmp_path: Path) -> None:
    workspace = ws(tmp_path)
    (workspace.root / "todo.py").write_text("x = 1\n", encoding="utf-8")
    verifier = RaisingVerifier(RuntimeError("judge exploded"))

    outcome = verify_workspace(
        workspace=workspace,
        task_text="t",
        gateway=LLMGateway(ScriptedProvider([""])),
        budget=budget(),
        judge_model=JUDGE_MODEL,
        task_id="cd-test",
        changed_files=["todo.py"],
        verifier=verifier,
    )

    assert outcome.status == "UNVERIFIED"
    assert not outcome.passed
    assert not outcome.ran
    assert "RuntimeError" in outcome.reason


def test_budget_exhaustion_during_verification_fails_closed(tmp_path: Path) -> None:
    workspace = ws(tmp_path)
    (workspace.root / "todo.py").write_text("x = 1\n", encoding="utf-8")
    verifier = RaisingVerifier(BudgetExceededError("spend budget would be exceeded"))

    outcome = verify_workspace(
        workspace=workspace,
        task_text="t",
        gateway=LLMGateway(ScriptedProvider([""])),
        budget=budget(),
        judge_model=JUDGE_MODEL,
        task_id="cd-test",
        changed_files=["todo.py"],
        verifier=verifier,
    )

    assert outcome.status == "UNVERIFIED"
    assert "budget exhausted during verification" in outcome.reason


# -- defect sanitising -------------------------------------------------------


def test_sanitize_keeps_the_schema_keys_and_the_emitting_lens() -> None:
    raw = [dict(defect(), reasoning="MY HIDDEN CHAIN OF THOUGHT", lens="correctness")]

    cleaned = sanitize_defects(raw)

    assert set(cleaned[0]) == {"id", "category", "severity", "location", "fix", "grounding_status", "lens"}
    assert "reasoning" not in cleaned[0]


def test_sanitize_preserves_which_lens_emitted_a_defect() -> None:
    """The forensic property: a defect's category is the model's claim about
    itself, and the lens is the ground truth of which reviewer produced it. The
    two are not required to agree, so the second cannot be inferred from the
    first."""
    cleaned = sanitize_defects([dict(defect(), category="CORRECTNESS", lens="security")])

    assert cleaned[0]["category"] == "CORRECTNESS"
    assert cleaned[0]["lens"] == "security"


def test_sanitize_does_not_invent_a_lens_for_an_untagged_defect() -> None:
    """Automated-gate defects come from automated_defects(), not a lens. An
    absent key is honest; a fabricated one would attribute ruff to a judge."""
    cleaned = sanitize_defects([defect()])

    assert "lens" not in cleaned[0]


def test_defects_from_two_lenses_sharing_an_id_stay_distinguishable() -> None:
    """Defect ids are numbered per lens, so two lenses both emit "C1". Before
    the lens survived sanitising these two collapsed into indistinguishable
    dicts in the report."""
    raw = [
        dict(defect(), id="C1", lens="correctness"),
        dict(defect(), id="C1", lens="security"),
    ]

    cleaned = sanitize_defects(raw)

    assert [d["lens"] for d in cleaned] == ["correctness", "security"]
    assert cleaned[0] != cleaned[1]


def test_lens_metadata_changes_no_verdict(tmp_path: Path) -> None:
    """Observability only: the same defects tagged and untagged must produce
    the same status, the same reason and the same severities."""
    outcomes = []
    for tagged in (False, True):
        root = tmp_path / f"run-{tagged}"
        root.mkdir()
        workspace = ws(root)
        (workspace.root / "todo.py").write_text("x = 1\n", encoding="utf-8")
        raw = dict(defect(), lens="security") if tagged else defect()
        outcomes.append(
            verify_workspace(
                workspace=workspace,
                task_text="t",
                gateway=LLMGateway(ScriptedProvider([""])),
                budget=budget(),
                judge_model=JUDGE_MODEL,
                task_id="cd-test",
                changed_files=["todo.py"],
                verifier=FakeVerifier([("UNVERIFIED", {"defects": [raw]}, gates())]),
            )
        )

    plain, tagged_outcome = outcomes
    assert plain.status == tagged_outcome.status == "UNVERIFIED"
    assert plain.reason == tagged_outcome.reason
    assert [d["severity"] for d in plain.defects] == [
        d["severity"] for d in tagged_outcome.defects
    ]
    assert "lens" not in plain.defects[0]
    assert tagged_outcome.defects[0]["lens"] == "security"


def test_repair_feedback_is_unchanged_by_lens_metadata(tmp_path: Path) -> None:
    """The agent's brief is structured evidence, not judge provenance. Adding
    the lens must not change a byte of what the fixing model reads."""
    feedbacks = []
    for tagged in (False, True):
        root = tmp_path / f"fb-{tagged}"
        root.mkdir()
        workspace = ws(root)
        (workspace.root / "todo.py").write_text("x = 1\n", encoding="utf-8")
        raw = dict(defect(), lens="security") if tagged else defect()
        outcome = verify_workspace(
            workspace=workspace,
            task_text="t",
            gateway=LLMGateway(ScriptedProvider([""])),
            budget=budget(),
            judge_model=JUDGE_MODEL,
            task_id="cd-test",
            changed_files=["todo.py"],
            verifier=FakeVerifier([("UNVERIFIED", {"defects": [raw]}, gates())]),
        )
        feedbacks.append(render_repair_feedback(outcome))

    assert feedbacks[0] == feedbacks[1]
    assert "security" not in feedbacks[1]


# -- snapshot fidelity -------------------------------------------------------


def test_the_snapshot_verification_reads_reflects_the_latest_edit(tmp_path: Path) -> None:
    """Regression guard for the hypothesis that a judge could be shown pre-fix
    source: read_code_snapshot reads from disk at call time, so an edit made
    before verification is the thing verification sees."""
    workspace = ws(tmp_path)
    source = workspace.root / "cart.py"
    source.write_text("def total():\n    return min([])\n", encoding="utf-8")
    before = read_code_snapshot(workspace.root)

    source.write_text("def total():\n    return 0.0\n", encoding="utf-8")
    after = read_code_snapshot(workspace.root)

    assert "min([])" in before
    assert "min([])" not in after
    assert "return 0.0" in after


def test_recorded_snapshot_bytes_describe_the_post_edit_source(tmp_path: Path) -> None:
    """The bytes a run records must identify the source the judges were shown.

    ``verify_workspace`` emits ``scope.total_bytes`` and the report keeps it.
    That number is only useful if it pins down *which* version of the tree was
    verified -- which is precisely how a live false-UNVERIFIED was cleared of
    staleness after the fact: the recorded count reproduced from the post-fix
    files and could not have come from the pre-fix ones.
    """
    workspace = ws(tmp_path)
    source = workspace.root / "cart.py"

    _write_lf(source, "def total():\n    return min([])\n")
    before_bytes = snapshot_scope(workspace).total_bytes

    _write_lf(source, "def total():\n    return 0.0\n")
    after_bytes = snapshot_scope(workspace).total_bytes

    assert before_bytes != after_bytes, "the count must distinguish the two versions"
    # One file: the estimate sits exactly one character above the real payload.
    assert after_bytes - len(read_code_snapshot(workspace.root)) == 1


def test_extra_defect_keys_never_reach_the_agent_or_the_report(tmp_path: Path) -> None:
    secret = "HIDDEN JUDGE REASONING"
    workspace = ws(tmp_path)
    (workspace.root / "todo.py").write_text("x = 1\n", encoding="utf-8")
    merged = {"defects": [dict(defect(), reasoning=secret)], "verdict": "FAIL"}
    verifier = FakeVerifier([("UNVERIFIED", merged, gates())])

    outcome = verify_workspace(
        workspace=workspace,
        task_text="t",
        gateway=LLMGateway(ScriptedProvider([""])),
        budget=budget(),
        judge_model=JUDGE_MODEL,
        task_id="cd-test",
        changed_files=["todo.py"],
        verifier=verifier,
    )

    assert secret not in json.dumps(outcome.defects)
    assert secret not in render_repair_feedback(outcome)


def test_repair_feedback_carries_only_structured_evidence() -> None:
    outcome = VerificationOutcome(
        status="UNVERIFIED",
        reason="blocked",
        ran=True,
        defects=[defect()],
        schema_errors=["correctness: malformed JSON"],
    )

    feedback = render_repair_feedback(outcome)

    assert "CORRECTNESS/HIGH" in feedback
    assert "todo.py:1" in feedback
    assert "guard the empty string" in feedback
    assert "review-schema-error" in feedback


# -- verdict mapping ---------------------------------------------------------


def test_an_ok_verdict_is_the_only_route_to_passed(tmp_path: Path) -> None:
    verifier = FakeVerifier([("OK", {"defects": [], "verdict": "OK"}, gates())])

    result, _ = run(tmp_path, WRITE_AND_FINISH, verifier=verifier)

    assert result.status is SessionStatus.PASSED
    assert result.agent_status is SessionStatus.COMPLETED_UNVERIFIED
    assert result.final_state.verification_status == "OK"
    assert result.repairs_used == 0


def test_blocking_defects_map_to_unverified(tmp_path: Path) -> None:
    verifier = FakeVerifier([("UNVERIFIED", {"defects": [defect()], "verdict": "FAIL"}, gates())])

    result, _ = run(tmp_path, WRITE_AND_FINISH, verifier=verifier, limits=Limits(max_repair_rounds=0))

    assert result.status is SessionStatus.UNVERIFIED
    assert result.agent_status is SessionStatus.COMPLETED_UNVERIFIED
    assert "1 blocking defect(s)" in result.reason


def test_an_automated_gate_failure_maps_to_unverified(tmp_path: Path) -> None:
    verifier = FakeVerifier(
        [("UNVERIFIED", {"defects": [], "verdict": "OK"}, gates(passed=False))]
    )

    result, _ = run(tmp_path, WRITE_AND_FINISH, verifier=verifier, limits=Limits(max_repair_rounds=0))

    assert result.status is SessionStatus.UNVERIFIED
    assert "failed gate(s): ruff" in result.reason


def test_malformed_judge_evidence_maps_to_unverified(tmp_path: Path) -> None:
    merged = {"defects": [], "verdict": "OK", "schema_errors": ["security: not JSON"]}
    verifier = FakeVerifier([("UNVERIFIED", merged, gates())])

    result, _ = run(tmp_path, WRITE_AND_FINISH, verifier=verifier, limits=Limits(max_repair_rounds=0))

    assert result.status is SessionStatus.UNVERIFIED
    assert "1 malformed judge response(s)" in result.reason


def test_there_is_no_third_probably_okay_state(tmp_path: Path) -> None:
    for verifier in (
        FakeVerifier([("UNVERIFIED", {"defects": [defect("MEDIUM")], "verdict": "OK"}, gates())]),
        RaisingVerifier(RuntimeError("boom")),
    ):
        result, _ = run(
            tmp_path, WRITE_AND_FINISH, verifier=verifier, limits=Limits(max_repair_rounds=0)
        )
        assert result.status in (SessionStatus.PASSED, SessionStatus.UNVERIFIED)
        assert result.status is SessionStatus.UNVERIFIED


def test_an_aborted_agent_is_never_verified(tmp_path: Path) -> None:
    verifier = FakeVerifier([("OK", {"defects": [], "verdict": "OK"}, gates())])

    result, _ = run(tmp_path, ["prose with no block"], verifier=verifier, limits=Limits(max_parse_errors=1))

    assert result.agent_status is SessionStatus.ABORTED_PROTOCOL
    assert result.status is SessionStatus.ABORTED_PROTOCOL
    assert result.verification is None
    assert verifier.calls == []


# -- the repair loop ---------------------------------------------------------


def test_one_repair_round_can_reach_passed(tmp_path: Path) -> None:
    verifier = FakeVerifier(
        [
            ("UNVERIFIED", {"defects": [defect()], "verdict": "FAIL"}, gates()),
            ("OK", {"defects": [], "verdict": "OK"}, gates()),
        ]
    )
    turns = [
        *WRITE_AND_FINISH,
        tool_turn("write_file", {"path": "fix.py", "content": "y = 2\n"}),
        final_turn("repaired"),
    ]

    result, _ = run(tmp_path, turns, verifier=verifier)

    assert result.status is SessionStatus.PASSED
    assert result.repairs_used == 1
    assert len(result.states) == 2
    assert len(verifier.calls) == 2


def test_the_workspace_is_not_reset_between_repairs(tmp_path: Path) -> None:
    """The blueprint invariant: a repair continues from the accumulated diff."""
    workspace = ws(tmp_path)
    verifier = FakeVerifier(
        [
            ("UNVERIFIED", {"defects": [defect()], "verdict": "FAIL"}, gates()),
            ("OK", {"defects": [], "verdict": "OK"}, gates()),
        ]
    )
    turns = [
        *WRITE_AND_FINISH,
        tool_turn("write_file", {"path": "second.py", "content": "y = 2\n"}),
        final_turn("repaired"),
    ]

    result, _ = run(tmp_path, turns, verifier=verifier, workspace=workspace)

    # Round one's file survives round two, and the ledger is cumulative.
    assert (workspace.root / "todo.py").exists()
    assert (workspace.root / "second.py").exists()
    assert result.final_state.files_changed == ["todo.py", "second.py"]


def test_repair_feedback_reaches_the_repair_session(tmp_path: Path) -> None:
    verifier = FakeVerifier(
        [
            ("UNVERIFIED", {"defects": [defect()], "verdict": "FAIL"}, gates()),
            ("OK", {"defects": [], "verdict": "OK"}, gates()),
        ]
    )
    turns = [*WRITE_AND_FINISH, final_turn("repaired")]

    _, provider = run(tmp_path, turns, verifier=verifier)

    repair_opening = provider.seen_messages[2][0].content
    assert "failed verification" in repair_opening
    assert "guard the empty string" in repair_opening


def test_repair_still_blocked_ends_unverified(tmp_path: Path) -> None:
    verifier = FakeVerifier([("UNVERIFIED", {"defects": [defect()], "verdict": "FAIL"}, gates())])
    turns = [*WRITE_AND_FINISH, final_turn("tried"), final_turn("tried again")]

    result, _ = run(tmp_path, turns, verifier=verifier, limits=Limits(max_repair_rounds=2))

    assert result.status is SessionStatus.UNVERIFIED
    assert result.repairs_used == 2
    assert "repair budget exhausted after 2 round(s)" in result.reason


def test_the_repair_loop_is_bounded(tmp_path: Path) -> None:
    verifier = FakeVerifier([("UNVERIFIED", {"defects": [defect()], "verdict": "FAIL"}, gates())])
    turns = [*WRITE_AND_FINISH, final_turn("again")]

    result, _ = run(tmp_path, turns, verifier=verifier, limits=Limits(max_repair_rounds=1))

    assert result.repairs_used == 1
    assert len(verifier.calls) == 2  # initial + one after the single repair


def test_zero_repair_rounds_never_repairs(tmp_path: Path) -> None:
    verifier = FakeVerifier([("UNVERIFIED", {"defects": [defect()], "verdict": "FAIL"}, gates())])

    result, _ = run(tmp_path, WRITE_AND_FINISH, verifier=verifier, limits=Limits(max_repair_rounds=0))

    assert result.repairs_used == 0
    assert len(verifier.calls) == 1
    assert "repair budget exhausted" not in result.reason


def test_a_repair_session_that_aborts_stops_the_loop(tmp_path: Path) -> None:
    verifier = FakeVerifier([("UNVERIFIED", {"defects": [defect()], "verdict": "FAIL"}, gates())])
    # The repair round emits prose forever and dies on the protocol bound.
    turns = [*WRITE_AND_FINISH, "no block at all"]

    result, _ = run(
        tmp_path, turns, verifier=verifier, limits=Limits(max_repair_rounds=2, max_parse_errors=1)
    )

    assert result.status is SessionStatus.UNVERIFIED
    assert result.repairs_used == 1
    assert result.states[-1].status is SessionStatus.ABORTED_PROTOCOL
    assert "repair round 1 ended ABORTED_PROTOCOL" in result.reason
    # The aborted round was not re-verified.
    assert len(verifier.calls) == 1


def test_an_unrepairable_outcome_never_enters_the_repair_loop(tmp_path: Path) -> None:
    """A declined verification has no defects, so there is nothing to repair."""
    verifier = FakeVerifier([("OK", {"defects": [], "verdict": "OK"}, gates())])
    turns = [tool_turn("list_files"), final_turn("did nothing")]

    result, _ = run(tmp_path, turns, verifier=verifier)

    assert result.status is SessionStatus.UNVERIFIED
    assert result.repairs_used == 0
    assert result.verification is not None
    assert not result.verification.ran
    assert verifier.calls == []


def test_repairs_share_the_turn_allowance(tmp_path: Path) -> None:
    """Repair rounds draw from the same max_turns pool, so they cannot extend
    the session past its own bound."""
    verifier = FakeVerifier([("UNVERIFIED", {"defects": [defect()], "verdict": "FAIL"}, gates())])
    turns = [*WRITE_AND_FINISH, final_turn("r1"), final_turn("r2")]

    result, _ = run(
        tmp_path, turns, verifier=verifier, limits=Limits(max_turns=3, max_repair_rounds=2)
    )

    total = sum(state.usage.turns_used for state in result.states)
    assert total <= 3


# -- end to end through the real pipeline ------------------------------------


def real_run(
    tmp_path: Path, agent_turns: list[str], judge_rounds: list[str], limits: Limits | None = None
):  # type: ignore[no-untyped-def]
    provider = JudgingProvider(agent_turns, judge_rounds)
    return (
        run_verified_session(
            task_text="add a function",
            workspace=ws(tmp_path),
            gateway=LLMGateway(provider),
            budget=budget(),
            model=MODEL,
            judge_model=JUDGE_MODEL,
            task_id="cd-real",
            limits=limits if limits is not None else Limits(),
            log=SessionLog(),
            clock=StepClock(step=0.0),
        ),
        provider,
    )


GOOD_CODE = 'def add(a: int, b: int) -> int:\n    return a + b\n'
GOOD_TEST = "from mod import add\n\n\ndef test_add() -> None:\n    assert add(1, 2) == 3\n"


def test_real_pipeline_clean_run_reaches_passed(tmp_path: Path) -> None:
    """The genuine article: real run_verification, real ruff/mypy/pytest gates,
    real schema validation, real verdict.gate. Only the model is faked."""
    turns = [
        tool_turn("write_file", {"path": "mod.py", "content": GOOD_CODE}),
        tool_turn("write_file", {"path": "test_mod.py", "content": GOOD_TEST}),
        final_turn("added add()", ["mod.py"]),
    ]

    result, provider = real_run(tmp_path, turns, [CLEAN_CRITIC])

    assert result.status is SessionStatus.PASSED
    assert result.verification is not None
    assert result.verification.ran
    assert provider.judge_calls == len(LENSES)  # all three lenses really ran
    assert all(gate.passed for gate in result.verification.automated_gates)


def test_real_pipeline_blocking_defect_reaches_unverified(tmp_path: Path) -> None:
    turns = [
        tool_turn("write_file", {"path": "mod.py", "content": GOOD_CODE}),
        final_turn("added add()", ["mod.py"]),
    ]

    result, _ = real_run(tmp_path, turns, [BLOCKING_CRITIC], Limits(max_repair_rounds=0))

    assert result.status is SessionStatus.UNVERIFIED
    assert result.verification is not None
    assert result.verification.ran
    # verdict.gate blocked on severity, and the defects came back structured.
    assert result.verification.defects
    # Sanitised, and now carrying the lens that emitted each one.
    assert all(
        set(d) == {"id", "category", "severity", "location", "fix", "grounding_status", "lens"}
        for d in result.verification.defects
    )


def test_real_pipeline_failing_gate_reaches_unverified(tmp_path: Path) -> None:
    broken_test = "from mod import add\n\n\ndef test_add() -> None:\n    assert add(1, 2) == 99\n"
    turns = [
        tool_turn("write_file", {"path": "mod.py", "content": GOOD_CODE}),
        tool_turn("write_file", {"path": "test_mod.py", "content": broken_test}),
        final_turn("added add()", ["mod.py"]),
    ]

    result, _ = real_run(tmp_path, turns, [CLEAN_CRITIC], Limits(max_repair_rounds=0))

    assert result.status is SessionStatus.UNVERIFIED
    assert result.verification is not None
    failed = [g.gate_name for g in result.verification.automated_gates if not g.passed]
    assert "pytest" in failed


def test_real_pipeline_repair_round_reaches_passed(tmp_path: Path) -> None:
    turns = [
        tool_turn("write_file", {"path": "mod.py", "content": GOOD_CODE}),
        final_turn("first attempt", ["mod.py"]),
        tool_turn("write_file", {"path": "extra.py", "content": "VALUE = 1\n"}),
        final_turn("repaired", ["extra.py"]),
    ]

    result, _ = real_run(tmp_path, turns, [BLOCKING_CRITIC, CLEAN_CRITIC], Limits(max_repair_rounds=2))

    assert result.status is SessionStatus.PASSED
    assert result.repairs_used == 1
    assert (tmp_path / "ws" / "mod.py").exists()
    assert (tmp_path / "ws" / "extra.py").exists()


# -- reports -----------------------------------------------------------------


def test_the_report_separates_agent_completion_from_verification(tmp_path: Path) -> None:
    verifier = FakeVerifier([("UNVERIFIED", {"defects": [defect()], "verdict": "FAIL"}, gates())])
    result, _ = run(tmp_path, WRITE_AND_FINISH, verifier=verifier, limits=Limits(max_repair_rounds=0))

    report = build_report(result)

    # The agent finished; AgentGate did not accept the work. Two claims.
    assert report.agent_status == "COMPLETED_UNVERIFIED"
    assert report.status == "UNVERIFIED"
    assert not report.passed


def test_a_passing_report_says_so_on_both_axes(tmp_path: Path) -> None:
    verifier = FakeVerifier([("OK", {"defects": [], "verdict": "OK"}, gates())])
    result, _ = run(tmp_path, WRITE_AND_FINISH, verifier=verifier)

    report = build_report(result)

    assert report.agent_status == "COMPLETED_UNVERIFIED"
    assert report.status == "PASSED"
    assert report.passed
    assert report.verification_ran


def test_the_report_carries_every_required_field(tmp_path: Path) -> None:
    verifier = FakeVerifier([("UNVERIFIED", {"defects": [defect()], "verdict": "FAIL"}, gates(False))])
    result, _ = run(tmp_path, WRITE_AND_FINISH, verifier=verifier, limits=Limits(max_repair_rounds=0))

    payload = json.loads(build_report(result).to_json())

    for key in (
        "task_id",
        "user_goal",
        "status",
        "agent_status",
        "stop_reason",
        "files_changed",
        "commands_run",
        "test_results",
        "planning_status",
        "planning_attempts",
        "turns_used",
        "tool_calls",
        "tokens_spent",
        "spend",
        "verification_status",
        "defects",
        "automated_gates",
        "repairs_used",
        "limits",
        "summary",
    ):
        assert key in payload, key
    assert payload["files_changed"] == ["todo.py"]
    assert payload["defects"][0]["severity"] == "HIGH"
    assert payload["automated_gates"][0]["passed"] is False
    assert isinstance(payload["spend"], str)


def test_the_report_uses_the_ledger_not_the_models_claim(tmp_path: Path) -> None:
    verifier = FakeVerifier([("OK", {"defects": [], "verdict": "OK"}, gates())])
    turns = [
        tool_turn("write_file", {"path": "todo.py", "content": "x = 1\n"}),
        final_turn("done", ["invented.py", "also_fake.py"]),
    ]

    result, _ = run(tmp_path, turns, verifier=verifier)
    report = build_report(result)

    assert report.files_changed == ["todo.py"]
    assert "invented.py" not in report.files_changed


def test_the_report_sums_usage_across_rounds(tmp_path: Path) -> None:
    verifier = FakeVerifier(
        [
            ("UNVERIFIED", {"defects": [defect()], "verdict": "FAIL"}, gates()),
            ("OK", {"defects": [], "verdict": "OK"}, gates()),
        ]
    )
    turns = [*WRITE_AND_FINISH, final_turn("repaired")]

    result, _ = run(tmp_path, turns, verifier=verifier)
    report = build_report(result)

    assert len(report.rounds) == 2
    assert report.turns_used == sum(state.usage.turns_used for state in result.states)
    assert report.repairs_used == 1


def test_the_report_records_a_declined_verification(tmp_path: Path) -> None:
    verifier = FakeVerifier([("OK", {"defects": [], "verdict": "OK"}, gates())])
    result, _ = run(tmp_path, [final_turn("did nothing")], verifier=verifier)

    report = build_report(result)

    assert not report.verification_ran
    assert report.status == "UNVERIFIED"
    assert "nothing to verify" in report.verification_reason


def test_rendering_leads_with_the_verdict(tmp_path: Path) -> None:
    verifier = FakeVerifier([("UNVERIFIED", {"defects": [defect()], "verdict": "FAIL"}, gates())])
    result, _ = run(tmp_path, WRITE_AND_FINISH, verifier=verifier, limits=Limits(max_repair_rounds=0))

    rendered = render_report(build_report(result))

    assert "NOT VERIFIED" in rendered
    assert "COMPLETED_UNVERIFIED" in rendered
    assert "CORRECTNESS/HIGH" in rendered


def test_a_report_never_contains_model_prose_beyond_the_summary(tmp_path: Path) -> None:
    secret = "HIDDEN REASONING FROM THE JUDGE"
    merged = {"defects": [dict(defect(), rationale=secret)], "verdict": "FAIL"}
    verifier = FakeVerifier([("UNVERIFIED", merged, gates())])
    result, _ = run(tmp_path, WRITE_AND_FINISH, verifier=verifier, limits=Limits(max_repair_rounds=0))

    assert secret not in build_report(result).to_json()


# -- observability -----------------------------------------------------------


def test_the_log_records_the_verification_lifecycle(tmp_path: Path) -> None:
    log = SessionLog()
    verifier = FakeVerifier(
        [
            ("UNVERIFIED", {"defects": [defect()], "verdict": "FAIL"}, gates()),
            ("OK", {"defects": [], "verdict": "OK"}, gates()),
        ]
    )
    turns = [*WRITE_AND_FINISH, final_turn("repaired")]

    run(tmp_path, turns, verifier=verifier, log=log)

    kinds = [event.kind for event in log.events]
    assert "verification_start" in kinds
    assert "verification_result" in kinds
    assert "repair_start" in kinds
    assert log.of_kind("run_result")[0].payload["status"] == "PASSED"
    assert log.of_kind("run_result")[0].payload["agent_status"] == "COMPLETED_UNVERIFIED"


def test_a_declined_verification_is_logged(tmp_path: Path) -> None:
    log = SessionLog()
    verifier = FakeVerifier([("OK", {"defects": [], "verdict": "OK"}, gates())])

    run(tmp_path, [final_turn("nothing")], verifier=verifier, log=log)

    assert log.of_kind("verification_declined")
    assert "nothing to verify" in log.of_kind("verification_declined")[0].payload["reason"]


# -- offline guarantee -------------------------------------------------------


@pytest.mark.parametrize("module", [verify_module, report_module])
def test_p4_modules_do_not_reach_a_provider(module: ModuleType) -> None:
    # Located via the imported module, not a repo-root-relative path, so the
    # test resolves whatever the working directory is.
    source = Path(module.__file__ or "").read_text(encoding="utf-8")

    assert "engine.providers" not in source
    assert "import anthropic" not in source
