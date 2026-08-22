"""Shared offline test support for the Coding Agent suites.

Not named ``test_*``, so pytest does not collect it. Importable as
``from codeagent_harness import ...`` from any working directory: with the
default ``prepend`` import mode and no ``__init__.py`` in ``tests/``, pytest
inserts each test file's own directory at the front of ``sys.path``, which
makes a sibling module resolvable without the repo root being the cwd. That is
the property the P2 and P3 copies of this code did not have -- they were
imported as ``tests.test_codeagent_session``, which only resolved when pytest
happened to be run from the repo root.

Pure test infrastructure: nothing under ``src/`` imports this, and nothing here
reaches a network, a provider SDK, or an API key.
"""

import json

from engine.llm_types import GenerationResult, Message

# Must exist in runtime/budget.py's PRICE_TABLE, or the budget controller
# raises UnknownModelPricingError before any call is made.
MODEL = "claude-sonnet-5"


class ScriptedProvider:
    """Offline stand-in for a real provider.

    Returns scripted turns in order, repeating the last one once the script is
    exhausted, and records what it was handed so a test can assert on what the
    loop actually fed back.
    """

    name = "scripted"

    def __init__(self, responses: list[str], *, raise_on_call: int | None = None) -> None:
        self._responses = responses
        self._raise_on_call = raise_on_call
        self.calls = 0
        self.seen_messages: list[list[Message]] = []
        self.seen_systems: list[str | None] = []

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
        self.seen_messages.append(list(messages))
        self.seen_systems.append(system)
        if self._raise_on_call == self.calls:
            raise RuntimeError("provider exploded")
        index = min(self.calls - 1, len(self._responses) - 1)
        return GenerationResult(
            text=self._responses[index],
            model=model,
            provider=self.name,
            input_tokens=10,
            output_tokens=20,
            stop_reason="end_turn",
        )


class StepClock:
    """Monotonic fake clock advancing a fixed step per read, so a wall-clock
    bound can be tested without sleeping."""

    def __init__(self, step: float = 1.0) -> None:
        self.now = 0.0
        self.step = step

    def __call__(self) -> float:
        self.now += self.step
        return self.now


def tool_turn(name: str, args: dict | None = None) -> str:
    return f'```tool\n{json.dumps({"name": name, "args": args or {}})}\n```'


def final_turn(summary: str = "done", files: list[str] | None = None) -> str:
    return f'```final\n{json.dumps({"summary": summary, "files_changed": files or []})}\n```'


def plan_block(**payload: object) -> str:
    return f"```plan\n{json.dumps(payload)}\n```"
