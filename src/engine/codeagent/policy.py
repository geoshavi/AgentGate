"""Command execution policy: what the agent is allowed to run, and with what
environment.

Structured argv only. ``run_command`` never accepts a shell string and the
executor never passes ``shell=True``, because a shell is what turns a bad
argument into arbitrary code execution. A ``str`` argv is refused explicitly
rather than being allowed to iterate into a list of characters, which is the
classic way this guard is defeated by accident.

Honest scope, repeated from the blueprint because it matters more here than
anywhere else: this is a policy layer, not a sandbox. There is no container,
no seccomp filter, no namespace. An allowlisted ``python`` running a script
the agent just wrote can reach the network or the wider filesystem. What this
module actually buys is a narrow argv surface (no ``curl``, no ``pip``, no
shell), a forced working directory, a bounded runtime, and a child
environment with the credentials worth stealing removed. Claiming more than
that would be false.
"""

import os
import sys
from dataclasses import dataclass, field

# argv[0] values the agent may run. Kept to what the MVP's own gates need:
# the interpreter, the three automated gates, and git.
DEFAULT_ALLOWED_PROGRAMS = frozenset({"python", "python3", "pytest", "ruff", "mypy", "git"})

# Read-only git subcommands. Everything absent from this set is denied, which
# is what makes `push`, `reset`, `clean`, `checkout`, `commit`, `rebase`,
# `merge`, and `tag` unreachable without naming each one.
DEFAULT_GIT_SUBCOMMANDS = frozenset({"status", "diff", "log", "show", "ls-files", "rev-parse"})

# Flags refused anywhere in argv. `--hard` and `--force` are redundant with
# the git subcommand allowlist above and kept anyway: two independent reasons
# to refuse `reset --hard` is the right number for the operation this repo
# most wants to never happen.
DENIED_FLAGS = frozenset(
    {"--force", "-f", "--hard", "--no-verify", "--no-gpg-sign", "-rf", "-fr", "--delete", "-D"}
)

# Program names refused as *arguments*, which is what catches `python -m pip`
# and `python -m ensurepip` -- forms where the dangerous program never appears
# in argv[0].
DENIED_ARG_VALUES = frozenset(
    {
        "pip",
        "pip3",
        "ensurepip",
        "sudo",
        "rm",
        "rmdir",
        "del",
        "curl",
        "wget",
        "chmod",
        "chown",
        "ssh",
        "scp",
        "nc",
        "telnet",
        "venv",
    }
)

# Characters that only mean anything to a shell. Their presence signals the
# model believes it is writing a shell line, which is worth failing on even
# though ``shell=False`` makes them inert.
SHELL_METACHARACTERS = (";", "|", "&", ">", "<", "`", "$(", "\n")

# Environment variables removed from every child process. Exact names first,
# then the pattern rules that catch provider keys this list has not heard of.
SENSITIVE_ENV_EXACT = frozenset({"ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY"})
SENSITIVE_ENV_SUBSTRINGS = (
    "KEY",
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "PASSWD",
    "CREDENTIAL",
    "AUTH",
    "API",
)
SENSITIVE_ENV_PREFIXES = (
    "AWS_",
    "ANTHROPIC_",
    "OPENAI_",
    "GOOGLE_",
    "AZURE_",
    "GH_",
    "GITHUB_",
    "NPM_",
    "PYPI_",
)


class CommandDenied(Exception):
    """The command violates the policy and was not executed."""


def scrub_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """Return a copy of ``base`` (default ``os.environ``) with credential-shaped
    variables removed.

    Pattern-based rather than list-based on purpose: a new provider's key
    variable should be excluded the day it is introduced, not the day someone
    remembers to add it here. ``PATH``, ``SYSTEMROOT`` and the other variables
    a subprocess genuinely needs match none of these rules and survive.
    """
    source = dict(os.environ) if base is None else dict(base)
    return {k: v for k, v in source.items() if not is_sensitive_env_name(k)}


