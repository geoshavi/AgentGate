"""Test/QA Agent limit presets.

No new limit *fields* -- every bound this agent needs already exists on
``codeagent.limits.Limits``, enforced by the components that own them. What
differs is the settings, the same preset-not-mechanism pattern
``debugagent.limits.DEBUG_LIMITS`` and ``refactoragent.limits.REFACTOR_LIMITS``
already establish.
"""

from dataclasses import replace

from engine.codeagent.limits import DEFAULT_LIMITS, Limits

QA_LIMITS: Limits = replace(
    DEFAULT_LIMITS,
    # Coverage work front-loads reading -- existing tests, detect_tests,
    # repo_graph queries to find what a candidate change would affect -- before
    # a single test is written, so it needs more turns and tool calls than the
    # Coding Agent's default before it can start writing.
    max_turns=35,
    max_tool_calls=30,
    # This agent's job is adding tests, not rewriting the system under test.
    # A handful of new or extended test files plus, rarely, one fixture is the
    # shape of "improves coverage without changing product behaviour"; more
    # than that is no longer a focused addition. Matches the Refactoring
    # Agent's ceiling for the same reason -- "focused" is a ceiling this
    # session enforces, not just an instruction a model can ignore.
    max_files_changed=8,
    # Unchanged from the default, restated because it is load-bearing here:
    # AgentGate's own verification-driven repair, shared with every other
    # agent that reuses run_verified_session.
    max_repair_rounds=2,
)

__all__ = ["QA_LIMITS"]
