"""C3: deterministic test-environment detection.

The detector is model-free and its whole contract is "same tree in, same value
out". These tests hold it to that, and to the two rules that keep it honest:

    it never guesses          -- ambiguous evidence yields UNKNOWN, because a
                                 wrong suite is worse than no suite
    it never decides policy   -- executability comes from an injected callback,
                                 so the detector cannot hardcode what may run

Offline throughout: a tree on disk and a callback. No model, no subprocess, no
network.
"""

from pathlib import Path

import pytest

from engine.capabilities.testenv import (
    MAX_TESTENV_FILES_READ,
    PYTEST_SUITE_ARGV,
    PYTEST_TARGETED_TEMPLATE,
    TARGET_SLOT,
    TestConfidence,
    TestEnvironment,
    detect,
)


def allow_all(argv: tuple[str, ...]) -> str | None:
    return None


def allow_python_only(argv: tuple[str, ...]) -> str | None:
    if argv and argv[0] in ("python", "python3"):
        return None
    return f"program {argv[0]!r} is not allowed" if argv else "empty argv"


def seed(root: Path, relative: str, content: str = "") -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def run(root: Path, permits=allow_python_only) -> TestEnvironment:  # type: ignore[no-untyped-def]
    return detect(root, permits=permits)


# -- pytest, CERTAIN ----------------------------------------------------------


def test_pyproject_pytest_ini_options_is_certain(tmp_path: Path) -> None:
    seed(tmp_path, "pyproject.toml", '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n')

    env = run(tmp_path)

    assert env.framework == "pytest"
    assert env.confidence is TestConfidence.CERTAIN
    assert any("pyproject.toml" in item for item in env.evidence)


def test_pytest_ini_is_certain(tmp_path: Path) -> None:
    seed(tmp_path, "pytest.ini", "[pytest]\naddopts = -q\n")

    env = run(tmp_path)

    assert env.framework == "pytest"
    assert env.confidence is TestConfidence.CERTAIN


def test_tox_ini_with_a_pytest_section_is_certain(tmp_path: Path) -> None:
    seed(tmp_path, "tox.ini", "[tox]\nenvlist = py311\n\n[pytest]\naddopts = -q\n")

    env = run(tmp_path)

    assert env.framework == "pytest"
    assert env.confidence is TestConfidence.CERTAIN


def test_setup_cfg_with_a_tool_pytest_section_is_certain(tmp_path: Path) -> None:
    seed(tmp_path, "setup.cfg", "[metadata]\nname = x\n\n[tool:pytest]\naddopts = -q\n")

    env = run(tmp_path)

    assert env.framework == "pytest"
    assert env.confidence is TestConfidence.CERTAIN


def test_a_tox_ini_without_pytest_config_is_not_certain(tmp_path: Path) -> None:
    seed(tmp_path, "tox.ini", "[tox]\nenvlist = py311\n")

    assert run(tmp_path).confidence is not TestConfidence.CERTAIN


# -- pytest, LIKELY -----------------------------------------------------------


def test_a_pytest_project_dependency_is_likely(tmp_path: Path) -> None:
    seed(tmp_path, "pyproject.toml", '[project]\nname = "x"\ndependencies = ["pytest>=8.0"]\n')

    env = run(tmp_path)

    assert env.framework == "pytest"
    assert env.confidence is TestConfidence.LIKELY


def test_a_pytest_dev_dependency_is_likely(tmp_path: Path) -> None:
    seed(
        tmp_path,
        "pyproject.toml",
        '[project]\nname = "x"\n\n[project.optional-dependencies]\ndev = ["pytest>=8.0"]\n',
    )

    assert run(tmp_path).confidence is TestConfidence.LIKELY


def test_a_conventional_tests_layout_is_likely(tmp_path: Path) -> None:
    seed(tmp_path, "tests/test_thing.py", "def test_x():\n    assert True\n")

    env = run(tmp_path)

    assert env.framework == "pytest"
    assert env.confidence is TestConfidence.LIKELY
    assert any("tests/" in item for item in env.evidence)


