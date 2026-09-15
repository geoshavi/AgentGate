"""Security Review Agent limit presets.

No new limit *fields* -- every bound this agent needs already exists on
``codeagent.limits.Limits``, enforced by the components that own them. What
differs is the settings, the same preset-not-mechanism pattern
``debugagent.limits.DEBUG_LIMITS``, ``refactoragent.limits.REFACTOR_LIMITS``
and ``testqaagent.limits.QA_LIMITS`` already establish.
"""

from dataclasses import replace

from engine.codeagent.limits import DEFAULT_LIMITS, Limits

SECURITY_LIMITS: Limits = replace(
    DEFAULT_LIMITS,
    # A review reads more and writes nothing, so it needs more turns and tool
    # calls than the Coding Agent's default budgets for before a session that
    # is doing its job would otherwise hit a ceiling meant for an editor.
    max_turns=40,
    max_tool_calls=35,
    # Structural, not a nudge: this agent's tool set has no write_file, no
    # replace_exact and no run_command (see securityagent/app.py), so nothing
    # in a session could ever change a file. max_files_changed=0 makes the
    # same guarantee a second way -- Workspace.note_changed raises before a
    # first write could land, even if a future tool set change reintroduced
    # one by accident.
    max_files_changed=0,
    # Unchanged from the default, restated because it is load-bearing here:
    # AgentGate's own verification-driven repair, shared with every other
    # agent that reuses run_verified_session. In practice a review session
    # changes no files, so verification is declined and no repair round is
    # ever reached -- this is what makes that the correct, honest outcome
    # rather than something to special-case.
    max_repair_rounds=2,
)

__all__ = ["SECURITY_LIMITS"]
