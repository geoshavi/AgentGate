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


class EgressDenied(CapabilityError):
    """An external capability or operation is not admitted, or its budget is spent.

    Raised by ``EgressPolicy.check`` and ``EgressLedger.begin_call`` -- always
    *before* anything leaves the machine, so a refusal costs no round trip.
    """


class DocsUnavailable(CapabilityError):
    """A documentation lookup produced nothing usable.

    One class for every way that can happen -- bad input, a timeout, an
    unparsable response, no matching library, a transport fault -- because the
    caller's next move is the same in all of them: continue from repository
    evidence. Distinguishing them would offer a choice nobody can act on.
    """


__all__ = [
    "CapabilityError",
    "DocsUnavailable",
    "EgressDenied",
    "ManifestError",
    "SkillError",
    "SkillRootError",
]