def test_the_trailing_test_suffix_layout_also_counts(tmp_path: Path) -> None:
    seed(tmp_path, "tests/thing_test.py", "def test_x():\n    assert True\n")

    assert run(tmp_path).confidence is TestConfidence.LIKELY


def test_explicit_config_outranks_a_weak_signal(tmp_path: Path) -> None:
    seed(tmp_path, "pytest.ini", "[pytest]\n")
    seed(tmp_path, "tests/test_thing.py", "def test_x(): ...\n")

    assert run(tmp_path).confidence is TestConfidence.CERTAIN


# -- negative -----------------------------------------------------------------


def test_a_lone_python_file_implies_nothing(tmp_path: Path) -> None:
    seed(tmp_path, "main.py", "print('hello')\n")

    env = run(tmp_path)

    assert env.framework is None
    assert env.confidence is TestConfidence.UNKNOWN
    assert env.suite_argv == ()


def test_an_unrelated_pyproject_implies_nothing(tmp_path: Path) -> None:
    seed(tmp_path, "pyproject.toml", '[project]\nname = "x"\ndependencies = ["requests"]\n')

    assert run(tmp_path).confidence is TestConfidence.UNKNOWN


def test_a_test_named_file_outside_a_tests_directory_implies_nothing(tmp_path: Path) -> None:
    """One conventionally-named file at the root is not a test layout."""
    seed(tmp_path, "test_scratch.py", "x = 1\n")

    assert run(tmp_path).confidence is TestConfidence.UNKNOWN


def test_an_empty_workspace_is_unknown(tmp_path: Path) -> None:
    env = run(tmp_path)

    assert env.framework is None
    assert env.confidence is TestConfidence.UNKNOWN
    assert env.suite_argv == ()
    assert env.targeted_template == ()
    assert env.executable is False
    assert env.blocked_reason is not None


# -- JS / TS ------------------------------------------------------------------


def test_package_json_test_script_naming_jest_is_certain(tmp_path: Path) -> None:
    seed(tmp_path, "package.json", '{"scripts": {"test": "jest --ci"}}')

    env = run(tmp_path)

    assert env.framework == "jest"
    assert env.confidence is TestConfidence.CERTAIN


def test_package_json_test_script_naming_vitest_is_certain(tmp_path: Path) -> None:
    seed(tmp_path, "package.json", '{"scripts": {"test": "vitest run"}}')

    assert run(tmp_path).framework == "vitest"


def test_package_json_test_script_naming_playwright_is_certain(tmp_path: Path) -> None:
    seed(tmp_path, "package.json", '{"scripts": {"test": "playwright test"}}')

    assert run(tmp_path).framework == "playwright"


def test_an_explicit_jest_config_is_certain(tmp_path: Path) -> None:
    seed(tmp_path, "jest.config.ts", "export default {};\n")

    env = run(tmp_path)

    assert env.framework == "jest"
    assert env.confidence is TestConfidence.CERTAIN


def test_an_explicit_vitest_config_is_certain(tmp_path: Path) -> None:
    seed(tmp_path, "vitest.config.js", "export default {};\n")

    assert run(tmp_path).framework == "vitest"


def test_a_dev_dependency_only_signal_is_likely(tmp_path: Path) -> None:
    seed(tmp_path, "package.json", '{"devDependencies": {"vitest": "^1.0.0"}}')

    env = run(tmp_path)

    assert env.framework == "vitest"
    assert env.confidence is TestConfidence.LIKELY


def test_a_js_suite_is_reported_but_not_executable_under_this_policy(tmp_path: Path) -> None:
    seed(tmp_path, "package.json", '{"scripts": {"test": "jest"}}')

    env = run(tmp_path)

    assert env.suite_argv == ("npm", "test")
    assert env.executable is False
    assert "npm" in (env.blocked_reason or "")


