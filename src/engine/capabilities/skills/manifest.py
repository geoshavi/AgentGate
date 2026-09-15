"""``SKILL.md`` front matter: parsed with a real YAML parser, then validated.

The Agent Skills specification says front matter is YAML, so this reads YAML. A
hand-rolled fixed-key reader was rejected: it would refuse syntactically valid
skills that use only standard fields -- folded scalars above all, which a
1024-character ``description`` makes routine rather than exotic -- and writing a
partial YAML parser to avoid a YAML dependency produces more code, more bugs and
less compatibility.

``yaml.safe_load`` is the documented-safe entry point: it constructs only
strings, numbers, booleans, ``None``, lists and dicts, and refuses ``!!python/*``
and every other custom constructor. ``yaml.load``, ``unsafe_load`` and
``full_load`` are never used here, and no custom ``Loader`` or constructor is
registered.

Three guards sit around the parse, because "safe against object construction" is
not the same as "safe":

1. **Size cap.** Only the front-matter block is parsed, and only up to
   ``max_frontmatter_bytes``. A file with no closing delimiter inside that window
   is refused rather than scanned to EOF.

2. **No anchors, aliases, foreign tags or multiple documents.** Checked
   *structurally*, over ``yaml.parse``'s event stream -- never by scanning the
   raw text for ``&`` or ``*``. Those characters appear constantly in ordinary
   prose ("Research & development", "Match *.py files"), and refusing them would
   break the common case while catching nothing an attacker could not rewrite.
   ``safe_load`` still expands aliases, so a ~1 KB document can expand without
   bound; the Agent Skills field set is flat scalars plus one string->string map,
   so anchors have no legitimate use and refusing them costs nothing real.

3. **Shape validation after parsing.** Types are checked and scalars are
   stringified, so an unquoted ``version: 1.0`` reads back as ``"1.0"`` rather
   than as a float.

**Parsing never grants authority.** This module produces a frozen data record.
``allowed-tools`` and ``compatibility`` are recorded because a report should be
able to state what a skill claimed, and are read by nothing that decides
anything -- see ``package.py`` and the blueprint's §4.8.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

import yaml

from engine.capabilities.errors import ManifestError

DELIMITER = "---"
MAX_FRONTMATTER_BYTES = 8_000

# Specification: 1-64 chars, lowercase alphanumeric and hyphens, no leading or
# trailing hyphen, no consecutive hyphens. Expressed as groups rather than a
# character class with lookarounds so all four rules are visible at once.
NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_NAME_CHARS = 64
MAX_DESCRIPTION_CHARS = 1_024
MAX_COMPATIBILITY_CHARS = 500

# Standard frontmatter keys this reader understands. Unknown keys are IGNORED,
# not rejected -- the forward-compatibility hinge that lets a skill written
# against a later spec still load here.
STANDARD_KEYS = frozenset(
    {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
)

# The AgentGate extension, namespaced inside the spec's own `metadata` map --
# the same convention Hermes uses with `metadata.hermes.*`. Optional: a skill
# carrying only `name` and `description` works unchanged.
WHEN_TO_USE_KEY = "agentgate.when_to_use"

# Tags a safe document may carry. `None` is the normal case (an implicit tag);
# an explicit standard tag is harmless. Anything else -- `!!python/object/...`,
# `!python/object:...`, a bare `!custom` -- is refused before construction.
ALLOWED_TAGS = frozenset(
    {
        "tag:yaml.org,2002:str",
        "tag:yaml.org,2002:int",
        "tag:yaml.org,2002:float",
        "tag:yaml.org,2002:bool",
        "tag:yaml.org,2002:null",
        "tag:yaml.org,2002:map",
        "tag:yaml.org,2002:seq",
    }
)


@dataclass(frozen=True)
class SkillManifest:
    """Validated front matter. A record, not a capability.

    ``allowed_tools`` is the specification's experimental ``allowed-tools``
    field, parsed and kept **only** so a report can say what the skill claimed.
    Nothing reads it to decide anything: in this system a skill is a file inside
    the artifact under test, and in the self-hosting case a model-writable one,
    so a field that turned a file into the grantor of capability would be
    escalation by design.
    """

    name: str
    description: str
    license: str = ""
    compatibility: str = ""
    allowed_tools: tuple[str, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))

    @property
    def when_to_use(self) -> str:
        """The catalogue line. Falls back to ``description`` when the optional
        extension is absent, so no extension is ever required."""
        return self.metadata.get(WHEN_TO_USE_KEY) or self.description


def split_frontmatter(text: str, *, max_bytes: int = MAX_FRONTMATTER_BYTES) -> tuple[str, str]:
    """Split ``text`` into (front matter, body), or raise.

    Only the first ``max_bytes`` characters are searched for the closing
    delimiter: a file that never closes its front matter is refused rather than
    scanned to EOF, which bounds the parser's input independently of file size.

    Raises:
        ManifestError: no opening delimiter, or no closing delimiter in range.
    """
    if not text.startswith(DELIMITER):
        raise ManifestError("SKILL.md must begin with a '---' front-matter delimiter")

    after_open = text[len(DELIMITER) :]
    if not after_open.startswith(("\n", "\r")):
        raise ManifestError("the opening '---' must be followed by a newline")

    window = after_open[:max_bytes]
    # `\r` is tolerated in the delimiter line as well as spaces and tabs. Callers
    # normalise newlines before reaching here, so this is defence in depth for a
    # caller that passes raw CRLF text straight in.
    match = re.search(r"^---[ \t\r]*$", window, re.MULTILINE)
    if match is None:
        raise ManifestError(
            f"no closing '---' within the first {max_bytes} bytes of front matter; "
            "front matter is bounded so an unterminated file cannot be scanned to EOF"
        )
    return window[: match.start()], after_open[match.end() :].lstrip("\r\n")


def assert_safe_yaml(source: str) -> None:
    """Refuse anchors, aliases, foreign tags and multi-document streams.

    Structural, over the event stream -- ``yaml.parse`` resolves the syntax, so
    ``"Research & development"`` and ``"Match *.py files"`` produce no anchor and
    no alias, while ``&defaults`` / ``*defaults`` produce both. A raw-text scan
    for those characters cannot tell the two apart and would refuse ordinary
    prose.

    Raises:
        ManifestError: any of the four, or the stream does not parse.
    """
    documents = 0
    try:
        for event in yaml.parse(source, Loader=yaml.SafeLoader):
            if isinstance(event, yaml.AliasEvent):
                raise ManifestError(
                    f"YAML alias '*{event.anchor}' is not allowed in skill front matter"
                )
            anchor = getattr(event, "anchor", None)
            if anchor:
                raise ManifestError(
                    f"YAML anchor '&{anchor}' is not allowed in skill front matter"
                )
            tag = getattr(event, "tag", None)
            if tag is not None and tag not in ALLOWED_TAGS:
                raise ManifestError(f"YAML tag {tag!r} is not allowed in skill front matter")
            if isinstance(event, yaml.DocumentStartEvent):
                documents += 1
                if documents > 1:
                    raise ManifestError(
                        "skill front matter must be a single YAML document"
                    )
    except yaml.YAMLError as exc:
        raise ManifestError(f"front matter is not valid YAML: {_one_line(exc)}") from exc


def parse_manifest(
    text: str,
    *,
    expected_name: str,
    max_bytes: int = MAX_FRONTMATTER_BYTES,
) -> SkillManifest:
    """Parse and validate one ``SKILL.md``.

    ``expected_name`` is the skill's directory name; the specification requires
    the two to match, and a mismatch is refused rather than silently preferring
    one of them.

    Raises:
        ManifestError: for every malformed, unsafe or invalid input.
    """
    front, _ = split_frontmatter(text, max_bytes=max_bytes)
    assert_safe_yaml(front)

    try:
        parsed = yaml.safe_load(front)
    except yaml.YAMLError as exc:
        raise ManifestError(f"front matter is not valid YAML: {_one_line(exc)}") from exc

    if parsed is None:
        raise ManifestError("front matter is empty")
    if not isinstance(parsed, dict):
        raise ManifestError(
            f"front matter must be a mapping, got {type(parsed).__name__}"
        )

    name = _scalar(parsed, "name", required=True)
    if len(name) > MAX_NAME_CHARS:
        raise ManifestError(f"name is {len(name)} characters; the maximum is {MAX_NAME_CHARS}")
    if not NAME_PATTERN.match(name):
        raise ManifestError(
            f"name {name!r} must be lowercase letters, digits and single hyphens, "
            "with no leading, trailing or consecutive hyphen"
        )
    if name != expected_name:
        raise ManifestError(
            f"name {name!r} must equal the skill directory name {expected_name!r}"
        )

    description = _scalar(parsed, "description", required=True)
    if len(description) > MAX_DESCRIPTION_CHARS:
        raise ManifestError(
            f"description is {len(description)} characters; "
            f"the maximum is {MAX_DESCRIPTION_CHARS}"
        )

    compatibility = _scalar(parsed, "compatibility")
    if len(compatibility) > MAX_COMPATIBILITY_CHARS:
        raise ManifestError(
            f"compatibility is {len(compatibility)} characters; "
            f"the maximum is {MAX_COMPATIBILITY_CHARS}"
        )

    return SkillManifest(
        name=name,
        description=description,
        license=_scalar(parsed, "license"),
        compatibility=compatibility,
        allowed_tools=tuple(_scalar(parsed, "allowed-tools").split()),
        metadata=_metadata(parsed.get("metadata")),
    )


# -- helpers ----------------------------------------------------------------


def _scalar(parsed: dict[str, Any], key: str, *, required: bool = False) -> str:
    """One scalar field, stringified and stripped.

    A list or mapping where a scalar belongs is a validation error, not something
    to coerce: ``str(['a'])`` would silently produce ``"['a']"`` and a report
    would then quote it as if the author had written it.
    """
    value = parsed.get(key)
    if value is None:
        if required:
            raise ManifestError(f"front matter is missing the required field {key!r}")
        return ""
    if isinstance(value, (dict, list, tuple, set)):
        raise ManifestError(f"{key!r} must be a scalar, got {type(value).__name__}")
    rendered = _stringify(value).strip()
    if required and not rendered:
        raise ManifestError(f"the required field {key!r} must not be empty")
    return rendered


def _metadata(value: Any) -> Mapping[str, str]:
    """The spec's ``metadata`` map: string keys to string values.

    Values are stringified so an unquoted ``version: 1.0`` becomes ``"1.0"``
    rather than a float -- the report's shape must not depend on whether the
    author reached for quotes.
    """
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, dict):
        raise ManifestError(f"'metadata' must be a mapping, got {type(value).__name__}")
    out: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise ManifestError(f"metadata keys must be strings, got {type(key).__name__}")
        if isinstance(item, (dict, list, tuple, set)):
            raise ManifestError(
                f"metadata value for {key!r} must be a scalar, got {type(item).__name__}"
            )
        out[key] = _stringify(item)
    return MappingProxyType(out)


def _stringify(value: Any) -> str:
    """Render a YAML scalar the way its author wrote it, as far as possible.

    ``True``/``None`` become ``"true"``/``""`` rather than Python's repr, and a
    float that is integral keeps its trailing ``.0`` so ``version: 1.0`` reads
    back as ``"1.0"``.
    """
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _one_line(exc: Exception) -> str:
    """A YAML error on one line, so it fits a discovery-error record."""
    return " ".join(str(exc).split())


__all__ = [
    "MAX_COMPATIBILITY_CHARS",
    "MAX_DESCRIPTION_CHARS",
    "MAX_FRONTMATTER_BYTES",
    "MAX_NAME_CHARS",
    "NAME_PATTERN",
    "STANDARD_KEYS",
    "WHEN_TO_USE_KEY",
    "SkillManifest",
    "assert_safe_yaml",
    "parse_manifest",
    "split_frontmatter",
]
