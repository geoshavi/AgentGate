"""Discovery and the snapshot: the one place skill bytes are ever read.

``SkillRegistry.snapshot()`` walks every admitted root, reads every ``SKILL.md``
and every enumerated reference, and returns a registry holding only frozen
``SkillPackage`` values. After it returns, the registry retains a ``source_root``
for provenance and **no path it will ever read from again**.

That ordering is the security property. ``build_capability_tools`` (C2) takes an
already-snapshotted registry as an argument, so a mutating tool object cannot
exist before the content it might have corrupted was already read. There is
deliberately **no** ``reload``, ``refresh`` or ``rescan``: a skill cannot reload
itself because the verb does not exist.

Bounds arrive as a plain ``SkillBounds`` of integers rather than as
``codeagent.limits.Limits``. ``capabilities/`` is a leaf (architecture Rule H)
and must stay importable with no agent package on the path; C2 maps one onto the
other at the seam, which is also the only place that mapping can drift.

A malformed skill is **excluded and recorded**, never half-registered. One bad
manifest must not cost a caller its other skills.
"""

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from engine.capabilities.errors import ManifestError, SkillError
from engine.capabilities.skills.manifest import (
    MAX_FRONTMATTER_BYTES,
    parse_manifest,
)
from engine.capabilities.skills.package import ReferenceContent, SkillPackage
from engine.capabilities.skills.roots import SkillRoot, is_denied_name

SKILL_FILE = "SKILL.md"
REFERENCES_DIR = "references"
ASSETS_DIR = "assets"
SCRIPTS_DIR = "scripts"


@dataclass(frozen=True)
class SkillBounds:
    """Deterministic bounds for the skills capability.

    Plain integers, not ``Limits``: see the module docstring. Defaults mirror the
    blueprint's §9 and are ceilings, not targets -- ``max_skill_body_chars`` in
    particular is set to the Agent Skills specification's own recommendation
    (~5 000 tokens) so a spec-conformant skill is never truncated, while
    first-party skills are expected far below it.
    """

    max_advertised_skills: int = 8
    max_skill_metadata_chars: int = 240
    max_skills_catalogue_chars: int = 2_000
    max_loaded_skills: int = 2
    max_loaded_references: int = 3
    max_skill_body_chars: int = 20_000
    max_skill_reference_chars: int = 4_000
    max_skill_references: int = 5
    max_skill_source_bytes: int = 256_000
    max_frontmatter_bytes: int = MAX_FRONTMATTER_BYTES


@dataclass(frozen=True)
class DiscoveryError:
    """One skill that could not be registered, and why."""

    root: str
    skill: str
    reason: str


@dataclass(frozen=True)
class ShadowedSkill:
    """A duplicate name a later root lost. Recorded so an operator root cannot
    silently displace a first-party skill."""

    name: str
    kept_root: str
    shadowed_root: str


