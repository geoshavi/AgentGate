"""D4: the whole Debug Agent, end to end and offline.

Every test drives the real flow -- the real reproduction subprocess, the real
evidence parser, the real fix tools, the real proof commands, real AgentGate
verification and the real ``verdict.gate`` -- with only the model replaced by a
scripted provider. No API key, no network, no spend.

The rule the suite exists to prove is one sentence: **PASSED requires the proof
gate AND AgentGate, and nothing a model says can substitute for either.** Every
other test is a way of failing exactly one of those two and checking the verdict
falls back honestly.
"""

import json
import shutil
from decimal import Decimal
from pathlib import Path

import pytest
from codeagent_harness import (
    CLEAN_CRITIC,
    MODEL,
    DebugScenarioProvider,
    critic,
    final_turn,
    rootcause_block,
    tool_turn,
)

from engine.codeagent.limits import Limits
from engine.codeagent.state import Phase, SessionStatus
from engine.debugagent.app import (
    DEFAULT_SUITE_ARGV,
    EXIT_ERROR,
    EXIT_UNVERIFIED,
    EXIT_VERIFIED,
    WorkspaceRejected,
    run_debug_task,
)
from engine.debugagent.fix import ProofStatus
from engine.debugagent.limits import DEBUG_LIMITS
from engine.debugagent.report import NOT_REACHED, render_debug_report
from engine.runtime.gateway import LLMGateway
from engine.verification.judge import LENSES

FIXTURES = Path(__file__).resolve().parent.parent / "examples"
LENS_PROMPTS = tuple(LENSES.values())

BUG = (
    "Adding nothing to the cart and asking for a total crashes instead of returning "
    "the shipping charge. Customers hitting the empty basket page see a 500."
)
REPRO = ["python", "-m", "pytest", "-q", "tests/test_cart.py::test_empty_cart_is_shipping_only"]
SUITE = list(DEFAULT_SUITE_ARGV)
# A test in the fixture that already passes -- the reproduction that will not
# reproduce.
PASSING_REPRO = ["python", "-m", "pytest", "-q", "tests/test_cart.py::test_shipping_is_always_added"]

# cart.py:24 is `cheapest = min(item.price for item in items)`.
DIAGNOSIS = rootcause_block(
    summary="the bulk discount computes the cheapest price before checking the cart has contents",
    mechanism=(
        "_discount calls min() over an empty generator when the cart is empty, because the "
        "BULK_UNITS check happens after the minimum is taken"
    ),
    primary_file="cart.py",
    primary_line=24,
    related_files=["tests/test_cart.py"],
    evidence_refs=["the traceback names cart.py:24 in _discount"],
    proposed_fix="take the BULK_UNITS check first, so an empty cart returns before min() runs",
    validation_plan=[SUITE],
)
BAD_DIAGNOSIS = rootcause_block(
    summary="the shipping constant is wrong",
    mechanism="SHIPPING_FLAT is not applied",
    primary_file="billing/shipping.py",  # does not exist
    primary_line=1,
    proposed_fix="fix the constant",
)

# The real fix: reorder the guard so an empty cart never reaches min().
GOOD_FIX = tool_turn(
    "replace_exact",
    {
        "path": "cart.py",
        "find": (
            "    cheapest = min(item.price for item in items)\n"
            "    if sum(item.qty for item in items) < BULK_UNITS:\n"
            "        return 0.0\n"
        ),
        "replace": (
            "    if sum(item.qty for item in items) < BULK_UNITS:\n"
            "        return 0.0\n"
            "    cheapest = min(item.price for item in items)\n"
        ),
    },
)
# Makes the reported bug go green and breaks the bulk-discount test. This is
# exactly the change a targeted-only gate would report as a fix.
BAD_FIX = tool_turn(
    "replace_exact",
    {
        "path": "cart.py",
        "find": (
            "    cheapest = min(item.price for item in items)\n"
            "    if sum(item.qty for item in items) < BULK_UNITS:\n"
            "        return 0.0\n"
            "    return cheapest * BULK_RATE\n"
        ),
        "replace": "    return 0.0\n",
    },
)
# Edits nothing at all, then declares victory.
NO_FIX_TURNS = [final_turn("fixed the bug", ["cart.py"])]