def is_sensitive_env_name(name: str) -> bool:
    upper = name.upper()
    if upper in SENSITIVE_ENV_EXACT:
        return True
    if upper.startswith(SENSITIVE_ENV_PREFIXES):
        return True
    return any(fragment in upper for fragment in SENSITIVE_ENV_SUBSTRINGS)


@dataclass(frozen=True)
class CommandPolicy:
    allowed_programs: frozenset[str] = field(default=DEFAULT_ALLOWED_PROGRAMS)
    git_subcommands: frozenset[str] = field(default=DEFAULT_GIT_SUBCOMMANDS)

    def check(self, argv: object) -> list[str]:
        """Validate ``argv`` and return the normalized form to execute.

        Normalization resolves ``python``/``python3`` to ``sys.executable`` so
        the agent runs the environment's own interpreter and cannot select a
        different one. Every other allowed program is left as a bare name for
        the OS to resolve on PATH.

        Raises:
            CommandDenied: for any violation. The message names the reason so
                it can be handed back to the model as a usable observation.
        """
        program = self._check_program(argv)
        # mypy: _check_program has established argv is a list[str].
        assert isinstance(argv, list)

        if program == "git":
            self._check_git(argv)

        for arg in argv[1:]:
            self._check_argument(arg)

        resolved = sys.executable if program in ("python", "python3") else program
        return [resolved, *argv[1:]]

    def _check_program(self, argv: object) -> str:
        if isinstance(argv, str):
            raise CommandDenied(
                "argv must be a list of strings, not a shell string; "
                f"pass ['git', 'status'] rather than {argv!r}"
            )
        if not isinstance(argv, list) or not argv:
            raise CommandDenied("argv must be a non-empty list of strings")
        if not all(isinstance(part, str) for part in argv):
            raise CommandDenied("every argv element must be a string")

        raw = argv[0]
        if "/" in raw or "\\" in raw or ":" in raw:
            # A path in argv[0] would let an allowlisted basename front for an
            # arbitrary binary ('/tmp/evil/python'), so only bare names pass.
            raise CommandDenied(f"argv[0] must be a bare program name, got {raw!r}")

        program = raw.casefold().removesuffix(".exe")
        if program not in self.allowed_programs:
            raise CommandDenied(
                f"program {raw!r} is not allowed; allowed: {sorted(self.allowed_programs)}"
            )
        return program

    def _check_git(self, argv: list[str]) -> None:
        if len(argv) < 2:
            raise CommandDenied("git requires a subcommand")
        subcommand = argv[1].casefold()
        if subcommand not in self.git_subcommands:
            raise CommandDenied(
                f"git subcommand {argv[1]!r} is not allowed; this agent may only run "
                f"read-only git: {sorted(self.git_subcommands)}"
            )

    def _check_argument(self, arg: str) -> None:
        lowered = arg.casefold()
        if lowered in DENIED_FLAGS:
            raise CommandDenied(f"flag {arg!r} is not allowed")
        if lowered in DENIED_ARG_VALUES:
            raise CommandDenied(f"argument {arg!r} names a program this agent may not run")
        if any(char in arg for char in SHELL_METACHARACTERS):
            raise CommandDenied(
                f"argument {arg!r} contains shell metacharacters; commands run without a shell"
            )
        if ".." in arg:
            raise CommandDenied(f"argument {arg!r} contains '..'; commands may not escape the workspace")
        if _looks_absolute(arg):
            raise CommandDenied(
                f"argument {arg!r} is an absolute path; commands run relative to the workspace"
            )


def _looks_absolute(arg: str) -> bool:
    if arg.startswith(("/", "\\")):
        return True
    # Windows drive-qualified forms: 'C:\\x', 'C:/x', and the drive-relative
    # 'C:x', all of which reach outside the forced working directory.
    return len(arg) >= 2 and arg[1] == ":" and arg[0].isalpha()


DEFAULT_POLICY = CommandPolicy()
