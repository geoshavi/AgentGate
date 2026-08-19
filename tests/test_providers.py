from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from engine.config import Config
from engine.providers.base import Message
from engine.providers.registry import build_provider


def _fake_anthropic_response(
    text: str, stop_reason: str | None = "end_turn", thinking_tokens: int | None = 4
) -> SimpleNamespace:
    """Mirrors the SDK's Message shape, including usage.output_tokens_details --
    which is None on a response the model produced no thinking for."""
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason=stop_reason,
        usage=SimpleNamespace(
            input_tokens=10,
            output_tokens=5,
            cache_read_input_tokens=2,
            cache_creation_input_tokens=3,
            output_tokens_details=(
                None if thinking_tokens is None else SimpleNamespace(thinking_tokens=thinking_tokens)
            ),
        ),
    )


def _config(**overrides) -> Config:
    defaults = {
        "anthropic_api_key": None,
        "openai_api_key": None,
        "google_api_key": None,
        "max_retries": 3,
        "db_path": Path("unused"),
        "max_tokens": 100_000,
        "timeout_seconds": 600.0,
        "max_agents": 10,
        "planned_budget": Decimal("1.00"),
        "review_max_tokens": 10_000,
        "review_planned_budget": Decimal("0.10"),
    }
    defaults.update(overrides)
    return Config(**defaults)


def test_anthropic_provider_generate_parses_response() -> None:
    with patch("engine.providers.anthropic_provider.Anthropic") as MockAnthropic:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _fake_anthropic_response("hello world")
        MockAnthropic.return_value = mock_client

        from engine.providers.anthropic_provider import AnthropicProvider

        provider = AnthropicProvider(api_key="fake-key")
        result = provider.generate(
            messages=[Message(role="user", content="hi")], model="claude-sonnet-5"
        )

        assert result.text == "hello world"
        assert result.provider == "anthropic"
        assert result.input_tokens == 10
        assert result.output_tokens == 5
        assert result.cache_read_tokens == 2
        assert result.cache_creation_tokens == 3
        assert result.stop_reason == "end_turn"
        assert result.thinking_tokens == 4


def test_anthropic_provider_reports_truncation_and_reasoning_spend() -> None:
    """The Phase 9C truncations were only inferable from output_tokens hitting
    the cap. stop_reason must carry that directly, and thinking_tokens must
    account for output the visible text never shows."""
    with patch("engine.providers.anthropic_provider.Anthropic") as MockAnthropic:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _fake_anthropic_response(
            "", stop_reason="max_tokens", thinking_tokens=1600
        )
        MockAnthropic.return_value = mock_client

        from engine.providers.anthropic_provider import AnthropicProvider

        result = AnthropicProvider(api_key="fake-key").generate(
            messages=[Message(role="user", content="hi")], model="claude-sonnet-5"
        )

        assert result.text == ""
        assert result.stop_reason == "max_tokens"
        assert result.thinking_tokens == 1600


def test_anthropic_provider_handles_a_response_with_no_thinking_details() -> None:
    """usage.output_tokens_details is absent when the model produced no
    thinking at all -- that must read as zero, not crash."""
    with patch("engine.providers.anthropic_provider.Anthropic") as MockAnthropic:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _fake_anthropic_response(
            "hi", thinking_tokens=None
        )
        MockAnthropic.return_value = mock_client

        from engine.providers.anthropic_provider import AnthropicProvider

        result = AnthropicProvider(api_key="fake-key").generate(
            messages=[Message(role="user", content="hi")], model="claude-sonnet-5"
        )

        assert result.thinking_tokens == 0


def test_anthropic_provider_sends_output_config_only_when_effort_is_requested() -> None:
    """omit, not a None/default value: sending output_config unconditionally
    would change every non-judge call's request shape too."""
    from anthropic import omit

    with patch("engine.providers.anthropic_provider.Anthropic") as MockAnthropic:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _fake_anthropic_response("hi")
        MockAnthropic.return_value = mock_client

        from engine.providers.anthropic_provider import AnthropicProvider

        provider = AnthropicProvider(api_key="fake-key")
        provider.generate(messages=[Message(role="user", content="hi")], model="claude-sonnet-5")
        assert mock_client.messages.create.call_args.kwargs["output_config"] is omit

        provider.generate(
            messages=[Message(role="user", content="hi")],
            model="claude-sonnet-5",
            effort="medium",
        )
        assert mock_client.messages.create.call_args.kwargs["output_config"] == {"effort": "medium"}


def test_build_provider_missing_key_raises() -> None:
    config = _config(anthropic_api_key=None)
    with pytest.raises(ValueError):
        build_provider("anthropic", config)


def test_build_provider_unknown_name_raises() -> None:
    config = _config(anthropic_api_key="key")
    with pytest.raises(ValueError):
        build_provider("does-not-exist", config)
