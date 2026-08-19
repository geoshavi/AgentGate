from engine.providers.base import GenerationResult, Message


class GoogleProvider:
    name = "google"

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
    ) -> GenerationResult:
        raise NotImplementedError("GoogleProvider is a placeholder for M2 (multi-provider routing).")
