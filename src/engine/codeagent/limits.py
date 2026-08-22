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

    # Session loop (P2). Every one of these is terminal when reached -- see
    # session.py, where each maps to exactly one SessionStatus.
    #
    # max_tool_calls is deliberately lower than max_turns: a turn is one model
    # call, a tool call is one execution, and turns are also spent on parse
    # errors and the final response. Setting them equal would make one of the
    # two bounds unreachable, which is a bound that cannot be tested and
    # therefore is not really a bound.
    max_turns: int = 25
    max_tool_calls: int = 20
    max_parse_errors: int = 3
    max_consecutive_tool_failures: int = 3
    max_repeated_calls: int = 3
    session_timeout_seconds: float = 600.0
    # Output cap requested per model turn. Named separately from the budget's
    # own ceiling because BudgetController.check_before_call uses it as the
    # worst-case spend estimate before every call.
    turn_max_tokens: int = 4_000

    # Planning (P3). A plan is advisory context, so every bound here exists to
    # keep it small and cheap rather than to constrain what the loop may do.
    # max_plan_attempts is 2 because the blueprint allows exactly one retry:
    # the first attempt plus one more with the validation errors fed back.
    max_plan_attempts: int = 2
    max_plan_steps: int = 7
    max_plan_files: int = 10
    max_plan_validation_commands: int = 3
    max_plan_notes: int = 5  # assumptions and risks, each
    max_plan_text_chars: int = 500  # one goal, step, note or criterion
    max_plan_context_chars: int = 4_000  # repository listing handed to the planner
    plan_max_tokens: int = 1_200

    def as_dict(self) -> dict[str, object]:
        """Serializable form, for recording which limits a run executed under."""
        return dict(asdict(self))


DEFAULT_LIMITS = Limits()
