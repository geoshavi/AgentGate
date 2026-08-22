"""Deterministic bounds for a Coding Agent session.

Every limit the agent can hit lives here as one frozen dataclass rather than
as module-level constants scattered across the tools that enforce them. The
reason is testability: a test that wants to prove truncation happens should
be able to construct ``Limits(max_read_bytes=10)`` instead of monkeypatching
a module global, and a future session needs to record the exact limits a run
executed under (see ``state.TaskState.limits``).

The defaults are round numbers chosen to be obviously safe, not measured
values. They are expected to move once real sessions exist; nothing in the
codebase depends on a particular number, only on the fact that one exists.
"""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Limits:
    # File reading. ``max_read_bytes`` bounds a single read_file call; a file
    # larger than this is returned truncated with the flag set, never
    # silently clipped.
    max_read_bytes: int = 64_000
    # Every tool's returned ``output`` is capped at this before the result is
    # handed back, so no single observation can dominate a future prompt.
    max_tool_output_bytes: int = 8_000

    # Directory listing and search.
    max_list_entries: int = 500
    max_list_depth: int = 3
    max_search_results: int = 50

    # Writing. ``max_write_bytes`` bounds a single write_file payload.
    # ``max_delete_bytes`` is the mass-deletion guard: a replace whose
    # replacement is empty and whose anchor is longer than this is refused,
    # as is any write that would truncate a non-empty file to empty.
    max_write_bytes: int = 64_000
    max_delete_bytes: int = 2_000
    # Ceiling on distinct files one session may modify. Enforced by
    # Workspace, which is the only component every mutation passes through.
    max_files_changed: int = 20

    # Command execution.
    command_timeout_seconds: float = 120.0

    def as_dict(self) -> dict[str, object]:
        """Serializable form, for recording which limits a run executed under."""
        return dict(asdict(self))


DEFAULT_LIMITS = Limits()