def test_the_detector_hardcodes_no_ecosystem_as_unrunnable(tmp_path: Path) -> None:
    """The same JS detection becomes executable the moment the policy allows it.

    This is the test that keeps `executable` honest: nothing in the detector
    knows that npm is currently refused, so widening CommandPolicy in a later
    reviewed phase needs no change here.
    """
    seed(tmp_path, "package.json", '{"scripts": {"test": "jest"}}')

    refused = detect(tmp_path, permits=allow_python_only)
    permitted = detect(tmp_path, permits=allow_all)

    assert refused.executable is False
    assert permitted.executable is True
    assert permitted.blocked_reason is None
    assert refused.framework == permitted.framework == "jest"


# -- conflict and ambiguity ---------------------------------------------------


def test_two_explicit_configs_are_ambiguous_rather_than_guessed(tmp_path: Path) -> None:
    seed(tmp_path, "pytest.ini", "[pytest]\n")
    seed(tmp_path, "package.json", '{"scripts": {"test": "jest"}}')

    env = run(tmp_path)

    assert env.framework is None
    assert env.confidence is TestConfidence.UNKNOWN
    assert env.suite_argv == ()
    assert "pytest" in " ".join(env.evidence)
    assert "jest" in " ".join(env.evidence)


def test_two_weak_signals_are_ambiguous(tmp_path: Path) -> None:
    seed(tmp_path, "tests/test_thing.py", "def test_x(): ...\n")
    seed(tmp_path, "package.json", '{"devDependencies": {"jest": "^29"}}')

    assert run(tmp_path).confidence is TestConfidence.UNKNOWN


def test_explicit_config_beats_a_weak_signal_from_the_other_ecosystem(tmp_path: Path) -> None:
    """Precedence is justified only by explicit config, and then it is decisive."""
    seed(tmp_path, "pytest.ini", "[pytest]\n")
    seed(tmp_path, "package.json", '{"devDependencies": {"jest": "^29"}}')

    env = run(tmp_path)

    assert env.framework == "pytest"
    assert env.confidence is TestConfidence.CERTAIN


# -- determinism --------------------------------------------------------------


def test_detection_is_repeatable(tmp_path: Path) -> None:
    seed(tmp_path, "pyproject.toml", '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n')
    seed(tmp_path, "tests/test_a.py", "def test_a(): ...\n")

    assert run(tmp_path) == run(tmp_path)


def test_evidence_order_is_deterministic(tmp_path: Path) -> None:
    seed(tmp_path, "pyproject.toml", "[tool.pytest.ini_options]\n")
    seed(tmp_path, "pytest.ini", "[pytest]\n")
    seed(tmp_path, "setup.cfg", "[tool:pytest]\n")

    assert run(tmp_path).evidence == run(tmp_path).evidence


def test_the_result_is_hashable_and_frozen(tmp_path: Path) -> None:
    seed(tmp_path, "pytest.ini", "[pytest]\n")
    env = run(tmp_path)

    assert hash(env)
    with pytest.raises((AttributeError, TypeError)):
        env.framework = "jest"  # type: ignore[misc]


# -- bounds and malformed input ----------------------------------------------


def test_malformed_toml_is_evidence_failure_not_a_crash(tmp_path: Path) -> None:
    seed(tmp_path, "pyproject.toml", "[tool.pytest.ini_options\nbroken = \n")

    env = run(tmp_path)

    assert env.confidence is TestConfidence.UNKNOWN
    assert any("unreadable" in item or "unparsable" in item for item in env.evidence)


def test_malformed_json_is_evidence_failure_not_a_crash(tmp_path: Path) -> None:
    seed(tmp_path, "package.json", "{not json at all")

    assert run(tmp_path).confidence is TestConfidence.UNKNOWN


