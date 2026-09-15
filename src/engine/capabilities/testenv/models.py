"""What test detection concluded, and what it is allowed to claim.

A value, not a decision. ``TestEnvironment`` says what evidence was found and
what argv would represent it; nothing here runs anything, and nothing downstream
is obliged to obey it. The Debug Agent's frozen reproduction and suite in
particular are settled before this value can exist.

Two fields carry the weight:

``confidence`` is computed by the harness from file evidence and is never
accepted from a model -- the rule ``debugagent/rootcause.py`` already applies to
its own confidence field.

``executable`` is not a property of the ecosystem. It is the verdict of the
caller's real command policy on ``suite_argv``, passed in as a callback, so the
detector cannot hardcode what may run and a later policy widening needs no change
here.
"""

from dataclasses import dataclass
from enum import Enum


class TestConfidence(Enum):
    """How much the evidence supports the framework named.

    CERTAIN  an explicit, structurally valid configuration names the framework
    LIKELY   a dependency or a conventional layout implies it
    UNKNOWN  nothing decisive, or two ecosystems disagree
    """

    # pytest collects any class named Test*; these are values, not suites. Not
    # annotated, so dataclass/Enum do not treat it as a member. Same technique as
    # codeagent.state.TestRun.
    __test__ = False

    CERTAIN = "CERTAIN"
    LIKELY = "LIKELY"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class TestEnvironment:
    """One detection result.

    Frozen and hashable so a caller can compare two runs directly -- which is how
    the determinism guarantee is tested rather than described.

    An UNKNOWN result carries empty argv deliberately: the alternative is a
    plausible command nobody verified, and a wrong suite frozen as a proof gate
    is worse than no suite at all.
    """

    __test__ = False

    framework: str | None = None
    suite_argv: tuple[str, ...] = ()
    targeted_template: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    confidence: TestConfidence = TestConfidence.UNKNOWN
    executable: bool = False
    blocked_reason: str | None = None

    @property
    def detected(self) -> bool:
        return self.framework is not None

    def as_dict(self) -> dict[str, object]:
        """Serializable form for a report. Evidence is a list of short source
        descriptions -- file names and section names -- never file contents."""
        return {
            "framework": self.framework,
            "confidence": self.confidence.value,
            "executable": self.executable,
            "suite_argv": list(self.suite_argv),
            "targeted_template": list(self.targeted_template),
            "evidence": list(self.evidence),
            "blocked_reason": self.blocked_reason,
        }


__all__ = ["TestConfidence", "TestEnvironment"]
