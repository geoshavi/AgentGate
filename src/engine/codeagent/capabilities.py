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

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from engine.capabilities.external import (
    CONTEXT7_PROVIDER,
    DOCS_LOOKUP,
    GITHUB_LOOKUP,
    GITHUB_PROVIDER,
    DocsPort,
    EgressLedger,
    EgressPolicy,
    GitHubPort,
)
from engine.capabilities.skills import (
    TRUST_BUILTIN,
    SkillBounds,
    SkillLoader,
    SkillRegistry,
    SkillRoot,
    builtin_skill_root,
)
from engine.codeagent.state import TaskState
from engine.codeagent.tools.analysis import AnalyzeCodeTool
from engine.codeagent.tools.base import Tool
from engine.codeagent.tools.docs import LookupDocsTool
from engine.codeagent.tools.github import LookupGitHubTool
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
    # External spend for this run. Held so a report can state what left the
    # machine even when the session that spent it has ended. None when no
    # external capability was admitted -- which is a different statement from
    # "admitted and never used", and the report keeps them apart.
    egress: EgressLedger | None = None

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
    analyze: bool = False,
    include_builtin_skills: bool = False,
    workspace_root: Path | None = None,
    docs: DocsPort | None = None,
    github: GitHubPort | None = None,
    egress_policy: EgressPolicy | None = None,
    docs_capability: str = CONTEXT7_PROVIDER,
    github_capability: str = GITHUB_PROVIDER,
) -> CapabilityBundle:
    """Snapshot the roots, then build the tools. In that order, always.

    Nothing requested -- the default -- returns an empty bundle, which is what
    keeps a run that configures nothing byte-identical to one from before this
    layer existed: no catalogue in the prompt, no tool in the registry, nothing
    in the report but empty lists.

    ``detect_tests``, ``analyze`` and ``include_builtin_skills`` are **opt-in
    rather than automatic**, even though all three are locally available and need
    no configuration. Each one registers a tool, and the tool catalogue is
    generated into the system prompt -- so switching them on by default would
    change every existing session's prompt. That is exactly the regression C2
    took care to make checkable, and two explicit parameters are a cheaper way to
    keep it than a caveat.

    ``include_builtin_skills`` prepends the engine's own ``skills/`` directory,
    **first** in root order, so a first-party skill wins a name collision with an
    operator-supplied one and the loser is recorded rather than silently
    displaced. It goes through ``SkillRegistry.snapshot`` exactly like any other
    root: there is deliberately no shortcut path for first-party content, because
    a second loader would be a second set of bounds and a second place for the
    snapshot ordering to be got wrong.
    """
    tools: dict[str, Tool] = {}
    catalogue = ""
    registry: SkillRegistry | None = None

    # The snapshot happens INSIDE this block, deliberately. When the first-party
    # skills come from a loader that cannot expose a real directory, the context
    # manager materialises them for its duration and removes them on exit -- so
    # completing the snapshot here is what guarantees every servable byte was
    # read while the source still existed, and that nothing can read it later.
    with _builtin_root(include_builtin_skills, workspace_root) as builtin:
        roots = [*([builtin] if builtin is not None else []), *skill_roots]
        if roots:
            limits = bounds or SkillBounds()
            registry = SkillRegistry.snapshot(roots, bounds=limits)
            tools.update(build_capability_tools(registry, bounds=limits))
            catalogue = registry.advertise()

    if detect_tests:
        tools["detect_tests"] = DetectTestsTool()

    # Static analysis, on the same opt-in terms and for the same reason: it
    # registers a tool, and the catalogue is generated into the system prompt.
    # The tool runs the analyser through the session's own executor and policy,
    # so nothing is decided here beyond whether it exists.
    if analyze:
        tools["analyze_code"] = AnalyzeCodeTool()

    # External documentation is registered only when a port exists AND the policy
    # admits the capability and operation. Absence is the safer interface: a
    # disabled tool that always answers "unavailable" would still appear in the
    # catalogue, and a model would spend turns discovering it cannot be used.
    #
    # One ledger, shared by every external capability admitted. External spend is
    # a property of the session rather than of who answered, so a run that reads
    # documentation and GitHub cannot take on more outside context than a run
    # that reads either alone. It also keeps ``CapabilityBundle.egress`` a single
    # number a report can state without knowing which providers existed.
    ledger: EgressLedger | None = None
    policy = egress_policy or EgressPolicy.none()
    if docs is not None and policy.admits(docs_capability, DOCS_LOOKUP):
        ledger = ledger or EgressLedger()
        tools["lookup_docs"] = LookupDocsTool(
            docs, policy=policy, ledger=ledger, capability=docs_capability
        )

    # Read-only GitHub context, on exactly the same terms. The port has no write
    # verb and the provider tool table admits only documented read tools, so
    # "read-only" is a property of what this tool can express rather than a rule
    # applied to what a model asks for.
    if github is not None and policy.admits(github_capability, GITHUB_LOOKUP):
        ledger = ledger or EgressLedger()
        tools["lookup_github"] = LookupGitHubTool(
            github, policy=policy, ledger=ledger, capability=github_capability
        )

    return CapabilityBundle(
        tools=tools, catalogue=catalogue, registry=registry, egress=ledger
    )