class SkillRegistry:
    """The snapshotted set of skills for one run.

    Construct with ``snapshot()``. The initialiser is private by convention --
    it takes already-frozen packages and performs no I/O -- so that "everything
    servable was read before this object existed" holds for every instance.
    """

    def __init__(
        self,
        packages: Sequence[SkillPackage],
        *,
        roots: Sequence[SkillRoot],
        errors: Sequence[DiscoveryError] = (),
        shadowed: Sequence[ShadowedSkill] = (),
        bounds: SkillBounds | None = None,
    ) -> None:
        self._packages = {package.name: package for package in packages}
        self._roots = tuple(roots)
        self._errors = tuple(errors)
        self._shadowed = tuple(shadowed)
        self._bounds = bounds or SkillBounds()

    # -- construction -------------------------------------------------------

    @classmethod
    def snapshot(
        cls,
        roots: Iterable[SkillRoot],
        *,
        bounds: SkillBounds | None = None,
    ) -> "SkillRegistry":
        """Read every servable byte, once, and freeze it.

        Roots are honoured in the order given -- builtin first by convention --
        and on a duplicate skill name **the first root wins**, with the loser
        recorded in ``shadowed``.
        """
        limits = bounds or SkillBounds()
        packages: list[SkillPackage] = []
        errors: list[DiscoveryError] = []
        shadowed: list[ShadowedSkill] = []
        seen: dict[str, SkillPackage] = {}

        ordered_roots = tuple(roots)
        for root in ordered_roots:
            for skill_dir in _skill_directories(root):
                name = skill_dir.name
                if name in seen:
                    shadowed.append(
                        ShadowedSkill(
                            name=name,
                            kept_root=str(seen[name].source_root),
                            shadowed_root=str(root.path),
                        )
                    )
                    continue
                try:
                    package = _read_package(skill_dir, root, limits)
                except (ManifestError, SkillError) as exc:
                    errors.append(DiscoveryError(str(root.path), name, str(exc)))
                    continue
                except OSError as exc:
                    errors.append(DiscoveryError(str(root.path), name, f"unreadable: {exc}"))
                    continue
                seen[name] = package
                packages.append(package)
                if len(packages) >= limits.max_advertised_skills:
                    break

        return cls(
            packages,
            roots=ordered_roots,
            errors=errors,
            shadowed=shadowed,
            bounds=limits,
        )

    # -- reading ------------------------------------------------------------

    @property
    def bounds(self) -> SkillBounds:
        return self._bounds

    @property
    def roots(self) -> tuple[SkillRoot, ...]:
        return self._roots

    @property
    def errors(self) -> tuple[DiscoveryError, ...]:
        return self._errors

    @property
    def shadowed(self) -> tuple[ShadowedSkill, ...]:
        return self._shadowed

    def names(self) -> tuple[str, ...]:
        return tuple(self._packages)

    def get(self, name: str) -> SkillPackage:
        """One package, from memory.

        Raises:
            SkillError: the name was never registered. The message names the
                registered set, so a caller's next attempt can be correct.
        """
        try:
            return self._packages[name]
        except KeyError:
            raise SkillError(
                f"unknown skill {name!r}; registered skills: {sorted(self._packages) or 'none'}"
            ) from None

    def advertise(self) -> str:
        """The bounded catalogue: metadata only, never a body.

        Capped twice -- per skill and in total -- because this is the only text
        this layer adds to a prompt unconditionally.
        """
        lines: list[str] = []
        used = 0
        for package in self._packages.values():
            line = package.catalogue_line(self._bounds.max_skill_metadata_chars)
            if used + len(line) + 1 > self._bounds.max_skills_catalogue_chars:
                break
            lines.append(line)
            used += len(line) + 1
        return "\n".join(lines)

    def mutations_from_ledger(
        self, changed_files: Iterable[str], *, workspace_root: Path | str
    ) -> tuple[str, ...]:
        """Which recorded workspace writes landed inside a skill root.

        Derived **only** from evidence the harness already holds -- the caller's
        list of files it recorded as written. Nothing here reads a file: a
        re-read at this point would reintroduce exactly the lazily-trusted
        channel the snapshot exists to close, and "we only read it to compare" is
        one refactor away from "we read it and used it".

        A root that does not overlap the workspace is skipped: an agent has no
        write path to it, so a ledger entry can never name one. Detecting a third
        party editing an external root is deferred (blueprint §13.11).
        """
        workspace = Path(workspace_root).resolve()
        prefixes: list[str] = []
        for root in self._roots:
            if not root.overlaps_workspace:
                continue
            try:
                prefix = root.path.relative_to(workspace).as_posix()
            except ValueError:  # pragma: no cover - overlaps implies relative_to works
                continue
            prefixes.append("" if prefix == "." else prefix)

        hits: list[str] = []
        for entry in changed_files:
            posix = entry.replace("\\", "/").lstrip("./")
            for prefix in prefixes:
                if not prefix or posix == prefix or posix.startswith(f"{prefix}/"):
                    hits.append(entry)
                    break
        return tuple(hits)


# -- snapshot internals ------------------------------------------------------


def _skill_directories(root: SkillRoot) -> list[Path]:
    """Candidate skill directories in one root, sorted for determinism.

    A directory without a ``SKILL.md`` is skipped silently: it is not a
    malformed skill, it is not a skill.
    """
    try:
        entries = sorted(root.path.iterdir())
    except OSError:  # pragma: no cover - the root was validated as a directory
        return []
    return [
        entry
        for entry in entries
        if entry.is_dir()
        and not is_denied_name(entry.name)
        and (entry / SKILL_FILE).is_file()
    ]


