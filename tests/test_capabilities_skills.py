"""C1: the Agent Skills core -- standard conformance, parsing safety, snapshot
immutability, reference safety, and root ordering.

Every test is offline: a skill tree on disk, a registry snapshot, and assertions
about what was read and what was refused. No model, no network, no API key.

The suite is organised by the property it protects, because that is how a
regression will be diagnosed:

    standard conformance   does a spec-conformant skill work, and are the
                           spec's own constraints enforced?
    YAML safety            what the parser refuses, and -- just as important --
                           what it must NOT refuse
    non-authority          a skill declaring tools gets no tools
    snapshot               content is fixed before the session and cannot move
    references             a key lookup, never a path
    roots                  deterministic order, first root wins
"""

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from capabilities_harness import frontmatter, write_skill

from engine.capabilities.errors import ManifestError, SkillError
from engine.capabilities.skills import (
    TRUST_BUILTIN,
    TRUST_OPERATOR,
    SkillBounds,
    SkillLoader,
    SkillPackage,
    SkillRegistry,
    SkillRoot,
)


def root_of(path: Path, tier: str = TRUST_BUILTIN, workspace: Path | None = None) -> SkillRoot:
    return SkillRoot.create(path, trust_tier=tier, workspace_root=workspace)


def snapshot(path: Path, *, bounds: SkillBounds | None = None) -> SkillRegistry:
    return SkillRegistry.snapshot([root_of(path)], bounds=bounds or SkillBounds())


# -- standard conformance ----------------------------------------------------


def test_a_minimal_standard_skill_is_discovered_advertised_and_loadable(tmp_path: Path) -> None:
    """The whole compatibility claim in one test: name + description, nothing
    else, no AgentGate extension."""
    write_skill(tmp_path, "testing", raw="---\nname: testing\ndescription: Does a thing.\n---\n\nBody.\n")

    registry = snapshot(tmp_path)

    assert registry.names() == ("testing",)
    assert "testing" in registry.advertise()
    assert SkillLoader(registry).load("testing").body.strip() == "Body."


def test_a_folded_multiline_description_parses(tmp_path: Path) -> None:
    write_skill(tmp_path, "testing", front="name: testing\ndescription: >-\n  first line\n  second line")

    manifest = snapshot(tmp_path).get("testing").manifest

    assert manifest.description == "first line second line"


def test_a_literal_multiline_description_parses(tmp_path: Path) -> None:
    write_skill(tmp_path, "testing", front="name: testing\ndescription: |-\n  first line\n  second line")

    manifest = snapshot(tmp_path).get("testing").manifest

    assert manifest.description == "first line\nsecond line"


def test_a_quoted_description_may_contain_a_colon_and_a_hash(tmp_path: Path) -> None:
    write_skill(tmp_path, "testing", front='name: testing\ndescription: "Use when: issue #42 appears"')

    manifest = snapshot(tmp_path).get("testing").manifest

    assert manifest.description == "Use when: issue #42 appears"


def test_a_comment_line_in_front_matter_is_ignored(tmp_path: Path) -> None:
    write_skill(tmp_path, "testing", front="# a comment\nname: testing\ndescription: Fine.")

    assert snapshot(tmp_path).get("testing").manifest.description == "Fine."


def test_the_metadata_map_and_the_agentgate_extension_are_read(tmp_path: Path) -> None:
    front = (
        "name: testing\ndescription: Does a thing.\n"
        "metadata:\n"
        "  agentgate.when_to_use: Before choosing tests.\n"
        '  version: "1.0"\n'
        "  author: someone"
    )
    write_skill(tmp_path, "testing", front=front)

    manifest = snapshot(tmp_path).get("testing").manifest

    assert manifest.when_to_use == "Before choosing tests."
    assert manifest.metadata["version"] == "1.0"
    assert manifest.metadata["author"] == "someone"


def test_metadata_scalars_are_stringified_rather_than_typed(tmp_path: Path) -> None:
    """The spec's metadata is a string->string map. An unquoted 1.0 is a float
    in YAML; storing it as one would make the report's shape depend on quoting."""
    write_skill(tmp_path, "testing", front="name: testing\ndescription: d\nmetadata:\n  version: 1.0")

    assert snapshot(tmp_path).get("testing").manifest.metadata["version"] == "1.0"


