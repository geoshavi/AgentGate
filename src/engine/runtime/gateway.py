"""The sole entry point for LLM calls. Wraps the existing Provider
abstraction (never bypasses it) and enforces budget + timeout + metrics
recording around every call.

Timeout enforcement relies entirely on the underlying Provider forwarding
``timeout_seconds`` to its SDK's native HTTP-level timeout (confirmed
supported by the installed Anthropic SDK, which actually aborts the
in-flight request). There is deliberately no ThreadPoolExecutor-based
backstop here: Python cannot forcibly kill a running thread, so a "wait up
to N seconds then give up" wrapper would abandon -- not cancel -- a runaway
call. In a long-lived process (engine-api) that leaks a thread per timeout,
which is a worse failure mode than trusting the SDK's own timeout. If a
future Provider implementation doesn't honor ``timeout_seconds`` natively,
that provider needs its own enforcement -- not something to paper over here.
"""

import sqlite3
import time
from decimal import Decimal

from engine.config import Config
from engine.llm_types import GenerationResult, Message
from engine.providers.base import Provider
from engine.providers.registry import build_provider
from engine.runtime.budget import BudgetController
from engine.state import db
from engine.state.models import AgentExecutionMetric


class LLMGateway:
    """Long-lived: constructed once (per CLI invocation, or once at
    engine-api startup) and reused across many calls. Budget is
    deliberately NOT constructor state -- it's scoped per run (CLI) or per
    request (api.py), passed into each ``generate()`` call, so one gateway
    can serve many runs/requests each with their own independent budget
    instead of one shared lifetime total.
    """

    def __init__(self, provider: Provider) -> None:
        self._provider = provider

    @classmethod
    def from_config(cls, provider_name: str, config: Config) -> "LLMGateway":
        """The only place outside providers/ itself allowed to construct a
        concrete Provider. Callers (cli.py, api.py) go through this, never
        through providers.registry.build_provider directly -- enforced by
        tests/test_architecture.py.
        """
        provider = build_provider(provider_name, config)
        return cls(provider)

    def generate(
        self,
        *,
        budget: BudgetController,
        messages: list[Message],
        model: str,
        agent_name: str,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        timeout_seconds: float | None = None,
        conn: sqlite3.Connection | None = None,
        run_id: int | None = None,
        task_id: str | None = None,
    ) -> GenerationResult:
        if conn is not None and (run_id is None or task_id is None):
            raise ValueError("conn was provided but run_id/task_id were not -- metrics would be unattributable")

        budget.check_before_call(model, max_tokens)

        start = time.monotonic()
        try:
            result = self._provider.generate(
                messages=messages,
                model=model,
                system=system,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:
            self._record_metric(
                conn,
                run_id,
                task_id,
                agent_name,
                model,
                result=None,
                latency_ms=_elapsed_ms(start),
                status="error",
                error=f"{type(exc).__name__}: {exc}",
                spend=None,
            )
            raise

        spend = budget.record_usage(
            model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cache_read_tokens=result.cache_read_tokens,
            cache_creation_tokens=result.cache_creation_tokens,
        )
        self._record_metric(
            conn,
            run_id,
            task_id,
            agent_name,
            model,
            result=result,
            latency_ms=_elapsed_ms(start),
            status="ok",
            error=None,
            spend=spend,
        )
        return result

    def _record_metric(
        self,
        conn: sqlite3.Connection | None,
        run_id: int | None,
        task_id: str | None,
        agent_name: str,
        model: str,
        *,
        result: GenerationResult | None,
        latency_ms: int,
        status: str,
        error: str | None,
        spend: Decimal | None,
    ) -> None:
        if conn is None:
            # No DB handle -> no write. Budget enforcement and the call
            # itself still happened above; only observability is skipped.
            return
        assert run_id is not None and task_id is not None  # guarded in generate()
        metric = AgentExecutionMetric(
            run_id=run_id,
            task_id=task_id,
            agent_name=agent_name,
            model=model,
            input_tokens=result.input_tokens if result else 0,
            output_tokens=result.output_tokens if result else 0,
            cache_read_tokens=result.cache_read_tokens if result else 0,
            cache_creation_tokens=result.cache_creation_tokens if result else 0,
            latency_ms=latency_ms,
            actual_spend=spend,
            status=status,
            error=error,
            stop_reason=result.stop_reason if result else None,
            thinking_tokens=result.thinking_tokens if result else 0,
            text_chars=len(result.text) if result else 0,
        )
        db.record_agent_execution_metric(conn, metric)


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
