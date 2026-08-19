"""Tests for orchestrator/manager.py's two failure modes that are terminal
for the whole run -- not retried, unlike a provider hiccup -- because
retrying can't fix either one: the budget doesn't replenish and the clock
doesn't reset.
"""

from decimal import Decimal
from pathlib import Path

from engine.config import DEFAULT_MODELS, Config
from engine.orchestrator.execution_plan import build_execution_plan
from engine.orchestrator.manager import OrchestratorManager
from engine.orchestrator.task_analyzer import classify_task
from engine.providers.base import GenerationResult, Message
from engine.runtime.gateway import LLMGateway


class _FakeProvider:
    name = "fake"

    def __init__(self) -> None:
        self.calls = 0

    def generate(
        self,
        messages: list[Message],
        model: str,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        timeout_seconds: float | None = None,
    ) -> GenerationResult:
        self.calls += 1
        return GenerationResult(
            text="FILE: out.py\n```\nx = 1\n```\n",
            model=model,
            provider=self.name,
            input_tokens=1,
            output_tokens=1,
        )


def _config(tmp_path: Path, **overrides) -> Config:
    defaults = {
        "anthropic_api_key": "fake",
        "openai_api_key": None,
        "google_api_key": None,
        "max_retries": 3,
        "db_path": tmp_path / "state.db",
        "max_tokens": 100_000,
        "timeout_seconds": 600.0,
        "max_agents": 10,
        "planned_budget": Decimal("1.00"),
        "review_max_tokens": 10_000,
        "review_planned_budget": Decimal("0.10"),
    }
    defaults.update(overrides)
    return Config(**defaults)


def test_execute_stops_immediately_on_budget_exhaustion_without_retrying(tmp_path: Path) -> None:
    provider = _FakeProvider()
    # So small that even one call's worst-case output cost blows it.
    config = _config(tmp_path, planned_budget=Decimal("0.00000001"))
    plan = build_execution_plan(classify_task("do the thing"), config)
    manager = OrchestratorManager(LLMGateway(provider), DEFAULT_MODELS["anthropic"])

    result = manager.execute(plan, tmp_path / "workspace", config, "anthropic")

    assert result.passed is False
    assert result.attempts == 1  # terminal -- not retried up to max_retries
    defects = result.verification_history[0].merged_critic["defects"]
    assert defects[0]["id"] == "BUDGET0"
    assert provider.calls == 0  # pre-flight check blocked it before any call


def test_execute_stops_immediately_when_run_deadline_already_passed(tmp_path: Path) -> None:
    provider = _FakeProvider()
    # 1 microsecond: reliably already elapsed by the time the step loop
    # checks it, since _reset_workspace's filesystem I/O alone takes longer.
    config = _config(tmp_path, timeout_seconds=0.000001)
    plan = build_execution_plan(classify_task("do the thing"), config)
    manager = OrchestratorManager(LLMGateway(provider), DEFAULT_MODELS["anthropic"])

    result = manager.execute(plan, tmp_path / "workspace", config, "anthropic")

    assert result.passed is False
    assert result.attempts == 1  # terminal -- not retried up to max_retries
    defects = result.verification_history[0].merged_critic["defects"]
    assert defects[0]["id"] == "DEADLINE0"
    assert provider.calls == 0
