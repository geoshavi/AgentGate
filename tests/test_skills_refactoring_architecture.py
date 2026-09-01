"""The first-party refactoring-architecture skill: manifest, packaging, load.

Three groups, proportionate to what test_skills_testing.py already proves for the
first-party mechanism itself (parsing, snapshotting, packaging, progressive
disclosure) -- this file does not re-derive those, it applies them to the new
content and adds the safety checks specific to what this skill says:

    conformance   does the shipped package parse and stay inside its bounds,
                  and does it register alongside the existing first-party skill
                  without a name collision?
    content       does the prose actually cover the procedure it claims to (map
                  before editing, separate fact from suggestion, small reversible
                  steps, defer to the testing skill, never weaken a test) and
                  never invent authority (no allowed-tools, no verdict/judge
                  language)?
    authority     does loading it change what the agent may actually do? It must
                  not.

The real skill is read directly, never mutated.
"""

import re
from pathlib import Path

import pytest

import engine.skill_library
from engine.capabilities.skills import (
    MAX_DESCRIPTION_CHARS,
    TRUST_BUILTIN,
    SkillBounds,
    SkillLoader,
    SkillRegistry,
    SkillRoot,
    parse_manifest,
)
from engine.codeagent.capabilities import build_capabilities
from engine.codeagent.policy import DEFAULT_POLICY, CommandDenied
from engine.codeagent.tools.registry import TOOL_REGISTRY

SKILL_NAME = "refactoring-architecture"
BOUNDS = SkillBounds()

LIBRARY_DIR = Path(engine.skill_library.__file__).resolve().parent


def skill_dir() -> Path:
    return LIBRARY_DIR / SKILL_NAME


def skill_text() -> str:
    return (skill_dir() / "SKILL.md").read_text(encoding="utf-8")


def reference_texts() -> dict[str, str]:
    directory = skill_dir() / "references"
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(directory.iterdir())}


def all_authored_text() -> dict[str, str]:
    return {"SKILL.md": skill_text(), **reference_texts()}


def flat(text: str) -> str:
    return " ".join(text.split()).lower()


def registry() -> SkillRegistry:
    return SkillRegistry.snapshot(
        [SkillRoot.create(LIBRARY_DIR, trust_tier=TRUST_BUILTIN)], bounds=BOUNDS
    )


# -- the package exists and conforms -----------------------------------------


def test_the_repository_ships_the_skill() -> None:
    assert (skill_dir() / "SKILL.md").is_file()


def test_the_manifest_parses_under_the_real_parser() -> None:
    manifest = parse_manifest(skill_text(), expected_name=SKILL_NAME)

    assert manifest.name == SKILL_NAME
    assert manifest.description.strip()
    assert len(manifest.description) <= MAX_DESCRIPTION_CHARS


def test_no_invented_top_level_frontmatter_field_is_used() -> None:
    front = skill_text().split("---")[1]
    top_level = {
        line.split(":", 1)[0].strip()
        for line in front.splitlines()
        if line.strip() and not line.startswith((" ", "\t", "#"))
    }
    assert not top_level & {"when_to_use", "tools", "version"}
    assert top_level <= {
        "name",
        "description",
        "license",
        "compatibility",
        "metadata",
        "allowed-tools",
    }


def test_the_manifest_declares_no_tools() -> None:
    """Procedure, not runtime authority: allowed-tools is advisory and grants
    nothing, so it is omitted rather than modelled with no effect."""
    assert parse_manifest(skill_text(), expected_name=SKILL_NAME).allowed_tools == ()


def test_the_skill_registers_alongside_the_existing_first_party_skill() -> None:
    names = registry().names()
    assert SKILL_NAME in names
    assert "testing" in names
    assert registry().errors == ()


def test_the_package_records_a_digest_and_its_provenance() -> None:
    package = registry().get(SKILL_NAME)

    assert len(package.body_digest) == 64
    assert package.trust_tier == TRUST_BUILTIN
    assert package.source_root == LIBRARY_DIR


