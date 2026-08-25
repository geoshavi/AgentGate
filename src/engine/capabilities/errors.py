"""Refusals the capabilities layer makes.

One base class so a caller can catch the whole layer, and narrow subclasses so a
caller that cares can tell a bad path from a bad manifest. Deliberately shallow:
these are refusals, not a domain model, and every one of them is expected to be
rendered to a human or handed back as a tool observation.

Nothing here inherits from an ``engine.codeagent`` exception. The capabilities
package is a leaf (architecture Rule H) and must stay importable without an
agent package on the path.
"""


class CapabilityError(Exception):
    """Base for every refusal this package makes."""


class SkillError(CapabilityError):
    """A skill could not be discovered, registered, or served."""


class SkillRootError(SkillError):
    """A skill root, or a path inside one, is unusable or out of bounds."""


class ManifestError(SkillError):
    """``SKILL.md`` front matter is missing, malformed, unsafe, or invalid."""


__all__ = ["CapabilityError", "ManifestError", "SkillError", "SkillRootError"]
