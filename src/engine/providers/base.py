"""The provider-implementation contract.

``Message`` and ``GenerationResult`` are re-exported here, not defined here:
they are the Gateway's public argument/return types and live in
``engine.llm_types`` so callers of ``LLMGateway.generate()`` don't have to
import the provider package to use the Gateway (see that module's docstring,
and Rule B in tests/test_architecture.py). The re-export keeps the existing
``from engine.providers.base import GenerationResult, Message`` spelling
working for the provider implementations in this package, which legitimately
need these types to satisfy ``Provider``.
"""

from typing import Protocol

from engine.llm_types import GenerationResult, Message

__all__ = ["GenerationResult", "Message", "Provider"]


class Provider(Protocol):
    name: str

    def generate(
        self,
        messages: list[Message],
        model: str,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        timeout_seconds: float | None = None,
    ) -> GenerationResult: ...
