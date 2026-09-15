"""Architecture Review Agent limit presets.

No new limit *fields* -- every bound this agent needs already exists on
``codeagent.limits.Limits``, enforced by the components that own them. What
differs is the settings, the same preset-not-mechanism pattern
``debugagent.limits.DEBUG_LIMITS``, ``refactoragent.limits.REFACTOR_LIMITS``,
``testqaagent.limits.QA_LIMITS`` and ``securityagent.limits.SECURITY_LIMITS``
already establish.
"""

from dataclasses import replace

from engine.codeagent.limits import DEFAULT_LIMITS, Limits

ARCHITECTURE_LIMITS: Limits = replace(
    DEFAULT_LIMITS,
    # repo_graph is this agent's primary evidence source (the task's own
    # framing), and surveying module boundaries, layering and dependency
    # direction across a repository takes more queries than reviewing one
    # file's security properties does -- more turns and tool calls than even
    # the Security Agent's own preset.
    max_turns=45,
    max_tool_calls=40,
    # Structural, not a nudge: this agent's tool set has no write_file, no
    # replace_exact and no run_command (see architectureagent/app.py), so
    # nothing in a session could ever change a file. max_files_changed=0
    # makes the same guarantee a second way -- Workspace.note_changed raises
    # before a first write could land, even if a future tool set change
    # reintroduced one by accident.
    max_files_changed=0,
    # Unchanged from the default, restated because it is load-bearing here:
    # AgentGate's own verification-driven repair, shared with every other
    # agent that reuses run_verified_session. In practice a review session
    # changes no files, so verification is declined and no repair round is
    # ever reached -- the same honest outcome the Security Agent's own
    # preset documents.
    max_repair_rounds=2,
)

__all__ = ["ARCHITECTURE_LIMITS"]
