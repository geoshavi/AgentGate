"""Offline test support for the capabilities suites.

Not named ``test_*`` so pytest does not collect it. Builds skill trees on disk so
the tests exercise the real snapshot path -- there is no in-memory shortcut into
``SkillRegistry``, because the property under test is precisely *when* the bytes
are read.

Pure test infrastructure: nothing under ``src/`` imports this, and nothing here
reaches a network, a provider SDK, or an API key.
"""

from pathlib import Path

MINIMAL = "A skill used for testing the capabilities layer."


def frontmatter(name: str, description: str = MINIMAL, **extra: str) -> str:
    """The two required Agent Skills fields, plus raw extra lines verbatim."""
    lines = [f"name: {name}", f"description: {description}"]
    lines += [f"{key.replace('_', '-')}: {value}" for key, value in extra.items()]
    return "\n".join(lines)


def write_skill(
    root: Path,
    name: str,
    *,
    front: str | None = None,
    body: str = "# Heading\n\nProcedure text.\n",
    references: dict[str, str] | None = None,
    assets: dict[str, str] | None = None,
    scripts: dict[str, str] | None = None,
    raw: str | None = None,
) -> Path:
    """Create one skill directory. ``raw`` writes SKILL.md verbatim, delimiters
    included, so a test can express malformed front matter."""
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    if raw is None:
        head = frontmatter(name) if front is None else front
        raw = f"---\n{head}\n---\n\n{body}"
    (skill_dir / "SKILL.md").write_text(raw, encoding="utf-8")

    for sub, files in (("references", references), ("assets", assets), ("scripts", scripts)):
        if not files:
            continue
        (skill_dir / sub).mkdir(exist_ok=True)
        for filename, content in files.items():
            (skill_dir / sub / filename).write_text(content, encoding="utf-8")
    return skill_dir
