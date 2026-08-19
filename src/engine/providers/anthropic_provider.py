from anthropic import NOT_GIVEN, Anthropic, omit

from engine.providers.base import GenerationResult, Message

# Sampling parameters were removed from the request surface on these model
# families -- a non-default `temperature` returns a 400. Listing the models
# that reject it, rather than the ones that accept it, keeps the failure loud:
# an unrecognised future model still gets temperature=0.0 and errors visibly,
# instead of silently sampling at the API default of 1.0.
_TEMPERATURE_REJECTED_BY = (
    "claude-opus-5",
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-sonnet-5",
    "claude-fable-5",
    "claude-mythos-5",
)


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str) -> None:
        self._client = Anthropic(api_key=api_key)

    def generate(
        self,
        messages: list[Message],
        model: str,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        timeout_seconds: float | None = None,
    ) -> GenerationResult:
        # The SDK's `timeout` default is a NOT_GIVEN sentinel, not None --
        # explicitly passing timeout=None disables the timeout entirely
        # rather than falling back to the client's default. Only pass a real
        # value through when the caller actually asked for one.
        response = self._client.messages.create(
            model=model,
            system=system or "",
            messages=[{"role": m.role, "content": m.content} for m in messages],
            max_tokens=max_tokens,
            temperature=omit if model.startswith(_TEMPERATURE_REJECTED_BY) else temperature,
            timeout=timeout_seconds if timeout_seconds is not None else NOT_GIVEN,
        )
        text = "".join(block.text for block in response.content if block.type == "text")
        # Thinking blocks are output tokens that never appear in `text` above,
        # so `output_tokens` alone cannot say whether a response was spent on
        # reasoning or on the answer. usage.output_tokens_details carries the
        # split when the model produced any; it is absent otherwise.
        details = response.usage.output_tokens_details
        return GenerationResult(
            text=text,
            model=model,
            provider=self.name,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cache_read_tokens=response.usage.cache_read_input_tokens or 0,
            cache_creation_tokens=response.usage.cache_creation_input_tokens or 0,
            stop_reason=response.stop_reason,
            thinking_tokens=details.thinking_tokens if details is not None else 0,
            raw=response,
        )
