"""The immutable snapshot: what a skill is, once it has been read.

A ``SkillPackage`` is the *whole* of what may later be served -- body and every
enumerated reference -- captured at registry construction. It holds a
``source_root`` for provenance and nothing that can read from it again: there is
no path to a file, no open handle, and no method that touches the filesystem.

That is the security property, not a convenience. Serving a skill lazily would
mean trusting bytes read *after* the agent gained write tools, and in the
self-hosting case (``skills/`` inside the target workspace) those bytes may be
the agent's own output. Reading eagerly costs a few hundred kilobytes of memory
and buys the ordering guarantee that makes the whole layer safe.

Immutability is enforced, not documented: frozen dataclasses throughout, tuples
rather than lists, and ``MappingProxyType`` for the reference mapping so a caller
cannot insert a key that was never enumerated.

``assets`` and ``scripts`` are **names only**. Contents are never read. The
specification permits agents to execute ``scripts/``; AgentGate's runtime policy
is authoritative and forbids it, so nothing here exposes a way to run anything.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from engine.capabilities.skills.manifest import SkillManifest


@dataclass(frozen=True)
class ReferenceContent:
    """One reference file, frozen at snapshot time.

    ``digest`` covers the source bytes **as read**, before truncation, so a
    report can state exactly which file produced this text even when ``text``
    itself is clipped.
    """

    name: str
    text: str
    truncated: bool
    chars: int
    digest: str


@dataclass(frozen=True)
class SkillPackage:
    """A skill, frozen. Serving one touches no filesystem.

    ``overlaps_workspace`` records that this skill's root lies inside the target
    workspace -- the self-hosting case. It is reported, never fatal: the snapshot
    ordering is what makes that case safe, so refusing the overlap would forbid a
    legitimate configuration while adding no protection.
    """

    manifest: SkillManifest
    body: str
    body_truncated: bool
    body_digest: str
    references: Mapping[str, ReferenceContent]
    assets: tuple[str, ...]
    scripts: tuple[str, ...]
    source_root: Path
    trust_tier: str
    overlaps_workspace: bool

    @property
    def name(self) -> str:
        return self.manifest.name

    @property
    def reference_names(self) -> tuple[str, ...]:
        """Every reference key this package will answer to, in snapshot order."""
        return tuple(self.references)

    def catalogue_line(self, limit: int) -> str:
        """The one line this skill contributes to the advertised catalogue.

        Metadata only -- never the body. Truncation is by characters and marks
        itself, because a silently clipped sentence reads as a complete one.
        """
        text = " ".join(self.manifest.when_to_use.split())
        if len(text) > limit:
            text = text[: max(0, limit - 1)].rstrip() + "…"
        return f"- {self.name}: {text}"


__all__ = ["ReferenceContent", "SkillPackage"]