# The repair for BAD_FIX: it has to anchor on what BAD_FIX left behind, which is
# the point -- a repair round continues from the accumulated diff, never from a
# clean tree.
REPAIR_FIX = tool_turn(
    "replace_exact",
    {
        "path": "cart.py",
        "find": "    return 0.0\n\n\ndef cart_total",
        "replace": (
            "    if sum(item.qty for item in items) < BULK_UNITS:\n"
            "        return 0.0\n"
            "    return min(item.price for item in items) * BULK_RATE\n"
            "\n"
            "\n"
            "def cart_total"
        ),
    },
)

SOLVE_TURNS = [GOOD_FIX, final_turn("moved the empty-cart guard ahead of min()", ["cart.py"])]
BREAK_TURNS = [BAD_FIX, final_turn("fixed the bug", ["cart.py"])]


def fixture_copy(tmp_path: Path, name: str = "cart_bug") -> Path:
    workspace = tmp_path / "ws"
    shutil.copytree(
        FIXTURES / name, workspace, ignore=shutil.ignore_patterns("__pycache__")
    )
    return workspace


def provider(
    fix_turns: list[str],
    *,
    diagnosis_turns: list[str] | None = None,
    judge_rounds: list[str] | None = None,
    raise_on_judge: bool = False,
) -> DebugScenarioProvider:
    return DebugScenarioProvider(
        diagnosis_turns=diagnosis_turns or [DIAGNOSIS],
        fix_turns=fix_turns,
        judge_rounds=judge_rounds or [CLEAN_CRITIC],
        lens_prompts=LENS_PROMPTS,
        raise_on_judge=raise_on_judge,
    )


def go(
    tmp_path: Path,
    fix_turns: list[str],
    *,
    diagnosis_turns: list[str] | None = None,
    judge_rounds: list[str] | None = None,
    raise_on_judge: bool = False,
    repro: list[str] | None = None,
    suite: list[str] | None = None,
    limits: Limits | None = None,
    workspace: Path | None = None,
    artifacts: Path | None = None,
    budget: str = "10.00",
):  # type: ignore[no-untyped-def]
    fake = provider(
        fix_turns,
        diagnosis_turns=diagnosis_turns,
        judge_rounds=judge_rounds,
        raise_on_judge=raise_on_judge,
    )
    result = run_debug_task(
        task_text=BUG,
        workspace_path=workspace if workspace is not None else fixture_copy(tmp_path),
        repro_argv=repro if repro is not None else REPRO,
        suite_argv=suite if suite is not None else SUITE,
        gateway=LLMGateway(fake),
        model=MODEL,
        judge_model=MODEL,
        limits=limits if limits is not None else DEBUG_LIMITS,
        planned_budget=Decimal(budget),
        task_id="dbg-app",
        artifacts_root=artifacts,
    )
    return result, fake


# -- the happy path ----------------------------------------------------------


def test_a_reproduced_bug_is_diagnosed_fixed_proven_and_verified(tmp_path: Path) -> None:
    workspace = fixture_copy(tmp_path)

    result, fake = go(tmp_path, SOLVE_TURNS, workspace=workspace)

    report = result.report
    assert report.status == SessionStatus.PASSED.value
    assert result.exit_code == EXIT_VERIFIED
    # Both halves of the verdict, asserted separately.
    assert report.observed.proof_status == ProofStatus.PROVEN.value
    assert report.agentgate.status == "OK"
    # And the workspace really is fixed: the count check now precedes min().
    source = workspace.joinpath("cart.py").read_text(encoding="utf-8")
    assert source.index("< BULK_UNITS") < source.index("cheapest = min(")
    assert fake.judge_calls == len(LENSES)


def test_the_proof_ran_both_commands_and_both_passed(tmp_path: Path) -> None:
    result, _ = go(tmp_path, SOLVE_TURNS)

    observed = result.report.observed
    assert observed.repro_before is not None and observed.repro_before["exit_code"] != 0
    assert observed.repro_after is not None and observed.repro_after["exit_code"] == 0
    assert observed.suite_after is not None and observed.suite_after["exit_code"] == 0
    assert observed.suite_after["argv"] == SUITE


# -- gate D/E: the failure will not reproduce --------------------------------


