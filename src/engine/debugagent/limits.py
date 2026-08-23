"""Debug Agent limit presets.

No new limit *fields* -- every bound the fix session needs already exists on
``codeagent.limits.Limits``, enforced by the components that own them. What
differs is the settings, so this module is a preset rather than a new mechanism.

The important one is ``max_files_changed``. "Prefer minimal fixes over broad
rewrites" is an instruction a model can ignore; ``Workspace.note_changed``
raising on the fourth file is not. Reusing the existing ceiling means the
constraint is enforced by the same object every mutation already passes through,
with no second control to keep in sync.
"""

from dataclasses import replace

from engine.codeagent.limits import DEFAULT_LIMITS, Limits

DEBUG_LIMITS: Limits = replace(
    DEFAULT_LIMITS,
    # A debug fix that touches four files is not a fix, it is a refactor.
    max_files_changed=3,
    # Debugging front-loads observation: more looking, less writing.
    max_turns=30,
    max_tool_calls=25,
    # Unchanged from the default, restated because it is load-bearing for D3:
    # two repair rounds, shared with any later verification-driven repair.
    max_repair_rounds=2,
)

__all__ = ["DEBUG_LIMITS"]