def _read_package(skill_dir: Path, root: SkillRoot, bounds: SkillBounds) -> SkillPackage:
    """Read one skill completely. The only function in the package that does I/O."""
    source = _read_text(skill_dir / SKILL_FILE, bounds.max_skill_source_bytes)
    manifest = parse_manifest(
        source.text, expected_name=skill_dir.name, max_bytes=bounds.max_frontmatter_bytes
    )
    from engine.capabilities.skills.manifest import split_frontmatter

    _, body = split_frontmatter(source.text, max_bytes=bounds.max_frontmatter_bytes)
    clipped, truncated = _clip(body, bounds.max_skill_body_chars)

    return SkillPackage(
        manifest=manifest,
        body=clipped,
        body_truncated=truncated,
        body_digest=source.digest,
        references=_read_references(skill_dir, root, bounds),
        assets=_list_names(skill_dir / ASSETS_DIR, root),
        scripts=_list_names(skill_dir / SCRIPTS_DIR, root),
        source_root=root.path,
        trust_tier=root.trust_tier,
        overlaps_workspace=root.overlaps_workspace,
    )


def _read_references(
    skill_dir: Path, root: SkillRoot, bounds: SkillBounds
) -> MappingProxyType[str, ReferenceContent]:
    """Enumerate and read this skill's references, eagerly.

    Eager because a reference must have exactly the protection ``SKILL.md`` has:
    reading one lazily would leave a second channel open past the point where the
    agent can write.

    Only regular files that are direct children survive. A nested file is not
    enumerated at all, which is what makes a nested key unrepresentable later --
    the specification also asks for references one level deep.
    """
    directory = skill_dir / REFERENCES_DIR
    if not directory.is_dir():
        return MappingProxyType({})

    out: dict[str, ReferenceContent] = {}
    for entry in sorted(directory.iterdir()):
        if len(out) >= bounds.max_skill_references:
            break
        if not entry.is_file() or is_denied_name(entry.name):
            continue
        # resolve()-then-contain: a symlink pointing outside the root is caught
        # here even though its literal name looked ordinary.
        if not root.contains(entry):
            continue
        try:
            name = root.component(entry.name)
        except SkillError:
            continue
        try:
            source = _read_text(entry, bounds.max_skill_source_bytes)
        except OSError:
            continue
        text, truncated = _clip(source.text, bounds.max_skill_reference_chars)
        out[name] = ReferenceContent(
            name=name,
            text=text,
            truncated=truncated,
            chars=len(text),
            digest=source.digest,
        )
    return MappingProxyType(out)


def _list_names(directory: Path, root: SkillRoot) -> tuple[str, ...]:
    """Names of the files in ``assets/`` or ``scripts/``. **Never contents.**

    Recorded so a report can say what a skill shipped. Reading them would spend
    the context budget this layer exists to protect, and executing them is
    forbidden outright -- nothing in this package can run anything.
    """
    if not directory.is_dir():
        return ()
    try:
        entries = sorted(directory.iterdir())
    except OSError:  # pragma: no cover
        return ()
    return tuple(
        entry.name
        for entry in entries
        if entry.is_file() and not is_denied_name(entry.name) and root.contains(entry)
    )


@dataclass(frozen=True)
class _Source:
    text: str
    digest: str


def _read_text(path: Path, max_bytes: int) -> _Source:
    """Read a file under a byte ceiling, digesting what was actually read.

    Binary mode, deliberately: the digest must cover the bytes as they are on
    disk -- before any character clipping and before any newline translation --
    so it identifies the source even when the stored text is truncated.

    The decoded text is then newline-normalised by hand, which text mode would
    have done for us and binary mode does not. Without it a CRLF ``SKILL.md``
    parses as a line ending in a stray ``\\r``, and the front-matter delimiter
    ``---\\r`` never matches ``^---$``. That is not hypothetical: every file
    written by ``Path.write_text`` on Windows is CRLF.
    """
    with path.open("rb") as handle:
        raw = handle.read(max_bytes)
    decoded = raw.decode("utf-8", errors="replace")
    return _Source(
        text=decoded.replace("\r\n", "\n").replace("\r", "\n"),
        digest=hashlib.sha256(raw).hexdigest(),
    )


def _clip(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit], True


__all__ = [
    "DiscoveryError",
    "ShadowedSkill",
    "SkillBounds",
    "SkillRegistry",
]
