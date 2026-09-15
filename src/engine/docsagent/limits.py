"""Documentation/Handover Agent limit presets.

No new limit *fields* -- every bound this agent needs already exists on
``codeagent.limits.Limits``. What differs is the settings, the same
preset-not-mechanism pattern every other C-suite agent's limits module
already establishes.
"""

from dataclasses import replace

from engine.codeagent.limits import DEFAULT_LIMITS, Limits

DOCS_LIMITS: Limits = replace(
    DEFAULT_LIMITS,
    # Inspecting code, repo_graph and existing docs before writing a word
    # takes more turns than the Coding Agent's default budgets for before
    # the first write -- the same reasoning REFACTOR_LIMITS and QA_LIMITS
    # already document for their own evidence-gathering.
    max_turns=35,
    max_tool_calls=30,
    # A handover task touches a README, a changelog, maybe an architecture
    # note -- a handful of files, not a rewrite of the documentation tree.
    # Structural, not just a nudge: write_file/replace_exact are themselves
    # scoped to documentation paths (docsagent/tools.py), so this is a second,
    # independent ceiling on the same property.
    max_files_changed=8,
    max_repair_rounds=2,
)

__all__ = ["DOCS_LIMITS"]
