"""Deterministic test-environment detection.

Model-free and read-only: given a workspace root and a command-policy callback,
it reports which test framework the evidence supports, which argv would represent
it, and whether that argv may actually run. It never executes anything, never
mutates, and never guesses -- ambiguous evidence yields UNKNOWN.

Import from here rather than from the modules below, so the internal split can
change without touching callers.
"""

from engine.capabilities.testenv.detect import (
    MAX_TESTENV_FILE_BYTES,
    MAX_TESTENV_FILES_READ,
    NO_SUITE,
    NPM_SUITE_ARGV,
    PYTEST_SUITE_ARGV,
    PYTEST_TARGETED_TEMPLATE,
    TARGET_SLOT,
    Permits,
    detect,
)
from engine.capabilities.testenv.models import TestConfidence, TestEnvironment

__all__ = [
    "MAX_TESTENV_FILES_READ",
    "MAX_TESTENV_FILE_BYTES",
    "NO_SUITE",
    "NPM_SUITE_ARGV",
    "PYTEST_SUITE_ARGV",
    "PYTEST_TARGETED_TEMPLATE",
    "TARGET_SLOT",
    "Permits",
    "TestConfidence",
    "TestEnvironment",
    "detect",
]
