"""Tests for runtime/gateway.py: the sole entry point for LLM calls.
Budget is checked before every call regardless of DB state; metrics are
written after every call (success or failure) but only when a live
connection is given -- no DB handle means no write, not a crash.
"""

from decimal import Decimal
from pathlib import Path

import pytest

from engine.config import Config
from engine.providers.base import GenerationResult, Message
from engine.runtime.budget import BudgetController, BudgetExceededError
from engine.runtime.gateway import LLMGateway
from engine.state import db

MODEL = "claude-sonnet-5"


class _FakeProvider:
    name = "fake"

    def __init__(
        self,
        text: str = "ok",
        raises: Exception | None = None,
        stop_reason: str | None = None,
        thinking_tokens: int = 0,
    ) -> None:
        self._text = text
        self._raises = raises
        self._stop_reason = stop_reason
        self._thinking_tokens = thinking_tokens
        self.calls = 0

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
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return GenerationResult(
            text=self._text,
            model=model,
            provider=self.name,
            input_tokens=5,
            output_tokens=7,
            cache_read_tokens=1,
            cache_creation_tokens=2,
            stop_reason=self._stop_reason,
            thinking_tokens=self._thinking_tokens,
        )


def _budget() -> BudgetController:
    return BudgetController(max_tokens=100_000, planned_budget=Decimal("1.00"))


def test_generate_without_conn_still_calls_the_provider_but_skips_metrics() -> None:
    provider = _FakeProvider()
    gateway = LLMGateway(provider)

    result = gateway.generate(
        budget=_budget(),
        messages=[Message(role="user", content="hi")],
        model=MODEL,
        agent_name="TestAgent",
    )

    assert provider.calls == 1
    assert result.text == "ok"


def test_generate_requires_run_id_and_task_id_when_conn_is_given(tmp_path: Path) -> None:
    gateway = LLMGateway(_FakeProvider())
    with db.connect(tmp_path / "state.db") as conn, pytest.raises(ValueError, match="run_id/task_id"):
        gateway.generate(
            budget=_budget(),
            messages=[Message(role="user", content="hi")],
            model=MODEL,
            agent_name="TestAgent",
            conn=conn,
        )


def test_generate_records_a_metric_row_on_success(tmp_path: Path) -> None:
    gateway = LLMGateway(_FakeProvider())
    db_path = tmp_path / "state.db"

    with db.connect(db_path) as conn:
        run_id = db.create_run(conn, "task", "anthropic", MODEL)
        gateway.generate(
            budget=_budget(),
            messages=[Message(role="user", content="hi")],
            model=MODEL,
            agent_name="CodingAgent",
            conn=conn,
            run_id=run_id,
            task_id="task-1",
        )
        conn.commit()

    with db.connect(db_path) as conn:
        metrics = db.get_agent_execution_metrics(conn, run_id)

    assert len(metrics) == 1
    m = metrics[0]
    assert m.status == "ok"
    assert m.agent_name == "CodingAgent"
    assert m.task_id == "task-1"
    assert m.input_tokens == 5
    assert m.output_tokens == 7
    assert m.cache_read_tokens == 1
    assert m.cache_creation_tokens == 2
    assert m.actual_spend is not None and m.actual_spend > 0
    assert m.error is None


def test_generate_records_an_error_metric_when_the_provider_raises(tmp_path: Path) -> None:
    gateway = LLMGateway(_FakeProvider(raises=RuntimeError("boom")))
    db_path = tmp_path / "state.db"

    with db.connect(db_path) as conn:
        run_id = db.create_run(conn, "task", "anthropic", MODEL)
        with pytest.raises(RuntimeError):
            gateway.generate(
                budget=_budget(),
                messages=[Message(role="user", content="hi")],
                model=MODEL,
                agent_name="CodingAgent",
                conn=conn,
                run_id=run_id,
                task_id="task-1",
            )
        conn.commit()

    with db.connect(db_path) as conn:
        metrics = db.get_agent_execution_metrics(conn, run_id)

    assert len(metrics) == 1
    assert metrics[0].status == "error"
    assert metrics[0].actual_spend is None
    assert metrics[0].error is not None and "boom" in metrics[0].error


def test_generate_checks_budget_before_calling_the_provider() -> None:
    provider = _FakeProvider()
    gateway = LLMGateway(provider)
    tiny_budget = BudgetController(max_tokens=10, planned_budget=Decimal("1.00"))

    with pytest.raises(BudgetExceededError):
        gateway.generate(
            budget=tiny_budget,
            messages=[Message(role="user", content="hi")],
            model=MODEL,
            agent_name="CodingAgent",
            max_tokens=100,
        )

    assert provider.calls == 0  # pre-flight check blocked it before any call