def test_a_bug_that_will_not_reproduce_aborts_before_any_model_call(tmp_path: Path) -> None:
    workspace = fixture_copy(tmp_path)
    original = workspace.joinpath("cart.py").read_text(encoding="utf-8")

    result, fake = go(tmp_path, SOLVE_TURNS, repro=PASSING_REPRO, workspace=workspace)

    assert result.report.status == SessionStatus.ABORTED_NO_REPRO.value
    assert result.exit_code == EXIT_ERROR
    assert result.report.phase_reached == Phase.REPRODUCING.value
    # Zero model calls of any kind, and zero edits.
    assert fake.model_calls == 0
    assert result.report.observed.files_changed == []
    assert workspace.joinpath("cart.py").read_text(encoding="utf-8") == original
    # Nothing later than the gate is claimed to have happened.
    assert result.report.claimed.diagnosis_status == NOT_REACHED
    assert result.report.observed.proof_status == NOT_REACHED
    assert result.report.agentgate.ran is False


# -- gate G/H: no validated root cause ---------------------------------------


def test_a_rejected_diagnosis_aborts_with_zero_edits(tmp_path: Path) -> None:
    workspace = fixture_copy(tmp_path)
    original = workspace.joinpath("cart.py").read_text(encoding="utf-8")

    result, fake = go(
        tmp_path, SOLVE_TURNS, diagnosis_turns=[BAD_DIAGNOSIS], workspace=workspace
    )

    assert result.report.status == SessionStatus.ABORTED_NO_ROOT_CAUSE.value
    assert result.exit_code == EXIT_ERROR
    assert result.report.observed.files_changed == []
    assert workspace.joinpath("cart.py").read_text(encoding="utf-8") == original
    # The fixing session was never constructed, so no fix turn was drawn.
    assert fake.fix_calls == 0
    assert fake.judge_calls == 0
    # Both diagnosis attempts were spent, and the reason is reported.
    assert fake.diagnosis_calls == DEBUG_LIMITS.max_rootcause_attempts
    assert result.report.claimed.diagnosis_errors


def test_a_rejected_diagnosis_keeps_the_reproduction_evidence(tmp_path: Path) -> None:
    """Losing the hypothesis must not lose the observation that earned it."""
    result, _ = go(tmp_path, SOLVE_TURNS, diagnosis_turns=[BAD_DIAGNOSIS])

    assert result.report.observed.reproduced is True
    assert result.report.observed.evidence is not None
    assert result.report.observed.evidence["exception_type"] == "ValueError"


# -- gate J: proven is not something a model can assert ----------------------


def test_a_fix_that_breaks_the_suite_is_not_proven(tmp_path: Path) -> None:
    result, fake = go(
        tmp_path, BREAK_TURNS, limits=Limits(**{**DEBUG_LIMITS.as_dict(), "max_repair_rounds": 0})
    )

    observed = result.report.observed
    assert observed.proof_status == ProofStatus.UNPROVEN.value
    # The reproduction went green; the suite is what caught it.
    assert observed.proof_stage == "SUITE"
    assert observed.repro_after is not None and observed.repro_after["exit_code"] == 0
    assert observed.suite_after is not None and observed.suite_after["exit_code"] != 0
    assert result.report.status == SessionStatus.UNVERIFIED.value
    assert result.exit_code == EXIT_UNVERIFIED
    # AgentGate was never asked: its answer could not have changed the verdict.
    assert fake.judge_calls == 0
    assert result.report.agentgate.ran is False


def test_a_session_that_changes_nothing_is_not_proven(tmp_path: Path) -> None:
    result, _ = go(
        tmp_path, NO_FIX_TURNS, limits=Limits(**{**DEBUG_LIMITS.as_dict(), "max_repair_rounds": 0})
    )

    assert result.report.observed.files_changed == []
    assert result.report.observed.proof_status == ProofStatus.UNPROVEN.value
    assert result.report.status == SessionStatus.UNVERIFIED.value
    assert result.exit_code == EXIT_UNVERIFIED


def test_the_model_declaring_success_cannot_move_the_verdict(tmp_path: Path) -> None:
    """The whole point of the phase, as one assertion."""
    result, _ = go(
        tmp_path, BREAK_TURNS, limits=Limits(**{**DEBUG_LIMITS.as_dict(), "max_repair_rounds": 0})
    )

    # What the model said is reported...
    assert result.report.claimed.fix_summary == "fixed the bug"
    # ...and it is reported as a claim, in the claimed block, while the verdict
    # comes from the commands.
    assert result.report.status != SessionStatus.PASSED.value
    assert result.report.observed.proof_status == ProofStatus.UNPROVEN.value


