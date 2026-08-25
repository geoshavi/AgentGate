"""Deterministic, model-free detection of a workspace's test environment.

The contract is one sentence: the same tree and the same policy callback produce
the same value, every time. Everything below serves that -- a fixed candidate
list rather than a repository walk, sorted iteration, bounded reads, and explicit
precedence with no tie-breaking by chance.

**It never guesses.** Ambiguous evidence yields UNKNOWN with empty argv, because
the consumer of a wrong answer is a command someone runs, and a wrong suite is
worse than no suite. Two explicit configurations from different ecosystems are
ambiguity, not a race to be resolved by ordering.

**It never decides policy.** Whether the suite it names may actually run is the
caller's command policy's answer, injected as ``permits``. The detector does not
know that ``npm`` is currently refused, which is exactly why widening that policy
in a later reviewed phase needs no change here.

**It never runs anything.** No subprocess, no import of workspace code, no
mutation. Reading is bounded by file count and by bytes, screened by
``capabilities/paths.py``, and confined to known configuration and layout
signals -- never arbitrary source, never a credential-shaped name, never a
dependency or build directory.
"""

import configparser
import json
import tomllib
from collections.abc import Callable
from pathlib import Path

from engine.capabilities.paths import contained, is_denied_name, is_noise_dir
from engine.capabilities.testenv.models import TestConfidence, TestEnvironment

# Approved bounds (blueprint §9). Ceilings, not targets.
MAX_TESTENV_FILES_READ = 8
MAX_TESTENV_FILE_BYTES = 32_000

# The repository's existing canonical invocation, reused rather than reinvented:
# the same argv appears in codeagent/tools/shell.py, codeagent/plan.py,
# debugagent/app.py and verification/automated.py. A second convention here would
# mean a detected suite and a run suite could disagree.
PYTEST_SUITE_ARGV: tuple[str, ...] = ("python", "-m", "pytest", "-q")
TARGET_SLOT = "{target}"
PYTEST_TARGETED_TEMPLATE: tuple[str, ...] = (*PYTEST_SUITE_ARGV, TARGET_SLOT)

# Metadata only. Whether this may run is the policy callback's answer, and under
# the Coding Agent's current policy it is not -- see the module docstring.
NPM_SUITE_ARGV: tuple[str, ...] = ("npm", "test")

NO_SUITE = "no runnable suite detected"

# argv -> None when allowed, or a refusal reason.
Permits = Callable[[tuple[str, ...]], str | None]

_JS_RUNNERS = ("jest", "vitest", "playwright")
_TEST_DIR_NAMES = ("tests", "test")


def detect(
    root: Path,
    *,
    permits: Permits,
    max_files: int = MAX_TESTENV_FILES_READ,
    max_bytes: int = MAX_TESTENV_FILE_BYTES,
    on_read: Callable[[str], None] | None = None,
) -> TestEnvironment:
    """Inspect ``root`` and report what test framework it uses.

    ``permits`` decides executability and is required: defaulting it would mean a
    caller could silently get a permissive answer, and "may this run" is not a
    question this module is entitled to answer.

    ``on_read`` is an optional observer for tests, called with each relative path
    actually read. Production callers never pass it.

    Never raises for an unusable tree: a missing root, an unreadable file or a
    malformed config all become UNKNOWN with the failure recorded as evidence.
    """
    reader = _Reader(root, max_files=max_files, max_bytes=max_bytes, on_read=on_read)
    if not root.is_dir():
        return _unknown(("root: not an existing directory",), permits)

    python = _detect_python(reader)
    javascript = _detect_javascript(reader)
    evidence = tuple(reader.failures) + python.evidence + javascript.evidence

    winner = _resolve(python, javascript)
    if winner is None:
        return _unknown(evidence, permits)
    return _finish(winner, evidence, permits)


# -- candidate signals -------------------------------------------------------