def test_the_body_and_every_reference_stay_inside_their_bounds() -> None:
    package = registry().get(SKILL_NAME)

    assert not package.body_truncated
    assert len(package.body) < BOUNDS.max_skill_body_chars // 2
    assert package.references
    assert len(package.references) <= BOUNDS.max_skill_references
    for content in package.references.values():
        assert not content.truncated
        assert content.chars <= BOUNDS.max_skill_reference_chars


def test_the_skill_ships_no_scripts_and_no_assets() -> None:
    package = registry().get(SKILL_NAME)

    assert package.scripts == ()
    assert package.assets == ()
    assert not (skill_dir() / "scripts").exists()
    assert not (skill_dir() / "assets").exists()


# -- content: the procedure this skill claims --------------------------------


def test_the_description_names_the_procedure_and_when_to_use_it() -> None:
    description = parse_manifest(skill_text(), expected_name=SKILL_NAME).description.lower()

    assert "refactor" in description
    assert "behaviour" in description or "behavior" in description
    assert "use when" in description


def test_the_when_to_use_extension_is_present_and_distinct() -> None:
    manifest = parse_manifest(skill_text(), expected_name=SKILL_NAME)

    assert manifest.metadata["agentgate.when_to_use"].strip()
    assert manifest.when_to_use != manifest.description


def test_behaviour_preservation_is_the_stated_first_rule() -> None:
    lowered = flat(skill_text())
    assert "a refactor changes structure, not behaviour" in lowered


def test_dependency_mapping_precedes_editing() -> None:
    lowered = flat(skill_text())
    assert "map before you touch anything" in lowered
    for term in ("repo_graph", "find_symbol", "find_references", "find_dependents"):
        assert term in lowered


def test_semgrep_findings_are_named_as_advisory_only() -> None:
    lowered = flat(skill_text())
    assert "analyze_code" in lowered
    assert "advisory" in lowered


def test_the_testing_skill_is_the_named_validation_procedure() -> None:
    lowered = flat(skill_text())
    assert "testing` skill" in lowered or "testing' skill" in lowered
    assert "detect_tests" in lowered


def test_the_five_review_dimensions_are_all_present() -> None:
    lowered = flat(skill_text())
    for term in ("coupling", "duplication", "layering", "dead code", "oversized"):
        assert term in lowered


def test_small_reversible_change_and_interface_preservation_are_stated() -> None:
    lowered = flat(skill_text())
    assert "small, reversible steps" in lowered or "small reversible steps" in lowered
    assert "preserve public interfaces" in lowered


def test_facts_and_suggestions_are_explicitly_separated() -> None:
    lowered = flat(skill_text())
    assert "observed fact" in lowered
    assert "suggestion" in lowered


# -- safety: what the prose may not say --------------------------------------

RISKY = ("delete", "skip", "xfail", "deselect", "weaken", "disable", "silence", "loosen")
NEGATIONS = ("never", "not ", "n't", "do not", "rather than", "instead of", "avoid", "refus")

FORBIDDEN = (
    "verdict.gate",
    "severity threshold",
    "judge prompt",
    "benchmark fixture",
    "eval dataset",
    "--no-verify",
    "shell=true",
    "os.system",
)


def blocks(text: str) -> list[str]:
    return [block for block in re.split(r"\n\s*\n", text) if block.strip()]


def test_every_risky_act_named_is_also_refused() -> None:
    offending: list[str] = []
    for filename, text in all_authored_text().items():
        for block in blocks(text):
            lowered = block.lower()
            if not any(term in lowered for term in RISKY):
                continue
            if not any(marker in lowered for marker in NEGATIONS):
                offending.append(f"{filename}: " + " ".join(block.split())[:160])
    assert not offending, "a block names a test-weakening act without refusing it:\n" + "\n".join(
        offending
    )


def test_no_forbidden_phrase_appears() -> None:
    for filename, text in all_authored_text().items():
        lowered = text.lower()
        found = [phrase for phrase in FORBIDDEN if phrase in lowered]
        assert not found, f"{filename} names {found}, which this skill must not steer"


