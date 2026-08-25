"""Agent Skills: discovery, the immutable snapshot, and progressive disclosure.

The public surface of the skills capability. Import from here rather than from
the modules below it, so the internal split can change without touching callers.

The one invariant worth restating at the package boundary: ``SkillRegistry``
reads every servable byte at ``snapshot()`` and ``SkillLoader`` reads none. There
is no reload, refresh or rescan, because trust is established by that ordering
and a second read would undo it.
"""

from engine.capabilities.skills.loader import LoadedSkill, SkillLoader
from engine.capabilities.skills.manifest import (
    MAX_DESCRIPTION_CHARS,
    MAX_FRONTMATTER_BYTES,
    MAX_NAME_CHARS,
    WHEN_TO_USE_KEY,
    SkillManifest,
    parse_manifest,
)
from engine.capabilities.skills.package import ReferenceContent, SkillPackage
from engine.capabilities.skills.registry import (
    DiscoveryError,
    ShadowedSkill,
    SkillBounds,
    SkillRegistry,
)
from engine.capabilities.skills.roots import (
    TRUST_BUILTIN,
    TRUST_OPERATOR,
    SkillRoot,
    is_denied_name,
)

__all__ = [
    "MAX_DESCRIPTION_CHARS",
    "MAX_FRONTMATTER_BYTES",
    "MAX_NAME_CHARS",
    "TRUST_BUILTIN",
    "TRUST_OPERATOR",
    "WHEN_TO_USE_KEY",
    "DiscoveryError",
    "LoadedSkill",
    "ReferenceContent",
    "ShadowedSkill",
    "SkillBounds",
    "SkillLoader",
    "SkillManifest",
    "SkillPackage",
    "SkillRegistry",
    "SkillRoot",
    "is_denied_name",
    "parse_manifest",
]