def test_malformed_ini_is_evidence_failure_not_a_crash(tmp_path: Path) -> None:
    seed(tmp_path, "setup.cfg", "= = = not ini = = =\n")

    assert run(tmp_path).confidence is TestConfidence.UNKNOWN


def test_an_oversized_config_is_read_under_the_byte_bound(tmp_path: Path) -> None:
    """A truncated read cannot yield a CERTAIN verdict from a section it never
    saw, and must not raise."""
    seed(tmp_path, "pyproject.toml", "# padding\n" * 20_000 + "[tool.pytest.ini_options]\n")

    env = detect(tmp_path, permits=allow_python_only, max_bytes=500)

    assert isinstance(env, TestEnvironment)
    assert env.confidence is TestConfidence.UNKNOWN


def test_the_file_read_budget_is_respected(tmp_path: Path) -> None:
    for name in ("pyproject.toml", "pytest.ini", "tox.ini", "setup.cfg", "package.json"):
        seed(tmp_path, name, "")
    reads: list[str] = []

    detect(tmp_path, permits=allow_python_only, on_read=reads.append)

    assert len(reads) <= MAX_TESTENV_FILES_READ


def test_a_credential_shaped_file_is_never_read(tmp_path: Path) -> None:
    seed(tmp_path, ".env", "SECRET=1\n")
    seed(tmp_path, "pytest.ini", "[pytest]\n")
    reads: list[str] = []

    detect(tmp_path, permits=allow_python_only, on_read=reads.append)

    assert not any(".env" in name for name in reads)


def test_noise_directories_are_not_inspected(tmp_path: Path) -> None:
    seed(tmp_path, "node_modules/pkg/package.json", '{"scripts": {"test": "jest"}}')
    seed(tmp_path, ".venv/lib/pytest.ini", "[pytest]\n")

    assert run(tmp_path).confidence is TestConfidence.UNKNOWN


def test_a_missing_root_is_unknown_rather_than_an_error(tmp_path: Path) -> None:
    env = run(tmp_path / "absent")

    assert env.confidence is TestConfidence.UNKNOWN


def test_a_symlinked_config_escaping_the_root_is_ignored(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "real.ini").write_text("[pytest]\n", encoding="utf-8")
    root = tmp_path / "root"
    root.mkdir()
    try:
        (root / "pytest.ini").symlink_to(outside / "real.ini")
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation needs privileges on this platform")

    assert run(root).confidence is TestConfidence.UNKNOWN


# -- argv shape ---------------------------------------------------------------


def test_the_suite_argv_is_a_tuple_of_strings_never_a_shell_string(tmp_path: Path) -> None:
    seed(tmp_path, "pytest.ini", "[pytest]\n")

    env = run(tmp_path)

    assert isinstance(env.suite_argv, tuple)
    assert all(isinstance(part, str) for part in env.suite_argv)
    assert env.suite_argv == PYTEST_SUITE_ARGV


def test_the_targeted_template_carries_a_literal_slot(tmp_path: Path) -> None:
    seed(tmp_path, "pytest.ini", "[pytest]\n")

    env = run(tmp_path)

    assert env.targeted_template == PYTEST_TARGETED_TEMPLATE
    assert TARGET_SLOT in env.targeted_template


def test_the_detector_runs_no_subprocess(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import subprocess

    def explode(*args: object, **kwargs: object) -> None:
        raise AssertionError("the detector executed a command")

    monkeypatch.setattr(subprocess, "run", explode)
    monkeypatch.setattr(subprocess, "Popen", explode)
    seed(tmp_path, "pytest.ini", "[pytest]\n")

    assert run(tmp_path).framework == "pytest"


def test_the_detector_mutates_nothing(tmp_path: Path) -> None:
    seed(tmp_path, "pytest.ini", "[pytest]\n")
    before = sorted(p.name for p in tmp_path.rglob("*"))

    run(tmp_path)

    assert sorted(p.name for p in tmp_path.rglob("*")) == before
