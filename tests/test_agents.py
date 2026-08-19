from decimal import Decimal
from pathlib import Path

import pytest

from engine.orchestrator.agents.base import AgentContext
from engine.orchestrator.agents.coding import CodingAgent
from engine.orchestrator.agents.refactoring import RefactoringAgent
from engine.orchestrator.agents.registry import AGENT_REGISTRY, get_agent
from engine.orchestrator.agents.research import ResearchAgent
from engine.orchestrator.agents.testing import TestingAgent
from engine.providers.base import GenerationResult, Message
from engine.runtime.budget import BudgetController
from engine.runtime.gateway import LLMGateway

_AGENT_CLASSES = [CodingAgent, ResearchAgent, TestingAgent, RefactoringAgent]


class _FakeProvider:
    name = "fake"

    def __init__(self, response_text: str) -> None:
        self._response_text = response_text
        self.last_system: str | None = None

    def generate(
        self,
        messages: list[Message],
        model: str,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        timeout_seconds: float | None = None,
    ) -> GenerationResult:
        self.last_system = system
        return GenerationResult(
            text=self._response_text, model=model, provider=self.name, input_tokens=1, output_tokens=1
        )


def _budget() -> BudgetController:
    return BudgetController(max_tokens=100_000, planned_budget=Decimal("1.00"))


def test_registry_contains_all_four_roles() -> None:
    assert set(AGENT_REGISTRY) == {"coding", "research", "testing", "refactoring"}


def test_get_agent_returns_the_registered_instance() -> None:
    assert get_agent("coding") is AGENT_REGISTRY["coding"]
    assert isinstance(get_agent("research"), ResearchAgent)
    assert isinstance(get_agent("testing"), TestingAgent)
    assert isinstance(get_agent("refactoring"), RefactoringAgent)


def test_get_agent_raises_on_unknown_role() -> None:
    with pytest.raises(ValueError, match="unknown-role"):
        get_agent("unknown-role")


def test_each_agent_has_its_own_prompt_file() -> None:
    for agent_cls in _AGENT_CLASSES:
        agent = agent_cls()
        assert agent.prompt_path.exists(), agent_cls.__name__
        assert agent.prompt_path.name == f"{agent.role}.md", agent_cls.__name__


def test_agents_have_distinct_prompts() -> None:
    prompts = {agent_cls: agent_cls().prompt_path.read_text() for agent_cls in _AGENT_CLASSES}
    assert len(set(prompts.values())) == len(prompts)


def test_agent_run_writes_parsed_files_and_uses_its_own_prompt(tmp_path: Path) -> None:
    for agent_cls in _AGENT_CLASSES:
        provider = _FakeProvider("FILE: out.py\n```\nx = 1\n```\n")
        agent = agent_cls()
        workspace = tmp_path / agent.role
        workspace.mkdir()

        output = agent.run(
            AgentContext(
                task_text="do it",
                workspace=workspace,
                gateway=LLMGateway(provider),
                budget=_budget(),
                model="claude-sonnet-5",
                run_id=1,
                task_id="task-1",
            )
        )

        assert output.files == {"out.py": "x = 1\n"}, agent_cls.__name__
        assert output.skipped_paths == [], agent_cls.__name__
        assert (workspace / "out.py").read_text() == "x = 1\n"
        assert provider.last_system == agent.prompt_path.read_text().strip(), agent_cls.__name__


def test_agent_run_refuses_unsafe_paths(tmp_path: Path) -> None:
    for agent_cls in _AGENT_CLASSES:
        provider = _FakeProvider("FILE: ../escape.py\n```\nx = 1\n```\n")
        agent = agent_cls()
        workspace = tmp_path / f"{agent.role}-unsafe"
        workspace.mkdir()

        output = agent.run(
            AgentContext(
                task_text="do it",
                workspace=workspace,
                gateway=LLMGateway(provider),
                budget=_budget(),
                model="claude-sonnet-5",
                run_id=1,
                task_id="task-1",
            )
        )

        assert output.skipped_paths == ["../escape.py"], agent_cls.__name__
        assert not (tmp_path / "escape.py").exists(), agent_cls.__name__
