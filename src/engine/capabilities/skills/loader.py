"""Progressive disclosure: deciding *when* already-trusted bytes enter context.

The loader is the model-facing half of the skills capability, and its entire
implementation is a lookup. It holds a snapshotted ``SkillRegistry`` and performs
**zero filesystem access** -- no open, no stat, no digest, no rescan. That is not
an optimisation; it is the invariant. In the self-hosting case the skill files
live inside a workspace the agent may write to, so a read at this point would
read the agent's own output and hand it back as first-party procedure.

    Progressive disclosure is about prompt/token inclusion, NOT about delayed
    trust establishment.

Trust was established once, at snapshot. This class only decides what is shown.

Two budgets, bounding two different things:

  ``max_loaded_skills``      distinct bodies admitted into context
  ``max_loaded_references``  reference files admitted into context

Both are about *context*. The tool-call budget that bounds *actions* lives in the
session (C2) -- a load costs one ordinary tool call there, so skill loading can
never be a free side channel.

A reference is addressed by **key**, never by path. The model's string is looked
up in the package's frozen mapping; a name that is not a key was never
enumerated, so traversal, absolute paths and nested paths are not refused so much
as unrepresentable.
"""

from dataclasses import dataclass

from engine.capabilities.errors import SkillError
from engine.capabilities.skills.registry import SkillBounds, SkillRegistry


@dataclass(frozen=True)
class LoadedSkill:
    """One disclosure. ``reference`` is None when the body was served."""

    name: str
    body: str
    truncated: bool
    chars: int
    reference: str | None = None
    duplicate: bool = False
    """True when this content was already disclosed earlier in the session, so
    ``body`` is a short note rather than the content. An explicit flag because
    the alternative -- a caller matching on the note's wording -- would make a
    prose edit a behaviour change."""

    @property
    def key(self) -> str:
        """Stable identity for reporting: ``skill`` or ``skill/reference``."""
        return self.name if self.reference is None else f"{self.name}/{self.reference}"


class SkillLoader:
    """Serves skill content from a snapshot, under per-session budgets.

    One instance per session: the budgets are consumption, and sharing an
    instance across sessions would share their spend.
    """

    def __init__(self, registry: SkillRegistry, *, bounds: SkillBounds | None = None) -> None:
        self._registry = registry
        self._bounds = bounds or registry.bounds
        self._loaded_skills: list[str] = []
        self._loaded_references: list[str] = []

    @property
    def registry(self) -> SkillRegistry:
        """The snapshot this loader serves. Read-only, for provenance: a caller
        reporting what was disclosed needs the digest that came with it."""
        return self._registry

    @property
    def loaded_skills(self) -> tuple[str, ...]:
        return tuple(self._loaded_skills)

    @property
    def loaded_references(self) -> tuple[str, ...]:
        return tuple(self._loaded_references)

    def load(self, name: str, *, reference: str | None = None) -> LoadedSkill:
        """Disclose one skill body, or one of its references.

        Serves from the in-memory snapshot. No filesystem access happens here,
        for any reason -- see the module docstring.

        Raises:
            SkillError: unknown skill, unknown reference key, or a budget
                already spent. Every message names what *is* available, so the
                caller's next attempt can succeed.
        """
        package = self._registry.get(name)  # raises SkillError naming the registered set

        if reference is not None:
            return self._load_reference(package.name, reference)

        if name in self._loaded_skills:
            # Already in context. Re-sending the body would spend the context
            # budget twice for no new information; the caller still paid a tool
            # call for the attempt, which is the honest accounting.
            return LoadedSkill(
                name=package.name,
                body=f"skill {package.name!r} is already loaded in this session",
                truncated=False,
                chars=0,
                duplicate=True,
            )

        if len(self._loaded_skills) >= self._bounds.max_loaded_skills:
            raise SkillError(
                f"cannot load {name!r}: max_loaded_skills is "
                f"{self._bounds.max_loaded_skills} and this session already loaded "
                f"{', '.join(self._loaded_skills)}"
            )

        self._loaded_skills.append(package.name)
        return LoadedSkill(
            name=package.name,
            body=package.body,
            truncated=package.body_truncated,
            chars=len(package.body),
        )

    def _load_reference(self, name: str, reference: str) -> LoadedSkill:
        package = self._registry.get(name)
        available = package.reference_names

        # A key lookup, deliberately. The string is never joined onto a path, so
        # '../x', '/etc/passwd' and 'nested/x' simply are not keys.
        content = package.references.get(reference) if isinstance(reference, str) else None
        if content is None:
            raise SkillError(
                f"skill {name!r} has no reference {reference!r}; "
                f"available references: {list(available) or 'none'}"
            )

        key = f"{name}/{reference}"
        if key in self._loaded_references:
            return LoadedSkill(
                name=name,
                body=f"reference {key!r} is already loaded in this session",
                truncated=False,
                chars=0,
                duplicate=True,
                reference=reference,
            )

        if len(self._loaded_references) >= self._bounds.max_loaded_references:
            raise SkillError(
                f"cannot load reference {key!r}: max_loaded_references is "
                f"{self._bounds.max_loaded_references} and this session already loaded "
                f"{', '.join(self._loaded_references)}"
            )

        self._loaded_references.append(key)
        return LoadedSkill(
            name=name,
            body=content.text,
            truncated=content.truncated,
            chars=content.chars,
            reference=reference,
        )


__all__ = ["LoadedSkill", "SkillLoader"]