class _Signal:
    """One ecosystem's finding: a framework, a confidence, and why."""

    __slots__ = ("confidence", "evidence", "framework", "suite_argv", "targeted")

    def __init__(
        self,
        framework: str | None = None,
        confidence: TestConfidence = TestConfidence.UNKNOWN,
        evidence: tuple[str, ...] = (),
        suite_argv: tuple[str, ...] = (),
        targeted: tuple[str, ...] = (),
    ) -> None:
        self.framework = framework
        self.confidence = confidence
        self.evidence = evidence
        self.suite_argv = suite_argv
        self.targeted = targeted

    @property
    def certain(self) -> bool:
        return self.confidence is TestConfidence.CERTAIN

    @property
    def found(self) -> bool:
        return self.framework is not None


def _detect_python(reader: "_Reader") -> _Signal:
    """pytest signals, strongest first.

    Each CERTAIN signal is an explicit, *structurally valid* configuration --
    the section must actually parse and be present. A file that merely exists
    with the right name proves nothing, which is why ``tox.ini`` without a
    ``[pytest]`` section does not count.
    """
    evidence: list[str] = []
    certain: list[str] = []

    data = reader.toml("pyproject.toml")
    if data is not None:
        tool = data.get("tool")
        if isinstance(tool, dict) and "pytest" in tool:
            certain.append("pyproject.toml [tool.pytest.ini_options]")
        elif _pyproject_declares_pytest(data):
            evidence.append("pyproject.toml declares a pytest dependency")

    for filename, sections in (
        ("pytest.ini", ("pytest",)),
        ("tox.ini", ("pytest",)),
        ("setup.cfg", ("tool:pytest",)),
    ):
        parsed = reader.ini(filename)
        if parsed is None:
            continue
        for section in sections:
            if parsed.has_section(section):
                certain.append(f"{filename} [{section}]")

    if certain:
        return _Signal(
            framework="pytest",
            confidence=TestConfidence.CERTAIN,
            evidence=tuple(sorted(certain)),
            suite_argv=PYTEST_SUITE_ARGV,
            targeted=PYTEST_TARGETED_TEMPLATE,
        )

    layout = _python_test_layout(reader)
    if layout is not None:
        evidence.append(layout)
    if evidence:
        return _Signal(
            framework="pytest",
            confidence=TestConfidence.LIKELY,
            evidence=tuple(sorted(evidence)),
            suite_argv=PYTEST_SUITE_ARGV,
            targeted=PYTEST_TARGETED_TEMPLATE,
        )
    return _Signal()


def _pyproject_declares_pytest(data: dict[str, object]) -> bool:
    """pytest named in project dependencies, optional groups, or dependency-groups.

    Matched on the distribution name only -- ``pytest>=8.0`` and ``pytest``
    both count, ``pytest-mock`` does not, because a plugin implies its host is
    present but says nothing about this project's own suite.
    """
    for requirement in _iter_requirements(data):
        if _distribution_name(requirement) == "pytest":
            return True
    return False


def _iter_requirements(data: dict[str, object]) -> list[str]:
    out: list[str] = []
    project = data.get("project")
    if isinstance(project, dict):
        deps = project.get("dependencies")
        if isinstance(deps, list):
            out += [item for item in deps if isinstance(item, str)]
        optional = project.get("optional-dependencies")
        if isinstance(optional, dict):
            for group in optional.values():
                if isinstance(group, list):
                    out += [item for item in group if isinstance(item, str)]
    groups = data.get("dependency-groups")
    if isinstance(groups, dict):
        for group in groups.values():
            if isinstance(group, list):
                out += [item for item in group if isinstance(item, str)]
    return out


def _distribution_name(requirement: str) -> str:
    """The bare distribution name from a PEP 508 requirement string."""
    name = requirement.strip()
    for separator in ("[", "<", ">", "=", "!", "~", ";", " ", "@"):
        name = name.split(separator)[0]
    return name.strip().casefold()


