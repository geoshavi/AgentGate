"""Capability assembly: the seam every agent uses to gain skills.

One function builds one bundle, and an agent's whole integration is to pass that
bundle to its session. Written once here rather than in each agent, so the Debug
Agent (C5) and the Refactoring Agent inherit it instead of motivating a third
copy of the same wiring.

**The ordering is the security property, and it is structural.**
``build_capability_tools`` takes an *already-snapshotted* ``SkillRegistry`` as an
argument, so a tool that can serve skill content cannot exist before the content
was read. ``build_capabilities`` composes snapshot-then-tools in that order and
is the only convenient way to get a bundle. That matters because a skill root may
legitimately sit inside the target workspace -- AgentGate debugging its own
repository -- where the agent can write to the very files the skills come from.
See ``capabilities/skills/registry.py``.

The bundle is deliberately thin. It carries what C2 needs and nothing shaped for
capabilities that do not exist yet: a second capability should extend this by one
field when it is real, not be anticipated by an abstraction now.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from engine.capabilities.skills import (
    SkillBounds,
    SkillLoader,
    SkillRegistry,
    SkillRoot,
)
from engine.codeagent.tools.base import Tool
from engine.codeagent.tools.skills import LoadSkillTool
from engine.codeagent.tools.testenv import DetectTestsTool


@dataclass(frozen=True)
class CapabilityBundle:
    """What one run's capabilities contribute: some tools, and some prompt text.

    ``tools`` holds only the *capability* tools, never the base registry, so a
    caller merges explicitly (``{**TOOL_REGISTRY, **bundle.tools}``). That keeps
    the Debug Agent's bespoke tool dict composable in C5 without this module
    needing to know what a fix session's base set is.

    ``registry`` is kept for reporting -- advertised names, discovery errors,
    root provenance, mutation derivation. It is a snapshot, so holding it grants
    no ability to read anything new.
    """

    tools: dict[str, Tool] = field(default_factory=dict)
    catalogue: str = ""
    registry: SkillRegistry | None = None

    @property
    def enabled(self) -> bool:
        """True when this bundle actually contributes something to a session."""
        return bool(self.tools)

    @property
    def advertised(self) -> tuple[str, ...]:
        return () if self.registry is None else self.registry.names()

    def roots_as_dicts(self) -> list[dict[str, Any]]:
        """Root provenance for the report.

        ``overlaps_workspace`` is the interesting field: it says a skill root sat
        inside a directory the agent could write to, which is permitted and is
        exactly the case the snapshot ordering exists to make safe.
        """
        if self.registry is None:
            return []
        return [
            {
                "path": str(root.path),
                "trust_tier": root.trust_tier,
                "overlaps_workspace": root.overlaps_workspace,
            }
            for root in self.registry.roots
        ]

    def discovery_errors(self) -> list[str]:
        if self.registry is None:
            return []
        return [f"{error.skill}: {error.reason}" for error in self.registry.errors]

    def shadowed_names(self) -> list[str]:
        if self.registry is None:
            return []
        return [entry.name for entry in self.registry.shadowed]


def build_capability_tools(
    registry: SkillRegistry, *, bounds: SkillBounds | None = None
) -> dict[str, Tool]:
    """Model-facing tools for an already-snapshotted registry.

    Takes the registry rather than the roots, deliberately: this signature is
    what makes "the snapshot happened first" impossible to get wrong. A registry
    with no skills yields no tools, so a model in that run never learns
    ``load_skill`` could have existed.
    """
    if not registry.names():
        return {}
    loader = SkillLoader(registry, bounds=bounds or registry.bounds)
    return {"load_skill": LoadSkillTool(loader)}


def build_capabilities(
    *,
    skill_roots: Sequence[SkillRoot] = (),
    bounds: SkillBounds | None = None,
    detect_tests: bool = False,
) -> CapabilityBundle:
    """Snapshot the roots, then build the tools. In that order, always.

    Nothing requested -- the default -- returns an empty bundle, which is what
    keeps a run that configures nothing byte-identical to one from before this
    layer existed: no catalogue in the prompt, no tool in the registry, nothing
    in the report but empty lists.

    ``detect_tests`` is **opt-in rather than automatic**, even though test
    detection needs only the workspace and no configuration at all. Registering
    it by default would add a tool to every run's catalogue, and the catalogue is
    generated into the system prompt -- so every existing session's prompt would
    change. That is exactly the regression C2 took care to make checkable, and
    one explicit parameter is a cheaper way to keep it than a caveat.
    """
    tools: dict[str, Tool] = {}
    catalogue = ""
    registry: SkillRegistry | None = None

    if skill_roots:
        limits = bounds or SkillBounds()
        registry = SkillRegistry.snapshot(skill_roots, bounds=limits)
        tools.update(build_capability_tools(registry, bounds=limits))
        catalogue = registry.advertise()

    if detect_tests:
        tools["detect_tests"] = DetectTestsTool()

    return CapabilityBundle(tools=tools, catalogue=catalogue, registry=registry)


__all__ = ["CapabilityBundle", "build_capabilities", "build_capability_tools"]