def test_when_to_use_falls_back_to_the_description(tmp_path: Path) -> None:
    write_skill(tmp_path, "testing")

    manifest = snapshot(tmp_path).get("testing").manifest

    assert manifest.when_to_use == manifest.description


def test_optional_standard_fields_are_recorded(tmp_path: Path) -> None:
    front = (
        "name: testing\ndescription: Does a thing.\n"
        "license: Apache-2.0\n"
        "compatibility: Requires git and python\n"
    )
    write_skill(tmp_path, "testing", front=front)

    manifest = snapshot(tmp_path).get("testing").manifest

    assert manifest.license == "Apache-2.0"
    assert manifest.compatibility == "Requires git and python"


def test_unknown_top_level_keys_are_ignored_not_rejected(tmp_path: Path) -> None:
    """Forward compatibility: a future spec field must not break today's reader."""
    write_skill(tmp_path, "testing", front="name: testing\ndescription: d\nsomething-new: value")

    assert snapshot(tmp_path).names() == ("testing",)


# -- name and description constraints ----------------------------------------


@pytest.mark.parametrize(
    "name",
    ["Testing", "-testing", "testing-", "test--ing", "test_ing", "test ing", "tésting"],
)
def test_names_violating_the_specification_are_refused(tmp_path: Path, name: str) -> None:
    (tmp_path / name).mkdir()
    (tmp_path / name / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: d\n---\n\nb\n", encoding="utf-8"
    )

    registry = snapshot(tmp_path)

    assert registry.names() == ()
    assert registry.errors


def test_a_name_of_sixty_four_characters_is_accepted(tmp_path: Path) -> None:
    name = "a" * 64
    write_skill(tmp_path, name)

    assert snapshot(tmp_path).names() == (name,)


def test_a_name_over_sixty_four_characters_is_refused(tmp_path: Path) -> None:
    write_skill(tmp_path, "a" * 65)

    assert snapshot(tmp_path).names() == ()


def test_a_name_that_differs_from_the_directory_is_refused(tmp_path: Path) -> None:
    write_skill(tmp_path, "testing", front=frontmatter("something-else"))

    registry = snapshot(tmp_path)

    assert registry.names() == ()
    assert any("directory" in e.reason for e in registry.errors)


def test_a_description_over_the_specification_limit_is_refused(tmp_path: Path) -> None:
    write_skill(tmp_path, "testing", front=f"name: testing\ndescription: {'x' * 1025}")

    assert snapshot(tmp_path).names() == ()


def test_an_empty_description_is_refused(tmp_path: Path) -> None:
    write_skill(tmp_path, "testing", front='name: testing\ndescription: ""')

    assert snapshot(tmp_path).names() == ()


def test_a_missing_required_field_is_refused(tmp_path: Path) -> None:
    write_skill(tmp_path, "testing", front="name: testing")

    assert snapshot(tmp_path).names() == ()


# -- YAML safety: what is refused --------------------------------------------


def test_a_yaml_anchor_is_refused(tmp_path: Path) -> None:
    """Structural refusal. safe_load still expands aliases, so a small document
    can expand without bound; anchors have no use in a flat scalar field set."""
    write_skill(tmp_path, "testing", front="name: testing\ndescription: d\ndefaults: &d\n  v: x")

    registry = snapshot(tmp_path)

    assert registry.names() == ()
    assert any("anchor" in e.reason for e in registry.errors)


def test_a_yaml_alias_is_refused(tmp_path: Path) -> None:
    front = "name: testing\ndescription: d\ndefaults: &d\n  v: x\ncopy: *d"
    write_skill(tmp_path, "testing", front=front)

    assert snapshot(tmp_path).names() == ()


def test_a_python_object_tag_is_refused(tmp_path: Path) -> None:
    front = 'name: testing\ndescription: d\nx: !!python/object/apply:os.system ["echo hi"]'
    write_skill(tmp_path, "testing", front=front)

    registry = snapshot(tmp_path)

    assert registry.names() == ()
    assert any("tag" in e.reason for e in registry.errors)