def _python_test_layout(reader: "_Reader") -> str | None:
    """A conventional ``tests/`` directory holding at least one test module.

    Directory listing only -- no file is read -- so this costs nothing against
    the read budget. Deliberately requires the directory: one ``test_scratch.py``
    at the repository root is a scratch file, not a suite.
    """
    for directory in _TEST_DIR_NAMES:
        names = reader.listdir(directory)
        for name in names:
            if name.startswith("test_") and name.endswith(".py"):
                return f"{directory}/ contains {name}"
            if name.endswith("_test.py"):
                return f"{directory}/ contains {name}"
    return None


def _detect_javascript(reader: "_Reader") -> _Signal:
    """jest / vitest / playwright signals.

    Reported with the same rigour as pytest and with a representative argv, but
    whether that argv may run is decided later by ``permits`` -- nothing here
    knows or asserts that it cannot.
    """
    certain: list[tuple[str, str]] = []
    likely: list[tuple[str, str]] = []

    for runner in _JS_RUNNERS:
        for suffix in (".js", ".ts", ".mjs", ".cjs"):
            filename = f"{runner}.config{suffix}"
            if reader.exists(filename):
                certain.append((runner, f"{filename} present"))

    package = reader.json("package.json")
    if isinstance(package, dict):
        scripts = package.get("scripts")
        if isinstance(scripts, dict):
            command = scripts.get("test")
            if isinstance(command, str):
                for runner in _JS_RUNNERS:
                    if runner in command.casefold():
                        certain.append((runner, f"package.json scripts.test runs {runner}"))
        for field in ("dependencies", "devDependencies"):
            declared = package.get(field)
            if isinstance(declared, dict):
                for runner in _JS_RUNNERS:
                    if runner in declared:
                        likely.append((runner, f"package.json {field} includes {runner}"))

    return _js_signal(certain, TestConfidence.CERTAIN) or _js_signal(
        likely, TestConfidence.LIKELY
    ) or _Signal()


def _js_signal(found: list[tuple[str, str]], confidence: TestConfidence) -> _Signal | None:
    """Collapse findings into one signal, or None.

    Two *different* JS runners at the same strength is ambiguity inside one
    ecosystem, and gets the same treatment as ambiguity between ecosystems: the
    evidence is kept, the framework is not claimed.
    """
    if not found:
        return None
    runners = {runner for runner, _ in found}
    evidence = tuple(sorted(reason for _, reason in found))
    if len(runners) > 1:
        return _Signal(evidence=evidence)
    return _Signal(
        framework=next(iter(runners)),
        confidence=confidence,
        evidence=evidence,
        suite_argv=NPM_SUITE_ARGV,
        targeted=NPM_SUITE_ARGV,
    )


def _resolve(python: _Signal, javascript: _Signal) -> _Signal | None:
    """Pick a winner, or refuse to.

    The documented precedence, and the whole of it:

      * exactly one ecosystem found anything      -> that one
      * exactly one has explicit configuration    -> that one, decisively
      * both have explicit configuration          -> ambiguous, no winner
      * both only weak signals                    -> ambiguous, no winner

    Precedence is justified only by explicit config; there is deliberately no
    "Python wins ties" rule, because that is a guess wearing a convention's
    clothes and it would be wrong in every polyglot repository.
    """
    if python.found and not javascript.found:
        return python
    if javascript.found and not python.found:
        return javascript
    if not python.found and not javascript.found:
        return None
    if python.certain and not javascript.certain:
        return python
    if javascript.certain and not python.certain:
        return javascript
    return None


def _finish(
    signal: _Signal, evidence: tuple[str, ...], permits: Permits
) -> TestEnvironment:
    """Ask the caller's policy whether the named suite may actually run."""
    reason = permits(signal.suite_argv)
    return TestEnvironment(
        framework=signal.framework,
        suite_argv=signal.suite_argv,
        targeted_template=signal.targeted,
        evidence=evidence,
        confidence=signal.confidence,
        executable=reason is None,
        blocked_reason=reason,
    )


