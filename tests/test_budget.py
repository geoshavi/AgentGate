"""Tests for runtime/budget.py: Decimal-only arithmetic, fail-closed
pricing, and the pre-flight (before the call) / accumulation (after)
split. Includes the SQLite round-trip test confirming actual_spend survives
storage as TEXT without losing precision.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from engine.runtime.budget import (
    PRICE_TABLE,
    BudgetController,
    BudgetExceededError,
    UnknownModelPricingError,
    estimate_cost,
    round_for_display,
)
from engine.state import db
from engine.state.models import AgentExecutionMetric

MODEL = "claude-sonnet-5"


def test_estimate_cost_is_derived_from_the_price_table() -> None:
    cost = estimate_cost(MODEL, input_tokens=1000, output_tokens=1000)
    prices = PRICE_TABLE[MODEL]
    assert cost == Decimal(1000) * prices["input"] + Decimal(1000) * prices["output"]


def test_estimate_cost_raises_for_unknown_model() -> None:
    with pytest.raises(UnknownModelPricingError):
        estimate_cost("not-a-real-model", output_tokens=100)


def test_price_table_not_stale() -> None:
    # Reverified 2026-09-01 against platform.claude.com/docs/en/about-claude/pricing:
    # Sonnet 5's scheduled 2026-09-01 increase to $3/$15 was cancelled, $2/$10
    # is now the permanent rate, and Haiku 4.5 rates are unchanged -- PRICE_TABLE
    # needed no edits. No further scheduled change is known, so this is now a
    # periodic recheck rather than a trigger tied to a specific date; push the
    # cutoff out three months and re-verify against the pricing page then.
    # UTC, not date.today() -- ruff (DTZ011) flags date.today() because it's
    # implicit-local-timezone, which could flip this test's verdict a day
    # early or late depending on the machine running it.
    today = datetime.now(tz=UTC).date()
    assert today < date(2026, 12, 1), (
        "PRICE_TABLE may be stale — verify Sonnet 5 and Haiku 4.5 rates at "
        "platform.claude.com/docs/en/about-claude/pricing"
    )


def test_round_for_display_uses_round_half_up() -> None:
    assert round_for_display(Decimal("0.0000005")) == Decimal("0.000001")
    assert round_for_display(Decimal("0.0000004")) == Decimal("0.000000")


def test_check_before_call_raises_when_token_budget_would_be_exceeded() -> None:
    budget = BudgetController(max_tokens=100, planned_budget=Decimal(100))
    with pytest.raises(BudgetExceededError, match="token budget"):
        budget.check_before_call(MODEL, max_tokens=101)


def test_check_before_call_raises_when_spend_budget_would_be_exceeded() -> None:
    budget = BudgetController(max_tokens=1_000_000, planned_budget=Decimal("0.00000001"))
    with pytest.raises(BudgetExceededError, match="spend budget"):
        budget.check_before_call(MODEL, max_tokens=100)


def test_check_before_call_passes_when_within_both_budgets() -> None:
    budget = BudgetController(max_tokens=100_000, planned_budget=Decimal("1.00"))
    budget.check_before_call(MODEL, max_tokens=1000)  # must not raise


def test_record_usage_accumulates_at_full_precision_without_rounding() -> None:
    budget = BudgetController(max_tokens=1_000_000, planned_budget=Decimal(1000))
    spend1 = budget.record_usage(MODEL, input_tokens=1, output_tokens=1)
    spend2 = budget.record_usage(MODEL, input_tokens=1, output_tokens=1)

    assert budget.spent_tokens == 4
    assert budget.spent_amount == spend1 + spend2
    # Full precision, not quantized to a display rounding -- accumulation
    # never calls round_for_display.
    assert budget.spent_amount == estimate_cost(MODEL, input_tokens=2, output_tokens=2)


def test_decimal_round_trips_through_sqlite_at_full_precision(tmp_path: Path) -> None:
    exact = Decimal("0.000123456789")
    db_path = tmp_path / "state.db"

    with db.connect(db_path) as conn:
        run_id = db.create_run(conn, "task", "anthropic", MODEL)
        db.record_agent_execution_metric(
            conn,
            AgentExecutionMetric(
                run_id=run_id,
                task_id="task-1",
                agent_name="CodingAgent",
                model=MODEL,
                input_tokens=10,
                output_tokens=20,
                cache_read_tokens=0,
                cache_creation_tokens=0,
                latency_ms=42,
                actual_spend=exact,
                status="ok",
                error=None,
            ),
        )
        conn.commit()

    with db.connect(db_path) as conn:
        metrics = db.get_agent_execution_metrics(conn, run_id)

    assert len(metrics) == 1
    assert metrics[0].actual_spend == exact
    assert str(metrics[0].actual_spend) == str(exact)


def test_decimal_round_trips_as_none_for_error_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"

    with db.connect(db_path) as conn:
        run_id = db.create_run(conn, "task", "anthropic", MODEL)
        db.record_agent_execution_metric(
            conn,
            AgentExecutionMetric(
                run_id=run_id,
                task_id="task-1",
                agent_name="CodingAgent",
                model=MODEL,
                input_tokens=0,
                output_tokens=0,
                cache_read_tokens=0,
                cache_creation_tokens=0,
                latency_ms=5,
                actual_spend=None,
                status="error",
                error="connection reset",
            ),
        )
        conn.commit()

    with db.connect(db_path) as conn:
        metrics = db.get_agent_execution_metrics(conn, run_id)

    assert metrics[0].actual_spend is None
    assert metrics[0].status == "error"