def test_a_failed_proof_is_repaired_and_the_repair_is_proven(tmp_path: Path) -> None:
    """The bad fix first, the real one after the suite failure is fed back."""
    result, fake = go(
        tmp_path,
        [
            BAD_FIX,
            final_turn("fixed", ["cart.py"]),
            REPAIR_FIX,
            final_turn("moved the guard ahead of the minimum", ["cart.py"]),
        ],
    )

    assert result.report.observed.repair_rounds == 1
    assert result.report.observed.proof_status == ProofStatus.PROVEN.value
    assert result.report.status == SessionStatus.PASSED.value
    # The repair round saw the suite failure, not a critique of it.
    repair_briefs = [
        message.content
        for messages in fake.seen_messages
        for message in messages
        if "FIX NOT PROVEN" in message.content
    ]
    assert repair_briefs and "THE SUITE BROKE" in repair_briefs[0]


# -- gate K/L: AgentGate decides its own half --------------------------------


def test_a_proven_fix_that_agentgate_blocks_is_unverified(tmp_path: Path) -> None:
    blocked = critic(
        [
            {
                "id": "C1",
                "category": "SECURITY",
                "severity": "CRITICAL",
                "location": "cart.py:24",
                "fix": "do not do that",
            }
        ]
    )

    result, fake = go(tmp_path, SOLVE_TURNS, judge_rounds=[blocked])

    # Proven, and still not PASSED.
    assert result.report.observed.proof_status == ProofStatus.PROVEN.value
    assert result.report.agentgate.status == "UNVERIFIED"
    assert result.report.status == SessionStatus.UNVERIFIED.value
    assert result.exit_code == EXIT_UNVERIFIED
    assert fake.judge_calls == len(LENSES)
    # There is no second fixing system: verification is terminal.
    assert fake.fix_calls == len(SOLVE_TURNS)


def test_agentgate_defects_reach_the_report(tmp_path: Path) -> None:
    blocked = critic(
        [
            {
                "id": "C1",
                "category": "CORRECTNESS",
                "severity": "HIGH",
                "location": "cart.py:22",
                "fix": "guard the empty case explicitly",
                "reasoning": "prose the schema never described",
            }
        ]
    )

    result, _ = go(tmp_path, SOLVE_TURNS, judge_rounds=[blocked])

    defects = result.report.agentgate.defects
    assert len(defects) == len(LENSES)  # one per lens, all three agreed
    assert defects[0]["location"] == "cart.py:22"
    # Sanitised on the way through: only the five schema keys survive.
    assert "reasoning" not in defects[0]


# -- fail closed -------------------------------------------------------------


def test_a_verifier_exception_fails_closed(tmp_path: Path) -> None:
    result, _ = go(tmp_path, SOLVE_TURNS, raise_on_judge=True)

    assert result.report.status == SessionStatus.UNVERIFIED.value
    assert result.exit_code == EXIT_UNVERIFIED
    assert result.report.agentgate.ran is False
    assert "verification failed" in result.report.agentgate.reason
    # The proof still stands on its own -- it was measured before AgentGate.
    assert result.report.observed.proof_status == ProofStatus.PROVEN.value


def test_an_oversized_snapshot_fails_closed(tmp_path: Path) -> None:
    tight = Limits(**{**DEBUG_LIMITS.as_dict(), "max_snapshot_bytes": 10})

    result, fake = go(tmp_path, SOLVE_TURNS, limits=tight)

    assert result.report.status == SessionStatus.UNVERIFIED.value
    assert result.report.agentgate.ran is False
    assert "max_snapshot_bytes" in result.report.agentgate.reason
    assert fake.judge_calls == 0


def test_a_budget_too_small_to_verify_fails_closed(tmp_path: Path) -> None:
    """A verifier that cannot afford to run must not be read as approval."""
    result, _ = go(tmp_path, SOLVE_TURNS, budget="0.0002")

    assert result.report.status != SessionStatus.PASSED.value
    assert result.exit_code != EXIT_VERIFIED


# -- refusals before anything is spent ---------------------------------------


def test_a_missing_workspace_is_refused(tmp_path: Path) -> None:
    fake = provider(SOLVE_TURNS)

    with pytest.raises(WorkspaceRejected):
        run_debug_task(
            task_text=BUG,
            workspace_path=tmp_path / "nope",
            repro_argv=REPRO,
            gateway=LLMGateway(fake),
            model=MODEL,
            judge_model=MODEL,
        )

    assert fake.model_calls == 0


