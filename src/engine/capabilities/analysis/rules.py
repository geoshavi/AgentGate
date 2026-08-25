"""The engine's own ruleset, located as a real directory for the length of a scan.

The same mechanism as ``capabilities/skills/roots.py:builtin_skill_root``, and
for the same reasons: ``importlib.resources`` rather than a path relative to the
repository root, so one lookup serves a source checkout and an installed wheel
alike. Resolving relative to the process's working directory would be wrong in
both -- during a run that directory is the *target workspace*, and a ``rules``
folder there is not ours.

**A context manager because materialisation may be needed and must be bounded.**
For a normal filesystem install the resource is already a directory and is
yielded directly; for a loader that does not expose one, the files are extracted
for the duration of the block and removed on exit. The scan therefore happens
inside the block, and no path outlives it.

Yields None rather than raising when the package is absent or unreadable: a run
without the first-party ruleset is a run without this capability, not a broken
one.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from importlib import resources
from pathlib import Path

BUILTIN_RULE_PACKAGE = "engine.rule_library"

# What the shipped ruleset is called in a report. A name rather than a path: a
# path would put this machine's directory layout into a run record, and would
# differ between a checkout and a wheel for what is the same content.
BUILTIN_RULESET = "agentgate-builtin"


@contextmanager
def builtin_ruleset() -> Iterator[Path | None]:
    """Yield a real directory holding the engine's first-party Semgrep rules."""
    try:
        resource = resources.files(BUILTIN_RULE_PACKAGE)
    except (ImportError, ModuleNotFoundError, TypeError):
        yield None
        return

    if isinstance(resource, Path):
        yield resource if resource.is_dir() else None
        return

    try:
        with resources.as_file(resource) as materialised:
            yield materialised if materialised.is_dir() else None
    except (OSError, ValueError):
        # as_file() on a directory requires Python 3.12+, and an exotic loader
        # may refuse entirely. Losing the ruleset is a degradation, not a
        # failure: the run proceeds without static analysis.
        yield None


__all__ = ["BUILTIN_RULESET", "BUILTIN_RULE_PACKAGE", "builtin_ruleset"]
