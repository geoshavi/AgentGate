"""Bounded, advisory static analysis.

One analyser so far: Semgrep, run against the session's own workspace with the
ruleset the engine ships. The shape is the point -- ``semgrep`` holds a frozen
argv template so no config URL or registry entry is expressible, ``rules``
locates local YAML so no scan is a network fetch, and ``models`` fixes what a run
is allowed to claim: evidence, never a verdict.

**Nothing here executes anything.** There is exactly one place in this codebase
that spawns a child process (``codeagent/tools/shell.py``), and the model-facing
half of this capability goes through it, under the session's own
``CommandPolicy``. This package builds an argv and reads an output; it has no
subprocess, no shell and no timeout of its own.

A leaf, like the rest of ``capabilities/`` (architecture Rule H): no agent
package, no ``Tool``, no ``Workspace``, no ``CommandPolicy``, no provider SDK.
"""

from engine.capabilities.analysis.models import (
    SEVERITY_ORDER,
    AnalysisFinding,
    AnalysisRun,
)
from engine.capabilities.analysis.rules import (
    BUILTIN_RULE_PACKAGE,
    BUILTIN_RULESET,
    builtin_ruleset,
)
from engine.capabilities.analysis.semgrep import (
    DEFAULT_TARGET,
    MAX_FINDINGS,
    PROGRAM,
    build_argv,
    parse_output,
)

# The one operation this capability admits, named here rather than spelled as a
# literal at each call site.
ANALYZE_CODE = "analyze_code"

__all__ = [
    "ANALYZE_CODE",
    "BUILTIN_RULESET",
    "BUILTIN_RULE_PACKAGE",
    "DEFAULT_TARGET",
    "MAX_FINDINGS",
    "PROGRAM",
    "SEVERITY_ORDER",
    "AnalysisFinding",
    "AnalysisRun",
    "build_argv",
    "builtin_ruleset",
    "parse_output",
]