def _unknown(evidence: tuple[str, ...], permits: Permits) -> TestEnvironment:
    """Nothing decisive. Empty argv, and a reason that says so.

    ``permits`` is not consulted: there is no argv to judge, and asking would
    invite a policy answer about the empty tuple to be read as a verdict about
    the workspace.
    """
    return TestEnvironment(
        evidence=evidence,
        confidence=TestConfidence.UNKNOWN,
        executable=False,
        blocked_reason=NO_SUITE,
    )


# -- bounded, screened reading -----------------------------------------------


class _Reader:
    """Reads only known candidates, only from ``root``, only within budget.

    Every failure is recorded as evidence rather than raised: an unparsable
    ``pyproject.toml`` is a fact about the workspace the caller should see, not
    an exception that ends a session.
    """

    def __init__(
        self,
        root: Path,
        *,
        max_files: int,
        max_bytes: int,
        on_read: Callable[[str], None] | None = None,
    ) -> None:
        self._root = root
        self._max_files = max_files
        self._max_bytes = max_bytes
        self._on_read = on_read
        self._reads = 0
        self.failures: tuple[str, ...] = ()

    def exists(self, name: str) -> bool:
        """Is ``name`` a screened, contained regular file? No read, no budget."""
        candidate = self._root / name
        if is_denied_name(name) or not candidate.is_file():
            return False
        return contained(self._root, candidate)

    def listdir(self, name: str) -> tuple[str, ...]:
        """Sorted file names directly inside ``name``. No read, no budget."""
        directory = self._root / name
        if is_noise_dir(name) or not directory.is_dir():
            return ()
        if not contained(self._root, directory):
            return ()
        try:
            return tuple(sorted(entry.name for entry in directory.iterdir() if entry.is_file()))
        except OSError:
            return ()

    def text(self, name: str) -> str | None:
        """Bounded text of one candidate, or None.

        Reads at most ``max_bytes``. A truncated read can only *fail* to find a
        section, never invent one, so a bounded read degrades a CERTAIN verdict
        to UNKNOWN rather than to a wrong answer.
        """
        if self._reads >= self._max_files or not self.exists(name):
            return None
        path = self._root / name
        self._reads += 1
        if self._on_read is not None:
            self._on_read(name)
        try:
            with path.open("rb") as handle:
                raw = handle.read(self._max_bytes)
        except OSError as exc:
            self._note(f"{name}: unreadable ({type(exc).__name__})")
            return None
        return raw.decode("utf-8", errors="replace")

    def toml(self, name: str) -> dict[str, object] | None:
        source = self.text(name)
        if source is None:
            return None
        try:
            return tomllib.loads(source)
        except (tomllib.TOMLDecodeError, ValueError):
            self._note(f"{name}: unparsable TOML")
            return None

    def json(self, name: str) -> object | None:
        source = self.text(name)
        if source is None:
            return None
        try:
            return json.loads(source)
        except (json.JSONDecodeError, ValueError):
            self._note(f"{name}: unparsable JSON")
            return None

    def ini(self, name: str) -> configparser.RawConfigParser | None:
        source = self.text(name)
        if source is None:
            return None
        # Raw parser: interpolation would try to expand '%' in values that are
        # not ours to interpret, and this only ever asks which sections exist.
        parser = configparser.RawConfigParser()
        try:
            parser.read_string(source)
        except configparser.Error:
            self._note(f"{name}: unparsable INI")
            return None
        return parser

    def _note(self, failure: str) -> None:
        self.failures = (*self.failures, failure)


__all__ = [
    "MAX_TESTENV_FILES_READ",
    "MAX_TESTENV_FILE_BYTES",
    "NO_SUITE",
    "NPM_SUITE_ARGV",
    "PYTEST_SUITE_ARGV",
    "PYTEST_TARGETED_TEMPLATE",
    "TARGET_SLOT",
    "Permits",
    "detect",
]
