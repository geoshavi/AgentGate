import sys

import pytest

from engine.codeagent.policy import (
    DEFAULT_POLICY,
    CommandDenied,
    CommandPolicy,
    is_sensitive_env_name,
    scrub_env,
)

# -- allowlist --------------------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["python", "-m", "pytest", "-q"],
        ["python3", "-c", "print(1)"],
        ["pytest", "-q"],
        ["ruff", "check", "."],
        ["mypy", "--ignore-missing-imports", "."],
        ["git", "diff"],
        ["git", "diff", "--stat"],
        ["git", "status", "--porcelain"],
        ["git", "log", "-n", "5"],
        ["git", "rev-parse", "HEAD"],
        ["git", "ls-files"],
        ["git", "show"],
    ],
)
def test_allowed_commands_pass(argv: list[str]) -> None:
    assert DEFAULT_POLICY.check(argv)


@pytest.mark.parametrize(
    "argv",
    [
        ["bash", "-c", "ls"],
        ["sh", "-c", "ls"],
        ["node", "index.js"],
        ["npm", "install"],
        ["docker", "run", "x"],
        ["make", "build"],
        ["cargo", "build"],
    ],
)
def test_unallowlisted_programs_are_denied(argv: list[str]) -> None:
    with pytest.raises(CommandDenied, match="not allowed"):
        DEFAULT_POLICY.check(argv)


def test_python_is_normalized_to_the_running_interpreter() -> None:
    assert DEFAULT_POLICY.check(["python", "-V"])[0] == sys.executable
    assert DEFAULT_POLICY.check(["python3", "-V"])[0] == sys.executable


def test_non_python_programs_keep_their_bare_name() -> None:
    assert DEFAULT_POLICY.check(["git", "status"])[0] == "git"


def test_arguments_are_preserved_verbatim() -> None:
    assert DEFAULT_POLICY.check(["python", "-m", "pytest", "-q"])[1:] == ["-m", "pytest", "-q"]


# -- shell strings ----------------------------------------------------------


def test_shell_string_is_denied_not_iterated() -> None:
    with pytest.raises(CommandDenied, match="must be a list of strings"):
        DEFAULT_POLICY.check("git status")


def test_empty_and_malformed_argv_are_denied() -> None:
    with pytest.raises(CommandDenied):
        DEFAULT_POLICY.check([])
    with pytest.raises(CommandDenied):
        DEFAULT_POLICY.check(None)
    with pytest.raises(CommandDenied, match="must be a string"):
        DEFAULT_POLICY.check(["python", 3])


def test_program_path_in_argv0_is_denied() -> None:
    for argv0 in ("/tmp/evil/python", "..\\python", "C:\\evil\\python.exe", "./python"):
        with pytest.raises(CommandDenied, match="bare program name"):
            DEFAULT_POLICY.check([argv0, "-V"])


# -- destructive git --------------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["git", "push"],
        ["git", "push", "origin", "main"],
        ["git", "reset", "--hard"],
        ["git", "reset", "HEAD~1"],
        ["git", "clean", "-fd"],
        ["git", "checkout", "main"],
        ["git", "commit", "-m", "x"],
        ["git", "rebase", "main"],
        ["git", "merge", "main"],
        ["git", "tag", "v1"],
        ["git", "stash"],
        ["git", "add", "."],
        ["git", "-c", "core.hooksPath=/tmp", "status"],
    ],
)
def test_destructive_or_writing_git_is_denied(argv: list[str]) -> None:
    with pytest.raises(CommandDenied):
        DEFAULT_POLICY.check(argv)


def test_git_push_is_denied_by_name() -> None:
    with pytest.raises(CommandDenied, match="read-only git"):
        DEFAULT_POLICY.check(["git", "push"])


def test_git_requires_a_subcommand() -> None:
    with pytest.raises(CommandDenied, match="requires a subcommand"):
        DEFAULT_POLICY.check(["git"])


