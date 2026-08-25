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
from engine.verification.judge import LENSES

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


def critic(defects: list[dict] | None = None) -> str:
    """A judge lens response. ``verdict`` is derived so it is always
    self-consistent with the severities, which the real schema enforces."""
    found = defects or []
    blocking = any(d.get("severity") in ("CRITICAL", "HIGH") for d in found)
    return json.dumps({"defects": found, "verdict": "FAIL" if blocking else "OK"})


CLEAN_CRITIC = critic()


def rootcause_block(**payload: object) -> str:
    return f"```rootcause\n{json.dumps(payload)}\n```"


# The two Debug Agent system prompts, identified by their opening sentence.
# Routing on the prompt rather than on call order is what lets a scenario
# script the phases independently: a run that never reaches the fix phase
# simply never draws from that stream.
DIAGNOSIS_MARKER = "You are diagnosing a reproduced software failure"
FIX_MARKER = "You are a debugging agent"

# Judge lens system prompt -> lens name, so a scenario can script one lens
# differently from its neighbours in the same round. Inverted from LENSES
# rather than restated, so a prompt edit cannot silently desynchronise the two.
LENS_NAME_BY_PROMPT: dict[str, str] = {prompt: name for name, prompt in LENSES.items()}


class DebugScenarioProvider:
    """One offline provider for a whole `engine debug` run.

    The same idea as ``ScenarioProvider`` -- route by system prompt into
    independent scripted streams -- for the Debug Agent's three model-calling
    phases: diagnosis, the fixing session, and the judge lenses. Extended rather
    than forked so both agents share one fake; the Coding Agent's planner stream
    has no counterpart here because the Debug Agent does not plan.

    Judge responses are per verification round, and the round advances every
    len(lens_prompts) calls. A round is either a single string -- every lens of
    that round gets the same answer -- or a {lens name: response} mapping, which
    is what lets a scenario reproduce the case where the three lenses disagree.
    """

    name = "debug-scenario"

    def __init__(
        self,
        *,
        diagnosis_turns: list[str],
        fix_turns: list[str],
        judge_rounds: list[str | dict[str, str]] | None = None,
        lens_prompts: tuple[str, ...] = (),
        raise_on_judge: bool = False,
    ) -> None:
        self._diagnosis_turns = diagnosis_turns
        self._fix_turns = fix_turns
        self._judge_rounds = judge_rounds or [CLEAN_CRITIC]
        self._lens_prompts = set(lens_prompts)
        self._raise_on_judge = raise_on_judge
        self.diagnosis_calls = 0
        self.fix_calls = 0
        self.judge_calls = 0
        self.seen_systems: list[str | None] = []
        self.seen_messages: list[list[Message]] = []

    @property
    def model_calls(self) -> int:
        return self.diagnosis_calls + self.fix_calls + self.judge_calls

    def generate(
        self,
        messages: list[Message],
        model: str,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        timeout_seconds: float | None = None,
    ) -> GenerationResult:
        self.seen_systems.append(system)
        self.seen_messages.append(list(messages))

        if system in self._lens_prompts:
            self.judge_calls += 1
            if self._raise_on_judge:
                raise RuntimeError("judge exploded")
            lenses = max(1, len(self._lens_prompts))
            index = min((self.judge_calls - 1) // lenses, len(self._judge_rounds) - 1)
            scripted = self._judge_rounds[index]
            text = scripted if isinstance(scripted, str) else scripted[LENS_NAME_BY_PROMPT[system]]
        elif system is not None and DIAGNOSIS_MARKER in system:
            index = min(self.diagnosis_calls, len(self._diagnosis_turns) - 1)
            self.diagnosis_calls += 1
            text = self._diagnosis_turns[index]
        elif system is not None and FIX_MARKER in system:
            index = min(self.fix_calls, len(self._fix_turns) - 1)
            self.fix_calls += 1
            text = self._fix_turns[index]
        else:  # pragma: no cover - an unrouted prompt is a test bug, not a path
            raise AssertionError(f"unroutable system prompt: {system!r}")

        return GenerationResult(
            text=text,
            model=model,
            provider=self.name,
            input_tokens=10,
            output_tokens=20,
            stop_reason="end_turn",
        )


class ScenarioProvider:
    """One offline provider for a whole end-to-end run.

    Routes by system prompt into three scripted streams -- planner, agent
    turns, judge lenses -- so a single fake can drive plan -> session ->
    verification -> repair without a network or an API key. Judge responses
    are per verification round: all three lenses of a round get the same
    answer, and the round advances every len(LENSES) calls.
    """

    name = "scenario"

    def __init__(
        self,
        *,
        agent_turns: list[str],
        plan_turns: list[str] | None = None,
        judge_rounds: list[str] | None = None,
        lens_prompts: tuple[str, ...] = (),
    ) -> None:
        self._agent_turns = agent_turns
        self._plan_turns = plan_turns or []
        self._judge_rounds = judge_rounds or [CLEAN_CRITIC]
        self._lens_prompts = set(lens_prompts)
        self.plan_calls = 0
        self.agent_calls = 0
        self.judge_calls = 0
        self.seen_systems: list[str | None] = []
        self.seen_messages: list[list[Message]] = []

    def generate(
        self,
        messages: list[Message],
        model: str,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        timeout_seconds: float | None = None,
    ) -> GenerationResult:
        self.seen_systems.append(system)
        self.seen_messages.append(list(messages))

        if system in self._lens_prompts:
            lenses = max(1, len(self._lens_prompts))
            index = min(self.judge_calls // lenses, len(self._judge_rounds) - 1)
            self.judge_calls += 1
            text = self._judge_rounds[index]
        elif system is not None and "You are planning a coding task" in system:
            index = min(self.plan_calls, len(self._plan_turns) - 1) if self._plan_turns else -1
            self.plan_calls += 1
            text = self._plan_turns[index] if self._plan_turns else "no plan block"
        else:
            index = min(self.agent_calls, len(self._agent_turns) - 1)
            self.agent_calls += 1
            text = self._agent_turns[index]

        return GenerationResult(
            text=text,
            model=model,
            provider=self.name,
            input_tokens=10,
            output_tokens=20,
            stop_reason="end_turn",
        )