def test_a_single_bang_python_tag_is_refused(tmp_path: Path) -> None:
    write_skill(tmp_path, "testing", front="name: testing\ndescription: d\nx: !python/object:os.system {}")

    assert snapshot(tmp_path).names() == ()


def test_multiple_yaml_documents_are_refused_by_the_safety_check() -> None:
    """Asserted on ``assert_safe_yaml`` directly, because a second '---' inside a
    SKILL.md closes the front matter rather than starting a second document (see
    the test below). The guard still belongs on the function: it is what makes
    the parser safe for any caller, not only this one."""
    from engine.capabilities.skills.manifest import assert_safe_yaml

    with pytest.raises(ManifestError) as excinfo:
        assert_safe_yaml("name: testing\ndescription: d\n---\nname: other\n")

    assert "single YAML document" in str(excinfo.value)


def test_a_second_delimiter_ends_the_front_matter_rather_than_extending_it(
    tmp_path: Path,
) -> None:
    """The first closing '---' wins. Everything after it is body text, so a
    later 'name:' line is prose and cannot redefine the manifest."""
    write_skill(tmp_path, "testing", front="name: testing\ndescription: d\n---\nname: other")

    package = snapshot(tmp_path).get("testing")

    assert package.manifest.name == "testing"
    assert "name: other" in package.body


def test_malformed_yaml_is_refused(tmp_path: Path) -> None:
    write_skill(tmp_path, "testing", front="name: testing\ndescription: [unclosed")

    assert snapshot(tmp_path).names() == ()


def test_front_matter_that_is_not_a_mapping_is_refused(tmp_path: Path) -> None:
    write_skill(tmp_path, "testing", raw="---\n- one\n- two\n---\n\nbody\n")

    assert snapshot(tmp_path).names() == ()


def test_a_non_scalar_where_a_scalar_is_required_is_refused(tmp_path: Path) -> None:
    write_skill(tmp_path, "testing", front="name:\n  - a\n  - b\ndescription: d")

    assert snapshot(tmp_path).names() == ()


def test_a_missing_closing_delimiter_is_refused(tmp_path: Path) -> None:
    write_skill(tmp_path, "testing", raw="---\nname: testing\ndescription: d\n\nbody with no close\n")

    assert snapshot(tmp_path).names() == ()


def test_a_file_without_front_matter_is_refused(tmp_path: Path) -> None:
    write_skill(tmp_path, "testing", raw="# Just a heading\n\nNo front matter here.\n")

    assert snapshot(tmp_path).names() == ()


def test_front_matter_over_the_byte_ceiling_is_refused(tmp_path: Path) -> None:
    filler = "\n".join(f"key{i}: value" for i in range(2000))
    write_skill(tmp_path, "testing", front=f"name: testing\ndescription: d\n{filler}")

    registry = snapshot(tmp_path)

    assert registry.names() == ()
    assert any("8000" in e.reason or "front matter" in e.reason for e in registry.errors)


# -- YAML safety: what must NOT be refused -----------------------------------


@pytest.mark.parametrize(
    "description",
    [
        '"Research & development helper"',
        '"Match *.py files"',
        "R&D helper for teams",
        '"Globs: *.py, *.md and A&B"',
        '"100% & counting"',
    ],
)
def test_ampersands_and_asterisks_in_ordinary_text_are_accepted(
    tmp_path: Path, description: str
) -> None:
    """The refusal above is structural. Rejecting on the raw characters would
    break ordinary prose, which is the common case, not the attack."""
    write_skill(tmp_path, "testing", front=f"name: testing\ndescription: {description}")

    assert snapshot(tmp_path).names() == ("testing",)


# -- a skill grants nothing ---------------------------------------------------


def test_allowed_tools_is_recorded_and_grants_nothing(tmp_path: Path) -> None:
    """The spec calls this "pre-approved tools" and marks it experimental. Here a
    skill is a file inside the artifact under test, so it is advisory only."""
    write_skill(
        tmp_path, "testing", front="name: testing\ndescription: d\nallowed-tools: run_command Read"
    )

    package = snapshot(tmp_path).get("testing")

    assert package.manifest.allowed_tools == ("run_command", "Read")
    # The package is data. It exposes nothing that could create or permit a tool.
    assert not [attr for attr in dir(package) if "tool" in attr.lower() and attr != "manifest"]
    assert not hasattr(package.manifest, "grant")
    assert not hasattr(package, "grant")