def test_the_skill_never_endorses_weakening_a_test_to_get_green() -> None:
    lowered = flat(skill_text())
    assert "never weaken, delete, or skip a test" in lowered


def test_the_skill_names_no_absolute_path_or_secret() -> None:
    for filename, text in all_authored_text().items():
        assert "C:\\" not in text, filename
        assert not re.search(r"(?m)^\s*/(home|Users|etc)/", text), filename
        assert "API_KEY" not in text and "SECRET" not in text.upper().replace(
            "SECRETS", ""
        ), filename


def test_the_skill_states_it_grants_no_authority() -> None:
    lowered = flat(skill_text())
    assert "grants no authority beyond" in lowered


# -- authority: loading it changes nothing ------------------------------------


def test_loading_the_skill_does_not_change_the_tool_registry() -> None:
    before = dict(TOOL_REGISTRY)
    bundle = build_capabilities(include_builtin_skills=True)

    SkillLoader(bundle.registry).load(SKILL_NAME)  # type: ignore[arg-type]

    assert dict(TOOL_REGISTRY) == before
    assert set(bundle.tools) == {"load_skill"}


def test_loading_the_skill_does_not_change_a_policy_decision() -> None:
    """The skill names tools by their function. It grants none of them."""
    bundle = build_capabilities(include_builtin_skills=True)
    SkillLoader(bundle.registry).load(SKILL_NAME)  # type: ignore[arg-type]

    with pytest.raises(CommandDenied):
        DEFAULT_POLICY.check(["npm", "test"])
    with pytest.raises(CommandDenied):
        DEFAULT_POLICY.check(["curl", "https://example.com"])
    assert DEFAULT_POLICY.check(["python", "-m", "pytest", "-q"])


# -- progressive disclosure ----------------------------------------------------


def test_the_catalogue_shows_metadata_and_never_the_body() -> None:
    catalogue = build_capabilities(include_builtin_skills=True).catalogue
    package = registry().get(SKILL_NAME)

    assert SKILL_NAME in catalogue
    assert package.manifest.when_to_use[:40] in catalogue
    assert "a refactor changes structure" not in catalogue
    assert package.body[:80] not in catalogue


def test_no_reference_content_reaches_the_catalogue() -> None:
    catalogue = build_capabilities(include_builtin_skills=True).catalogue
    for name, text in reference_texts().items():
        assert name not in catalogue
        assert text.strip().splitlines()[0] not in catalogue


def test_the_body_arrives_only_on_an_explicit_load() -> None:
    loader = SkillLoader(registry())

    loaded = loader.load(SKILL_NAME)
    assert "a refactor changes structure" in flat(loaded.body)
    assert loaded.reference is None


def test_a_reference_arrives_only_on_an_explicit_reference_load() -> None:
    loader = SkillLoader(registry())
    body = loader.load(SKILL_NAME).body
    assert "the five queries" not in flat(body)

    reference = loader.load(SKILL_NAME, reference="dependency-mapping.md")
    assert "the five queries" in flat(reference.body)


# -- packaging -----------------------------------------------------------------


def test_the_declared_glob_covers_every_authored_file_in_this_skill() -> None:
    import tomllib

    config = tomllib.loads(
        (LIBRARY_DIR.parents[2] / "pyproject.toml").read_text(encoding="utf-8")
    )
    patterns = config["tool"]["setuptools"]["package-data"]["engine.skill_library"]

    matched = {
        p.relative_to(LIBRARY_DIR).as_posix() for pat in patterns for p in LIBRARY_DIR.glob(pat)
    }
    authored = {
        p.relative_to(skill_dir()).as_posix()
        for p in skill_dir().rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    }
    matched_for_skill = {
        m[len(f"{SKILL_NAME}/") :] for m in matched if m.startswith(f"{SKILL_NAME}/")
    }

    assert authored, "no authored skill files found"
    assert authored <= matched_for_skill, f"package-data misses {sorted(authored - matched_for_skill)}"