# -- dangerous arguments ----------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["python", "-m", "pip", "install", "requests"],
        ["python", "-m", "ensurepip"],
        ["pytest", "sudo"],
        ["python", "rm"],
        ["python", "curl"],
        ["python", "wget"],
    ],
)
def test_denied_program_names_as_arguments_are_refused(argv: list[str]) -> None:
    with pytest.raises(CommandDenied, match="may not run"):
        DEFAULT_POLICY.check(argv)


@pytest.mark.parametrize(
    "arg",
    ["--force", "-f", "--hard", "--no-verify", "-rf"],
)
def test_denied_flags_are_refused(arg: str) -> None:
    with pytest.raises(CommandDenied, match="not allowed"):
        DEFAULT_POLICY.check(["pytest", arg])


@pytest.mark.parametrize(
    "arg",
    ["a; rm -rf /", "a | tee x", "a && b", "a > out.txt", "a < in.txt", "`id`", "$(id)", "a\nb"],
)
def test_shell_metacharacters_are_refused(arg: str) -> None:
    with pytest.raises(CommandDenied, match="metacharacters"):
        DEFAULT_POLICY.check(["python", "-c", arg])


def test_parent_traversal_in_arguments_is_refused() -> None:
    with pytest.raises(CommandDenied, match=r"\.\."):
        DEFAULT_POLICY.check(["pytest", "../other_repo"])


@pytest.mark.parametrize(
    "arg",
    ["/etc/passwd", "\\\\server\\share", "C:\\Windows\\System32", "C:/Windows", "D:x"],
)
def test_absolute_path_arguments_are_refused(arg: str) -> None:
    with pytest.raises(CommandDenied, match="absolute path"):
        DEFAULT_POLICY.check(["pytest", arg])


def test_policy_is_configurable_without_touching_defaults() -> None:
    strict = CommandPolicy(allowed_programs=frozenset({"git"}), git_subcommands=frozenset({"status"}))
    assert strict.check(["git", "status"])
    with pytest.raises(CommandDenied):
        strict.check(["python", "-V"])
    with pytest.raises(CommandDenied):
        strict.check(["git", "diff"])
    # The module default is unchanged by the above.
    assert DEFAULT_POLICY.check(["python", "-V"])


# -- environment scrubbing --------------------------------------------------


def test_sensitive_variables_are_removed() -> None:
    base = {
        "ANTHROPIC_API_KEY": "sk-ant-secret",
        "OPENAI_API_KEY": "sk-secret",
        "GOOGLE_API_KEY": "goog-secret",
        "AWS_SECRET_ACCESS_KEY": "aws-secret",
        "AWS_SESSION_TOKEN": "aws-token",
        "GITHUB_TOKEN": "gh-secret",
        "MY_DB_PASSWORD": "hunter2",
        "SOME_CREDENTIAL": "x",
        "SSH_AUTH_SOCK": "/tmp/agent.sock",
        "PATH": "/usr/bin",
        "HOME": "/home/dev",
        "LANG": "en_US.UTF-8",
    }
    scrubbed = scrub_env(base)

    assert scrubbed == {"PATH": "/usr/bin", "HOME": "/home/dev", "LANG": "en_US.UTF-8"}
    assert not any("secret" in value for value in scrubbed.values())


def test_scrubbing_catches_unknown_provider_keys() -> None:
    scrubbed = scrub_env({"SOMEFUTUREPROVIDER_API_KEY": "x", "PATH": "/usr/bin"})
    assert "SOMEFUTUREPROVIDER_API_KEY" not in scrubbed


def test_scrub_env_defaults_to_the_real_environment() -> None:
    scrubbed = scrub_env()
    assert not any(is_sensitive_env_name(name) for name in scrubbed)


def test_variables_a_subprocess_needs_survive_scrubbing() -> None:
    for name in ("PATH", "SYSTEMROOT", "COMSPEC", "TEMP", "HOME", "LANG", "PYTHONPATH"):
        assert not is_sensitive_env_name(name), name


def test_scrubbing_does_not_mutate_the_input() -> None:
    base = {"ANTHROPIC_API_KEY": "x", "PATH": "/usr/bin"}
    scrub_env(base)
    assert base == {"ANTHROPIC_API_KEY": "x", "PATH": "/usr/bin"}
