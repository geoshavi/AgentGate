"""The model-facing half of the skills capability: one tool, one lookup.

The adapter across the capability seam. Everything below it -- ``SkillLoader``,
``SkillPackage`` -- trades in plain values and knows nothing about ``Tool``,
``ToolContext`` or ``ToolResult``; everything above it is ordinary Coding Agent
machinery. This module is the only place the two meet, which is what keeps
``engine/capabilities/`` a leaf (architecture Rule H).

Shaped exactly like ``debugagent/tools/repro.py``: a per-session tool instance
constructed with the state it may serve, injected through the tools dict, and
adding a *constraint* rather than an execution path. It performs **no filesystem
access at all** -- the loader it holds cannot, and this module does not try.

``load_skill`` is an ordinary tool. It spends one ``max_tool_calls`` like every
other, including when it refuses and when it declines a duplicate. There is no
private capability budget, because a private budget is a budget the session's
own bounds cannot see.

Failures are values, not exceptions: an unknown skill, an unknown reference and
an exhausted disclosure budget all come back as ``ToolResult(ok=False)`` naming
what *is* available, so the model's next turn can be correct.
"""

from typing import Any

from engine.capabilities.errors import SkillError
from engine.capabilities.skills import LoadedSkill, SkillLoader
from engine.codeagent.state import CapabilityEvent, ToolResult
from engine.codeagent.tools.base import ToolContext, ToolError, failed, ok, str_arg


class LoadSkillTool:
    """Disclose one advertised skill, or one of its enumerated references."""

    name = "load_skill"
    description = (
        "Read the full instructions for one of the skills listed under 'Available "
        "skills'. Args: {\"skill\": \"<name>\"} for the skill's procedure, or "
        '{"skill": "<name>", "reference": "<file>"} for one of the reference files '
        "that skill lists. Only advertised skills and already-listed references can "
        "be requested; this reads nothing from the workspace."
    )

    def __init__(self, loader: SkillLoader) -> None:
        self._loader = loader

    @property
    def loader(self) -> SkillLoader:
        """The session's disclosure budget. For reporting, not for editing."""
        return self._loader

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        """Serve from the snapshot, and record what was disclosed.

        Every outcome -- served, duplicate, refused -- appends exactly one
        ``CapabilityEvent`` to ``ctx.capability_log``, so the report can
        distinguish "the model was shown this" from "the model asked and was
        told no" without inferring either from a tool-call count.
        """
        try:
            name = str_arg(args, "skill")
        except ToolError as exc:
            ctx.capability_log.append(
                CapabilityEvent(kind="skill", name="", error=str(exc))
            )
            return failed(f"ToolError: {exc}")

        reference = args.get("reference")
        if reference is not None and not isinstance(reference, str):
            message = f"argument 'reference' must be a string, got {type(reference).__name__}"
            ctx.capability_log.append(
                CapabilityEvent(kind="skill", name=name, error=message)
            )
            return failed(f"ToolError: {message}")

        try:
            loaded = self._loader.load(name, reference=reference)
        except SkillError as exc:
            ctx.capability_log.append(
                CapabilityEvent(
                    kind="skill", name=name, reference=reference, error=str(exc)
                )
            )
            return failed(f"SkillError: {exc}")

        ctx.capability_log.append(
            CapabilityEvent(
                kind="skill",
                name=loaded.name,
                reference=loaded.reference,
                chars=loaded.chars,
                truncated=loaded.truncated,
                duplicate=loaded.duplicate,
                digest=(
                    "" if loaded.duplicate
                    else self._digest_for(loaded.name, loaded.reference)
                ),
            )
        )
        return ok(_render(loaded), ctx)

    def _digest_for(self, name: str, reference: str | None) -> str:
        """Snapshot provenance for what was just served.

        Read from the frozen package, so the report can name the exact bytes the
        model saw even if the file on disk has since changed.
        """
        package = self._loader.registry.get(name)
        if reference is None:
            return package.body_digest
        content = package.references.get(reference)
        return content.digest if content is not None else ""


def _render(loaded: LoadedSkill) -> str:
    """The observation: a short provenance header, then the text.

    Names the skill, the reference when there is one, the character count and
    whether it was truncated -- the four things a reader of the transcript needs
    to judge what the model was working from. No filesystem path appears: the
    model addresses skills by name and references by key, so a path would be
    both useless to it and an unnecessary disclosure about the host.
    """
    header = [f"skill: {loaded.name}"]
    if loaded.reference is not None:
        header.append(f"reference: {loaded.reference}")
    if loaded.duplicate:
        header.append("status: already loaded earlier in this session")
        return "\n".join(header)
    header.append(f"chars: {loaded.chars}")
    header.append(f"truncated: {'true' if loaded.truncated else 'false'}")
    return "\n".join(header) + "\n---\n" + loaded.body


__all__ = ["LoadSkillTool"]
