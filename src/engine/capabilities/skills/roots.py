"""A skill root: a rooted, read-only view of one directory of skills.

Two guarantees, and nothing else:

  1. A resolved path is inside the root, or the call raises.
  2. A resolved path is not credential-shaped, or the call raises.

Both are enforced through ``capabilities/paths.py``, which holds the containment
check and the credential screen once for every capability that reads a file.

Deliberately a reimplementation of ``codeagent.workspace.Workspace.resolve``'s
technique rather than an import of it, for three reasons in order of weight:

  1. ``capabilities/`` is a leaf and may not import ``codeagent`` (Rule H).
  2. A skill root is **read-only**. ``Workspace`` also carries a mutation ledger
     and a ``max_files_changed`` ceiling; inheriting those would mean this object
     could be handed to something that writes. There is no write path here at
     all -- no ``note_changed``, no ``open`` for writing.
  3. ``workspace.py`` already documents choosing duplication over coupling for
     exactly this trade ("Duplicating eleven lines is the cheaper of the two
     costs"), against ``orchestrator/agents/common.py``.

**Overlap with the target workspace is recorded, never refused.** AgentGate must
be able to debug its own repository, and ``skills/`` then sits inside the
workspace. Refusing that would make self-hosting impossible, and would rest on
path separation -- a property of a layout, not of trust. What makes a skill
trustworthy is the snapshot ordering in ``registry.py``, not its location.
"""

from dataclasses import dataclass
from pathlib import Path, PurePath

from engine.capabilities.errors import SkillRootError
from engine.capabilities.paths import contained, is_denied_name

TRUST_BUILTIN = "builtin"
TRUST_OPERATOR = "operator"
TRUST_TIERS = frozenset({TRUST_BUILTIN, TRUST_OPERATOR})

# The credential screen lives in capabilities/paths.py, shared with the test
# detector: two capabilities read files for different reasons and must refuse the
# same names, and two copies of a security screen is two chances to fix only one.
# Re-exported here so ``from ...skills.roots import is_denied_name`` still works.


@dataclass(frozen=True)
class SkillRoot:
    """One admitted directory of skills, with its trust provenance.

    ``trust_tier`` records *who admitted this root*, which is a human decision
    made before the run. It deliberately does not confer any durable property:
    every admitted root, of either tier, is snapshotted identically, because
    "an operator named it" says nothing about whether it can change mid-run.
    """

    path: Path
    trust_tier: str
    overlaps_workspace: bool

    @classmethod
    def create(
        cls,
        path: Path | str,
        *,
        trust_tier: str = TRUST_BUILTIN,
        workspace_root: Path | str | None = None,
    ) -> "SkillRoot":
        """Admit a root, or raise.

        Raises:
            SkillRootError: the tier is unknown, or the path is not a directory.
        """
        if trust_tier not in TRUST_TIERS:
            raise SkillRootError(
                f"unknown trust tier {trust_tier!r}; expected one of {sorted(TRUST_TIERS)}"
            )
        resolved = Path(path).resolve()
        if not resolved.is_dir():
            raise SkillRootError(f"skill root is not an existing directory: {resolved}")
        return cls(
            path=resolved,
            trust_tier=trust_tier,
            overlaps_workspace=_overlaps(resolved, workspace_root),
        )

    # -- path guard ---------------------------------------------------------

    def component(self, name: str) -> str:
        """Validate ``name`` as a single, safe path component.

        Used for reference filenames. A reference is addressed by *key*, never by
        path, so anything with a separator, a traversal, a drive or a root is not
        merely unsafe -- it is not a component at all.

        Raises:
            SkillRootError: not a plain, allowed component.
        """
        if not isinstance(name, str) or not name.strip():
            raise SkillRootError("reference name must be a non-empty string")
        cleaned = name.strip()
        if cleaned in (".", ".."):
            raise SkillRootError(f"invalid reference name: {name!r}")
        # Normalise separators first so 'a\\b' is judged as two components on
        # POSIX too -- models emit Windows separators regardless of host OS.
        if "/" in cleaned or "\\" in cleaned:
            raise SkillRootError(
                f"reference name must be a single file name, not a path: {name!r}"
            )
        candidate = PurePath(cleaned)
        if candidate.is_absolute() or candidate.root or candidate.drive:
            raise SkillRootError(f"reference name must not be an absolute path: {name!r}")
        if is_denied_name(cleaned):
            raise SkillRootError(f"refusing a credential-shaped reference name: {name!r}")
        return cleaned

    def contains(self, candidate: Path) -> bool:
        """True if ``candidate`` resolves inside this root.

        Resolution follows symlinks first, so a link pointing outside the root is
        caught here even though its literal path looked harmless.
        """
        return contained(self.path, candidate)

    def relative(self, path: Path) -> str:
        """Posix-style path of ``path`` relative to the root, for reporting."""
        return path.resolve().relative_to(self.path).as_posix()


def builtin_skill_root() -> Path | None:
    """The engine's own ``skills/`` directory, or None if it is not there.

    Trusted by *provenance*: it ships with the code under review, so an operator
    who ran this engine already accepted it. That is the only thing the tier
    means -- admission is not durable, and this root is snapshotted exactly like
    any other (see ``registry.py``).

    Located relative to this file rather than the process's working directory,
    because the working directory during a run is the *target workspace* and a
    ``skills/`` folder there is not ours. Returns None rather than raising when
    absent: an installed wheel has no repository root, and a run with no
    first-party skills is a valid run, not a broken one.
    """
    candidate = Path(__file__).resolve().parents[4] / "skills"
    return candidate if candidate.is_dir() else None


def _overlaps(root: Path, workspace_root: Path | str | None) -> bool:
    """Whether this root lies inside the target workspace (or is it).

    Recorded, never fatal -- see the module docstring.
    """
    if workspace_root is None:
        return False
    try:
        workspace = Path(workspace_root).resolve()
    except OSError:  # pragma: no cover - resolve on a plain string does not fail
        return False
    return root == workspace or root.is_relative_to(workspace)


__all__ = [
    "TRUST_BUILTIN",
    "TRUST_OPERATOR",
    "TRUST_TIERS",
    "SkillRoot",
    "builtin_skill_root",
    "is_denied_name",
]