def test_the_engines_own_tree_is_refused(tmp_path: Path) -> None:
    marker = tmp_path / "src" / "engine" / "verification"
    marker.mkdir(parents=True)
    (marker / "verdict.py").write_text("# the real one\n", encoding="utf-8")

    with pytest.raises(WorkspaceRejected, match="own source tree"):
        run_debug_task(
            task_text=BUG,
            workspace_path=tmp_path,
            repro_argv=REPRO,
            gateway=LLMGateway(provider(SOLVE_TURNS)),
            model=MODEL,
            judge_model=MODEL,
        )


def test_a_shell_string_reproduction_is_refused(tmp_path: Path) -> None:
    fake = provider(SOLVE_TURNS)

    with pytest.raises(TypeError, match="argv list"):
        run_debug_task(
            task_text=BUG,
            workspace_path=fixture_copy(tmp_path),
            repro_argv="python -m pytest -q",
            gateway=LLMGateway(fake),
            model=MODEL,
            judge_model=MODEL,
        )

    assert fake.model_calls == 0


def test_a_regression_command_the_policy_refuses_is_rejected_before_editing(
    tmp_path: Path,
) -> None:
    workspace = fixture_copy(tmp_path)
    fake = provider(SOLVE_TURNS)

    with pytest.raises(ValueError, match="not allowed"):
        run_debug_task(
            task_text=BUG,
            workspace_path=workspace,
            repro_argv=REPRO,
            suite_argv=["git", "push"],
            gateway=LLMGateway(fake),
            model=MODEL,
            judge_model=MODEL,
        )

    assert fake.model_calls == 0
    assert not (workspace / "cart.py").read_text(encoding="utf-8").startswith("# edited")


def test_an_unpriced_model_aborts_without_editing(tmp_path: Path) -> None:
    """The budget refuses a model it cannot price, and the run ends there."""
    workspace = fixture_copy(tmp_path)
    original = workspace.joinpath("cart.py").read_text(encoding="utf-8")
    fake = provider(SOLVE_TURNS)

    result = run_debug_task(
        task_text=BUG,
        workspace_path=workspace,
        repro_argv=REPRO,
        gateway=LLMGateway(fake),
        model="not-a-real-model",
        judge_model=MODEL,
        task_id="dbg-unpriced",
    )

    assert result.report.status == SessionStatus.ABORTED_NO_ROOT_CAUSE.value
    assert result.exit_code == EXIT_ERROR
    assert result.report.observed.files_changed == []
    assert workspace.joinpath("cart.py").read_text(encoding="utf-8") == original
    assert fake.fix_calls == 0


# -- the report --------------------------------------------------------------


def test_changed_files_come_from_the_ledger_not_the_models_claim(tmp_path: Path) -> None:
    lying = [
        GOOD_FIX,
        final_turn("rewrote the whole billing system", ["cart.py", "billing.py", "invoices.py"]),
    ]

    result, _ = go(tmp_path, lying)

    assert result.report.observed.files_changed == ["cart.py"]
    assert result.report.claimed.fix_summary == "rewrote the whole billing system"


def test_inspected_files_come_from_the_ledger(tmp_path: Path) -> None:
    result, _ = go(tmp_path, SOLVE_TURNS)

    assert "cart.py" in result.report.observed.files_inspected


def test_the_report_separates_observed_claimed_and_agentgate(tmp_path: Path) -> None:
    result, _ = go(tmp_path, SOLVE_TURNS)
    payload = json.loads(result.report.to_json())

    assert set(payload) >= {"observed", "claimed", "agentgate", "usage", "status", "reason"}
    # No model sentence in the observed block.
    assert "summary" not in payload["observed"]
    # No verdict in the claimed block.
    assert "status" not in payload["claimed"]
    assert payload["claimed"]["root_cause"]["primary_file"] == "cart.py"
    assert payload["agentgate"]["status"] == "OK"


def test_the_report_carries_every_required_field(tmp_path: Path) -> None:
    result, _ = go(tmp_path, SOLVE_TURNS)
    payload = json.loads(result.report.to_json())

    assert payload["reported_bug"] == BUG
    assert payload["repro_command"] == REPRO
    assert payload["suite_command"] == SUITE
    assert payload["task_id"] == "dbg-app"
    assert payload["observed"]["evidence"]["exception_type"] == "ValueError"
    assert payload["observed"]["commands_run"]
    assert payload["observed"]["repair_rounds"] == 0
    assert payload["claimed"]["root_cause"]["confidence"] in {
        "OBSERVED",
        "CORROBORATED",
        "INFERRED",
    }
    assert payload["agentgate"]["automated_gates"]
    assert payload["usage"]["agent_model_calls"] >= 2
    assert payload["usage"]["elapsed_ms"] >= 0
    assert payload["usage"]["total_tokens"] > 0
    assert Decimal(payload["usage"]["spend"]) > 0

    # The agent/judge split is named, not left to the reader to infer.
    usage = payload["usage"]
    assert usage["agent_tokens"] == usage["agent_input_tokens"] + usage["agent_output_tokens"]
    assert usage["agent_tokens"] + usage["judge_tokens"] == usage["total_tokens"]
    # Counts that do not exist on this side of the verification seam are absent
    # rather than guessed.
    assert "judge_model_calls" not in usage
    assert "total_model_calls" not in usage


