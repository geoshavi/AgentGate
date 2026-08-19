from engine.providers.base import GenerationResult, Message


class OllamaProvider:
    name = "ollama"

    def __init__(self, host: str = "http://localhost:11434") -> None:
        self._host = host

    def generate(
        self,
        messages: list[Message],
        model: str,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        timeout_seconds: float | None = None,
    ) -> GenerationResult:
        raise NotImplementedError("OllamaProvider is a placeholder for M2 (multi-provider routing).")