def test_from_config_wraps_the_provider_built_by_the_registry(monkeypatch) -> None:
    sentinel_provider = _FakeProvider()
    monkeypatch.setattr("engine.runtime.gateway.build_provider", lambda name, config: sentinel_provider)

    config = Config(
        anthropic_api_key="key",
        openai_api_key=None,
        google_api_key=None,
        max_retries=3,
        db_path=Path("unused"),
        max_tokens=1,
        timeout_seconds=1.0,
        max_agents=1,
        planned_budget=Decimal(1),
        review_max_tokens=1,
        review_planned_budget=Decimal(1),
    )
    gateway = LLMGateway.from_config("anthropic", config)

    gateway.generate(
        budget=_budget(), messages=[Message(role="user", content="hi")], model=MODEL, agent_name="x"
    )
    assert sentinel_provider.calls == 1


def test_generate_records_stop_reason_and_thinking_token_metadata(tmp_path: Path) -> None:
    """The 9C.1 diagnosis had to infer truncation from output_tokens == max_tokens.
    A truncated call must record that fact directly instead."""
    provider = _FakeProvider(text="partial", stop_reason="max_tokens", thinking_tokens=1400)
    gateway = LLMGateway(provider)
    db_path = tmp_path / "state.db"

    with db.connect(db_path) as conn:
        run_id = db.create_run(conn, "task", "anthropic", MODEL)
        gateway.generate(
            budget=_budget(),
            messages=[Message(role="user", content="hi")],
            model=MODEL,
            agent_name="judge:security",
            conn=conn,
            run_id=run_id,
            task_id="task-1",
        )
        conn.commit()

    with db.connect(db_path) as conn:
        m = db.get_agent_execution_metrics(conn, run_id)[0]

    assert m.stop_reason == "max_tokens"
    assert m.thinking_tokens == 1400
    assert m.text_chars == len("partial")


def test_generate_records_absent_metadata_as_none_and_zero(tmp_path: Path) -> None:
    """A provider that reports no stop_reason must produce NULL, never a
    fabricated value -- 'unknown' and 'end_turn' are different claims."""
    gateway = LLMGateway(_FakeProvider(text="ok"))
    db_path = tmp_path / "state.db"

    with db.connect(db_path) as conn:
        run_id = db.create_run(conn, "task", "anthropic", MODEL)
        gateway.generate(
            budget=_budget(),
            messages=[Message(role="user", content="hi")],
            model=MODEL,
            agent_name="CodingAgent",
            conn=conn,
            run_id=run_id,
            task_id="task-1",
        )
        conn.commit()

    with db.connect(db_path) as conn:
        m = db.get_agent_execution_metrics(conn, run_id)[0]

    assert m.stop_reason is None
    assert m.thinking_tokens == 0
    assert m.text_chars == 2


def test_connect_backfills_observability_columns_on_a_preexisting_database(tmp_path: Path) -> None:
    """SCHEMA uses CREATE TABLE IF NOT EXISTS, so new columns never reach an
    existing .engine/state.db. Without a migration every future bench run on
    the real database would fail on the INSERT."""
    import sqlite3

    db_path = tmp_path / "state.db"
    legacy = sqlite3.connect(db_path)
    legacy.execute(
        "CREATE TABLE agent_execution_metrics ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL, task_id TEXT NOT NULL, "
        "agent_name TEXT NOT NULL, model TEXT NOT NULL, input_tokens INTEGER NOT NULL, "
        "output_tokens INTEGER NOT NULL, cache_read_tokens INTEGER NOT NULL, "
        "cache_creation_tokens INTEGER NOT NULL, latency_ms INTEGER NOT NULL, "
        "actual_spend TEXT, status TEXT NOT NULL, error TEXT, "
        "created_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    legacy.commit()
    legacy.close()

    gateway = LLMGateway(_FakeProvider(text="x", stop_reason="end_turn", thinking_tokens=3))
    with db.connect(db_path) as conn:
        run_id = db.create_run(conn, "task", "anthropic", MODEL)
        gateway.generate(
            budget=_budget(),
            messages=[Message(role="user", content="hi")],
            model=MODEL,
            agent_name="judge:correctness",
            conn=conn,
            run_id=run_id,
            task_id="task-1",
        )
        conn.commit()

    with db.connect(db_path) as conn:
        m = db.get_agent_execution_metrics(conn, run_id)[0]

    assert m.stop_reason == "end_turn"
    assert m.thinking_tokens == 3