@contextmanager
def _builtin_root(
    include_builtin: bool, workspace_root: Path | None
) -> Iterator[SkillRoot | None]:
    """The engine's own skill root, admitted as ``builtin``, for one block.

    Yielded from a context manager because ``builtin_skill_root`` may have had to
    extract packaged resources to a temporary directory; the caller must finish
    reading them before the block ends. Yields None when not requested, when the
    package is absent, or when the resource cannot be presented as a directory --
    all three are a run without first-party skills, which is valid.

    Callers place this root **first**, which is the whole of the shadowing rule:
    ``SkillRegistry.snapshot`` keeps the first package it sees for a name, so
    ordering the engine's own root ahead of operator roots is what stops an
    operator quietly replacing a first-party skill with something of the same
    name.
    """
    if not include_builtin:
        yield None
        return
    with builtin_skill_root() as path:
        if path is None:
            yield None
            return
        yield SkillRoot.create(path, trust_tier=TRUST_BUILTIN, workspace_root=workspace_root)


def context_sources_from(states: Sequence[TaskState]) -> dict[str, Any]:
    """What entered the model's context besides the workspace and its own turns.

    Names, counts and digests -- never content. A skill body is bounded on the
    way into context precisely so it does not have to be bounded again on the way
    into a report, and storing it here would turn a run record into a transcript.

    ``digests`` maps each disclosed key (``skill`` or ``skill/reference``) to the
    sha256 of the source as read at snapshot, which is what lets a reader say
    exactly which bytes the model saw even when the file on disk has since
    changed. That case is real: a skill root may sit inside the workspace.

    Static fields come from the final state -- discovery happened once, so every
    round carries the same values -- while events accumulate across rounds, the
    way commands_run already does.

    Shared by both agents rather than reimplemented per report: the Coding Agent
    passes its verified run's states, the Debug Agent its fix session's, and the
    shape a reader sees is the same in both. A second copy would drift the moment
    one of them gained a field.
    """
    final = states[-1]
    events = [event for state in states for event in state.skill_events]
    # The last round that detected anything wins: detection is an observation of
    # the workspace as it then stood, and a repair round re-running it is a fresh
    # answer rather than a second opinion. None throughout means it never ran.
    detection = next(
        (state.test_detection for state in reversed(states) if state.test_detection),
        None,
    )
    external = {
        "calls": sum(state.external_calls for state in states),
        "chars": sum(state.external_chars for state in states),
        "failures": [reason for state in states for reason in state.external_failures],
        "events": [event for state in states for event in state.external_events],
    }
    # Every scan across every round, in order. Metadata only -- counts, rule
    # ids, exit status -- so a report can say what was analysed and what came
    # back without carrying the analyser's output.
    analysis = [run for state in states for run in state.analysis_runs]
    return {
        "test_detection": detection,
        "analysis": analysis or None,
        "external": external if external["events"] else None,
        "skills": {
            "advertised": list(final.advertised_skills),
            "loaded": [name for state in states for name in state.loaded_skills],
            "references": [
                key for state in states for key in state.loaded_skill_references
            ],
            "chars": sum(state.skill_chars for state in states),
            "events": events,
            "errors": list(final.skill_discovery_errors),
            "shadowed": list(final.skill_shadowed),
            "roots": list(final.skill_roots),
            "mutations": list(final.skill_source_mutations),
            "digests": {
                event["name"]
                if event["reference"] is None
                else f"{event['name']}/{event['reference']}": event["digest"]
                for event in events
                if event["digest"]
            },
        }
    }


__all__ = [
    "CapabilityBundle",
    "build_capabilities",
    "build_capability_tools",
    "context_sources_from",
]
