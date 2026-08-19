from engine.providers.base import Effort, GenerationResult, Message


class OpenAIProvider:
    name = "openai"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def generate(
        self,
        messages: list[Message],
        model: str,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        timeout_seconds: float | None = None,
        effort: Effort | None = None,
    ) -> GenerationResult:
        raise NotImplementedError("OpenAIProvider is a placeholder for M2 (multi-provider routing).")