def test_the_report_json_holds_no_prompt_or_reasoning_text(tmp_path: Path) -> None:
    result, _ = go(tmp_path, SOLVE_TURNS)
    text = result.report.to_json()

    assert "You are a debugging agent" not in text
    assert "You are diagnosing" not in text
    assert "```rootcause" not in text


def test_confidence_is_computed_not_accepted(tmp_path: Path) -> None:
    claimed_high = rootcause_block(
        summary="the guard is in the wrong place",
        mechanism="min() runs before the count check",
        primary_file="cart.py",
        primary_line=24,
        proposed_fix="reorder the guard",
        confidence="ABSOLUTELY_CERTAIN",
    )

    result, _ = go(tmp_path, SOLVE_TURNS, diagnosis_turns=[claimed_high])

    assert result.report.claimed.root_cause is not None
    assert result.report.claimed.root_cause["confidence"] in {
        "OBSERVED",
        "CORROBORATED",
        "INFERRED",
    }


def test_the_rendered_report_puts_measurement_before_narration(tmp_path: Path) -> None:
    result, _ = go(tmp_path, SOLVE_TURNS)
    text = render_debug_report(result.report)

    assert text.index("-- observed") < text.index("-- claimed by the model")
    assert text.index("-- AgentGate verification") < text.index("-- claimed by the model")
    assert "PASSED" in text
    assert "cart.py" in text


def test_artifacts_are_written(tmp_path: Path) -> None:
    result, _ = go(tmp_path, SOLVE_TURNS, artifacts=tmp_path / "artifacts")

    assert result.report_path is not None and result.report_path.is_file()
    assert result.log_path is not None and result.log_path.is_file()
    events = [
        json.loads(line)
        for line in result.log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    kinds = {event["kind"] for event in events}
    assert {"repro_result", "rootcause_result", "fix_proof", "debug_result"} <= kinds


def test_the_run_is_recorded_in_the_database(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    fake = provider(SOLVE_TURNS)

    run_debug_task(
        task_text=BUG,
        workspace_path=fixture_copy(tmp_path),
        repro_argv=REPRO,
        gateway=LLMGateway(fake),
        model=MODEL,
        judge_model=MODEL,
        task_id="dbg-db",
        db_path=db_path,
    )

    from engine.state import db

    with db.connect(db_path) as conn:
        runs = conn.execute("SELECT id, status FROM runs").fetchall()
        metrics = conn.execute(
            "SELECT agent_name FROM agent_execution_metrics WHERE run_id = ?", (runs[0][0],)
        ).fetchall()

    assert runs[0][1] == "passed"
    names = {row[0] for row in metrics}
    assert "DebugAgent.rootcause" in names
    assert "DebugAgent.fix" in names
    assert any(name.startswith("judge:") for name in names)


# -- bounds ------------------------------------------------------------------


def test_the_fix_may_not_change_a_fourth_file(tmp_path: Path) -> None:
    """max_files_changed is a mechanism, not a prompt line."""
    spray = [
        tool_turn("replace_exact", {"path": "cart.py", "find": "BULK_RATE = 0.10",
                                    "replace": "BULK_RATE = 0.10  # a"}),
        tool_turn("replace_exact", {"path": "conftest.py", "find": "import sys",
                                    "replace": "import sys  # b"}),
        tool_turn("replace_exact", {"path": "tests/test_cart.py", "find": "from cart import",
                                    "replace": "from cart import "}),
        final_turn("touched everything", []),
    ]
    tight = Limits(**{**DEBUG_LIMITS.as_dict(), "max_files_changed": 2, "max_repair_rounds": 0})

    result, _ = go(tmp_path, spray, limits=tight)

    assert len(result.report.observed.files_changed) <= 2
    assert result.report.status != SessionStatus.PASSED.value