def test_compatibility_is_recorded_and_never_acted_on(tmp_path: Path) -> None:
    front = "name: testing\ndescription: d\ncompatibility: Requires docker and network access"
    write_skill(tmp_path, "testing", front=front)

    package = snapshot(tmp_path).get("testing")

    assert "docker" in package.manifest.compatibility
    assert not hasattr(package, "install")
    assert not hasattr(package, "requirements")


def test_the_capabilities_package_imports_no_agent_module() -> None:
    """Rule H at runtime, in a clean interpreter.

    A subprocess rather than an in-process check, for two reasons. ``sys.modules``
    is shared across the pytest session, so an in-process assertion would only be
    measuring which other test file ran first. And this catches what the static
    scan in test_architecture.py structurally cannot: an import performed
    dynamically, which that module's own docstring records as its residual gap.
    """
    probe = (
        "import sys; import engine.capabilities.skills;"
        "leaked=[m for m in sys.modules if m.startswith(('engine.codeagent','engine.debugagent'))];"
        "print(','.join(sorted(leaked)))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=Path(__file__).resolve().parent.parent,
        check=False,  # the assertion below reports stderr, which is more useful
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "", f"importing capabilities pulled in {result.stdout.strip()}"


# -- snapshot immutability ----------------------------------------------------


def test_the_body_served_is_the_one_read_at_snapshot(tmp_path: Path) -> None:
    skill = write_skill(tmp_path, "testing", body="ORIGINAL\n")
    registry = snapshot(tmp_path)

    (skill / "SKILL.md").write_text(
        f"---\n{frontmatter('testing')}\n---\n\nREPLACED\n", encoding="utf-8"
    )

    assert "ORIGINAL" in SkillLoader(registry).load("testing").body
    assert "REPLACED" not in SkillLoader(registry).load("testing").body


def test_a_reference_served_is_the_one_read_at_snapshot(tmp_path: Path) -> None:
    skill = write_skill(tmp_path, "testing", references={"guide.md": "ORIGINAL REF\n"})
    registry = snapshot(tmp_path)

    (skill / "references" / "guide.md").write_text("REPLACED REF\n", encoding="utf-8")

    loaded = SkillLoader(registry).load("testing", reference="guide.md")
    assert "ORIGINAL REF" in loaded.body
    assert "REPLACED REF" not in loaded.body


def test_loading_survives_deletion_of_the_entire_source_tree(tmp_path: Path) -> None:
    """The strongest statement of the invariant: there is nothing left to read."""
    write_skill(tmp_path, "testing", body="BODY\n", references={"guide.md": "REF\n"})
    registry = snapshot(tmp_path)

    shutil.rmtree(tmp_path / "testing")

    loader = SkillLoader(registry)
    assert "BODY" in loader.load("testing").body
    assert "REF" in loader.load("testing", reference="guide.md").body


def fs_spy(monkeypatch, watched: Path) -> list[str]:  # type: ignore[no-untyped-def]
    """Record every filesystem touch aimed at ``watched``, without raising.

    A raising patch fires inside pytest's own traceback machinery when an
    unrelated test fails, which turns one failure into an INTERNALERROR. This
    records instead, and the test asserts the log is empty. Only paths under the
    skill root are watched: pytest, importlib and tmp_path legitimately touch
    other files while a test runs.
    """
    calls: list[str] = []
    target = watched.resolve()

    def watch(label: str, original):  # type: ignore[no-untyped-def]
        def wrapper(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            try:
                if Path(self).resolve().is_relative_to(target):
                    calls.append(f"{label}({self})")
            except (OSError, ValueError):
                pass
            return original(self, *args, **kwargs)

        return wrapper

    for label in ("read_text", "read_bytes", "open", "stat", "iterdir"):
        monkeypatch.setattr(Path, label, watch(label, getattr(Path, label)))
    return calls


def test_loading_performs_no_filesystem_access(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Belt and braces beside the deletion test: watch the root, then load."""
    write_skill(tmp_path, "testing", body="BODY", references={"guide.md": "REF"})
    registry = snapshot(tmp_path)

    calls = fs_spy(monkeypatch, tmp_path)
    loader = SkillLoader(registry)
    assert "BODY" in loader.load("testing").body
    assert "REF" in loader.load("testing", reference="guide.md").body

    assert calls == [], f"SkillLoader.load touched the filesystem: {calls}"


def test_the_registry_exposes_no_reload_api() -> None:
    for verb in ("reload", "refresh", "rescan", "reread", "update", "invalidate"):
        assert not hasattr(SkillRegistry, verb), f"SkillRegistry.{verb} must not exist"


def test_a_package_is_frozen_and_its_references_are_not_a_mutable_dict(tmp_path: Path) -> None:
    write_skill(tmp_path, "testing", references={"guide.md": "REF\n"})
    package = snapshot(tmp_path).get("testing")

    with pytest.raises((AttributeError, TypeError)):
        package.body = "rewritten"  # type: ignore[misc]
    with pytest.raises(TypeError):
        package.references["guide.md"] = None  # type: ignore[index]
    assert not isinstance(package.references, dict)


def test_the_digest_covers_the_source_as_read(tmp_path: Path) -> None:
    write_skill(tmp_path, "testing", body="BODY\n")

    package = snapshot(tmp_path).get("testing")

    expected = hashlib.sha256((tmp_path / "testing" / "SKILL.md").read_bytes()).hexdigest()
    assert package.body_digest == expected


def test_a_body_over_the_bound_is_truncated_and_flagged(tmp_path: Path) -> None:
    write_skill(tmp_path, "testing", body="x" * 500)

    package = snapshot(tmp_path, bounds=SkillBounds(max_skill_body_chars=100)).get("testing")

    assert package.body_truncated
    assert len(package.body) <= 100


def test_a_reference_over_the_bound_is_truncated_and_flagged(tmp_path: Path) -> None:
    write_skill(tmp_path, "testing", references={"guide.md": "y" * 500})

    bounds = SkillBounds(max_skill_reference_chars=100)
    reference = snapshot(tmp_path, bounds=bounds).get("testing").references["guide.md"]

    assert reference.truncated
    assert len(reference.text) <= 100


# -- reference safety ---------------------------------------------------------


def test_an_unknown_reference_key_is_refused_and_names_the_available_ones(tmp_path: Path) -> None:
    write_skill(tmp_path, "testing", references={"guide.md": "REF\n"})
    loader = SkillLoader(snapshot(tmp_path))

    with pytest.raises(SkillError) as excinfo:
        loader.load("testing", reference="absent.md")

    assert "guide.md" in str(excinfo.value)


@pytest.mark.parametrize(
    "key",
    [
        "../SKILL.md",
        "../../etc/passwd",
        "/etc/passwd",
        "C:/Windows/system.ini",
        "C:\\Windows\\system.ini",
        "nested/guide.md",
        "nested\\guide.md",
        ".",
        "",
    ],
)
def test_a_reference_key_that_is_a_path_is_refused(tmp_path: Path, key: str) -> None:
    """The model supplies a key into a mapping, never a path. These cannot be
    keys because nothing path-shaped was ever enumerated as one."""
    write_skill(tmp_path, "testing", references={"guide.md": "REF\n"})
    loader = SkillLoader(snapshot(tmp_path))

    with pytest.raises(SkillError):
        loader.load("testing", reference=key)


def test_a_nested_reference_file_is_not_enumerated(tmp_path: Path) -> None:
    skill = write_skill(tmp_path, "testing", references={"guide.md": "REF\n"})
    nested = skill / "references" / "deeper"
    nested.mkdir()
    (nested / "secret.md").write_text("NESTED\n", encoding="utf-8")

    package = snapshot(tmp_path).get("testing")

    assert tuple(package.references) == ("guide.md",)


def test_a_credential_shaped_reference_is_not_enumerated(tmp_path: Path) -> None:
    write_skill(tmp_path, "testing", references={"guide.md": "REF\n", ".env": "SECRET=1\n"})

    package = snapshot(tmp_path).get("testing")

    assert ".env" not in package.references


@pytest.mark.skipif(sys.platform == "win32", reason="symlink creation needs privileges on Windows")
def test_a_symlinked_reference_escaping_the_root_is_not_enumerated(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-secret.md"
    outside.write_text("OUTSIDE\n", encoding="utf-8")
    root = tmp_path / "roots"
    skill = write_skill(root, "testing", references={"guide.md": "REF\n"})
    (skill / "references" / "escape.md").symlink_to(outside)

    package = snapshot(root).get("testing")

    assert "escape.md" not in package.references


def test_a_reference_of_one_skill_is_unreachable_through_another(tmp_path: Path) -> None:
    write_skill(tmp_path, "alpha", references={"alpha-ref.md": "ALPHA\n"})
    write_skill(tmp_path, "beta", references={"beta-ref.md": "BETA\n"})
    loader = SkillLoader(snapshot(tmp_path))

    with pytest.raises(SkillError):
        loader.load("beta", reference="alpha-ref.md")


def test_references_beyond_the_bound_are_not_enumerated(tmp_path: Path) -> None:
    write_skill(tmp_path, "testing", references={f"r{i}.md": f"REF{i}\n" for i in range(9)})

    package = snapshot(tmp_path, bounds=SkillBounds(max_skill_references=3)).get("testing")

    assert len(package.references) == 3


# -- assets and scripts -------------------------------------------------------


def test_asset_and_script_names_are_recorded_but_never_read(tmp_path: Path) -> None:
    write_skill(
        tmp_path,
        "testing",
        assets={"template.md": "ASSET BODY"},
        scripts={"extract.py": "import os; os.system('echo pwned')"},
    )

    package = snapshot(tmp_path).get("testing")

    assert package.assets == ("template.md",)
    assert package.scripts == ("extract.py",)
    # Contents are nowhere in the package.
    serialized = repr(package)
    assert "ASSET BODY" not in serialized
    assert "os.system" not in serialized


def test_a_script_is_not_reachable_as_a_reference(tmp_path: Path) -> None:
    write_skill(tmp_path, "testing", scripts={"extract.py": "print('x')"})
    loader = SkillLoader(snapshot(tmp_path))

    with pytest.raises(SkillError):
        loader.load("testing", reference="extract.py")


def test_the_package_exposes_no_way_to_run_anything(tmp_path: Path) -> None:
    write_skill(tmp_path, "testing", scripts={"extract.py": "print('x')"})
    package = snapshot(tmp_path).get("testing")

    for verb in ("run", "execute", "exec", "invoke", "call"):
        assert not hasattr(package, verb)


# -- roots, ordering and shadowing --------------------------------------------


def test_a_builtin_root_wins_over_an_operator_duplicate(tmp_path: Path) -> None:
    builtin, operator = tmp_path / "builtin", tmp_path / "operator"
    write_skill(builtin, "testing", body="BUILTIN\n")
    write_skill(operator, "testing", body="OPERATOR\n")

    registry = SkillRegistry.snapshot(
        [root_of(builtin, TRUST_BUILTIN), root_of(operator, TRUST_OPERATOR)],
        bounds=SkillBounds(),
    )

    assert "BUILTIN" in registry.get("testing").body
    assert registry.get("testing").trust_tier == TRUST_BUILTIN


def test_shadowing_is_recorded_deterministically(tmp_path: Path) -> None:
    builtin, operator = tmp_path / "builtin", tmp_path / "operator"
    write_skill(builtin, "testing")
    write_skill(operator, "testing")

    registry = SkillRegistry.snapshot(
        [root_of(builtin, TRUST_BUILTIN), root_of(operator, TRUST_OPERATOR)],
        bounds=SkillBounds(),
    )

    assert len(registry.shadowed) == 1
    assert registry.shadowed[0].name == "testing"
    assert str(operator) in registry.shadowed[0].shadowed_root


def test_discovery_order_is_deterministic(tmp_path: Path) -> None:
    for name in ("zulu", "alpha", "mike"):
        write_skill(tmp_path, name)

    assert snapshot(tmp_path).names() == ("alpha", "mike", "zulu")


def test_a_malformed_skill_does_not_prevent_its_siblings(tmp_path: Path) -> None:
    write_skill(tmp_path, "good")
    write_skill(tmp_path, "bad", front="name: bad\ndescription: [unclosed")

    registry = snapshot(tmp_path)

    assert registry.names() == ("good",)
    assert len(registry.errors) == 1
    assert registry.errors[0].skill == "bad"


def test_a_directory_without_a_skill_file_is_skipped_silently(tmp_path: Path) -> None:
    (tmp_path / "not-a-skill").mkdir()
    write_skill(tmp_path, "good")

    registry = snapshot(tmp_path)

    assert registry.names() == ("good",)
    assert registry.errors == ()


def test_a_missing_root_is_an_error_not_a_crash(tmp_path: Path) -> None:
    with pytest.raises(SkillError):
        root_of(tmp_path / "absent")


def test_advertised_skills_are_capped(tmp_path: Path) -> None:
    for i in range(6):
        write_skill(tmp_path, f"skill-{i}")

    registry = snapshot(tmp_path, bounds=SkillBounds(max_advertised_skills=2))

    assert len(registry.names()) == 2


def test_the_catalogue_carries_metadata_only_never_the_body(tmp_path: Path) -> None:
    write_skill(tmp_path, "testing", body="SECRET BODY TEXT\n")

    catalogue = snapshot(tmp_path).advertise()

    assert "testing" in catalogue
    assert "SECRET BODY TEXT" not in catalogue


def test_the_catalogue_is_bounded(tmp_path: Path) -> None:
    for i in range(8):
        write_skill(tmp_path, f"skill-{i}", front=frontmatter(f"skill-{i}", "d" * 1000))

    catalogue = snapshot(tmp_path, bounds=SkillBounds(max_skills_catalogue_chars=300)).advertise()

    assert len(catalogue) <= 300


def test_an_empty_registry_advertises_nothing(tmp_path: Path) -> None:
    assert snapshot(tmp_path).advertise() == ""


# -- loader budgets -----------------------------------------------------------


def test_a_third_distinct_skill_load_is_refused(tmp_path: Path) -> None:
    for name in ("alpha", "beta", "gamma"):
        write_skill(tmp_path, name)
    loader = SkillLoader(snapshot(tmp_path), bounds=SkillBounds(max_loaded_skills=2))

    loader.load("alpha")
    loader.load("beta")
    with pytest.raises(SkillError) as excinfo:
        loader.load("gamma")

    assert "max_loaded_skills" in str(excinfo.value)


def test_reloading_a_loaded_skill_does_not_respend_the_bound(tmp_path: Path) -> None:
    for name in ("alpha", "beta"):
        write_skill(tmp_path, name)
    loader = SkillLoader(snapshot(tmp_path), bounds=SkillBounds(max_loaded_skills=2))

    loader.load("alpha")
    loader.load("alpha")
    loader.load("beta")

    assert loader.loaded_skills == ("alpha", "beta")


def test_reference_loads_are_bounded(tmp_path: Path) -> None:
    write_skill(tmp_path, "testing", references={f"r{i}.md": f"REF{i}" for i in range(4)})
    loader = SkillLoader(snapshot(tmp_path), bounds=SkillBounds(max_loaded_references=2))

    loader.load("testing", reference="r0.md")
    loader.load("testing", reference="r1.md")
    with pytest.raises(SkillError):
        loader.load("testing", reference="r2.md")


def test_loading_an_unadvertised_skill_is_refused(tmp_path: Path) -> None:
    write_skill(tmp_path, "testing")
    loader = SkillLoader(snapshot(tmp_path))

    with pytest.raises(SkillError) as excinfo:
        loader.load("nonexistent")

    assert "testing" in str(excinfo.value)


def test_parse_errors_are_manifest_errors(tmp_path: Path) -> None:
    from engine.capabilities.skills.manifest import parse_manifest

    with pytest.raises(ManifestError):
        parse_manifest("---\nnot: valid\n---\n\nbody\n", expected_name="testing")


def test_a_package_reports_its_provenance(tmp_path: Path) -> None:
    write_skill(tmp_path, "testing")

    package: SkillPackage = snapshot(tmp_path).get("testing")

    assert package.source_root == tmp_path.resolve()
    assert package.trust_tier == TRUST_BUILTIN
    assert package.overlaps_workspace is False
