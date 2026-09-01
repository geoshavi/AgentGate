"""Refactoring Agent limit presets.

No new limit *fields* -- every bound this agent needs already exists on
``codeagent.limits.Limits``, enforced by the components that own them. What
differs is the settings, the same way ``debugagent.limits.DEBUG_LIMITS`` is a
preset rather than a new mechanism.
"""

from dataclasses import replace

from engine.codeagent.limits import DEFAULT_LIMITS, Limits

REFACTOR_LIMITS: Limits = replace(
    DEFAULT_LIMITS,
    # A refactor maps dependencies -- repo_graph queries, detect_tests,
    # analyze_code -- before it edits anything, so it spends more turns and
    # tool calls on evidence than the Coding Agent's default budgets for
    # before the first write.
    max_turns=35,
    max_tool_calls=30,
    # "Prefer small, reversible changes" is an instruction a model can ignore;
    # ``Workspace.note_changed`` raising past this is not. Higher than the
    # Debug Agent's 3 (a fix touching four files is a refactor, not a fix) --
    # a blast-radius-aware rename can legitimately touch a definition and
    # several call sites -- but well under the generic default of 20, which
    # would let a "refactor" become an unbounded rewrite.
    max_files_changed=10,
    # Unchanged from the default, restated because it is load-bearing here:
    # AgentGate's own verification-driven repair, shared with every other
    # agent that reuses run_verified_session.
    max_repair_rounds=2,
)

__all__ = ["REFACTOR_LIMITS"]
