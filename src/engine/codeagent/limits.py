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

    # Verification (P4). max_snapshot_bytes bounds the concatenated *.py
    # snapshot that verification/pipeline.py inlines into every judge prompt.
    # It is enforced by the caller because pipeline.py is on the measured path
    # and must not change: above this size the session refuses to verify at all
    # rather than verifying a truncated program, which would be a verdict about
    # code that does not exist.
    max_snapshot_bytes: int = 200_000
    max_repair_rounds: int = 2

    # Debug Agent (D1). The reproduction gate and the evidence it collects.
    #
    # repro_timeout_seconds is separate from command_timeout_seconds because a
    # reproduction is the one command whose *failure to finish* is a terminal
    # result for the whole run, not an observation the agent can react to.
    #
    # Traceback parsing reads the already-truncated output tails rather than the
    # raw streams, so max_repro_output_bytes bounds the parser's input too and
    # no separate "lines scanned" limit is needed.
    repro_timeout_seconds: float = 120.0
    max_repro_output_bytes: int = 8_000
    max_evidence_frames: int = 10
    max_referenced_files: int = 20
    # One exception message or summary. Model-free text, but it comes from a
    # child process, and an unbounded field in a report is how a log becomes a
    # transcript.
    max_evidence_text_chars: int = 500

    # Debug Agent (D2). Root-cause diagnosis: what the model may see, how much
    # it may say, and how many times it may try.
    #
    # max_rootcause_attempts is 2 for the same reason max_plan_attempts is: the
    # first attempt plus exactly one retry with the validation errors fed back.
    # A third attempt has never been the difference between a usable answer and
    # an unusable one; it is just a third bill.
    max_rootcause_attempts: int = 2
    # Evidence-first inspection. The diagnosing model sees the files the failure
    # actually named, not the repository -- these two bound that selection.
    max_inspected_files: int = 6
    max_inspect_file_bytes: int = 6_000
    max_debug_context_chars: int = 12_000
    # Bounded search expansion. Terms come from traceback function names, so
    # these bound how far a *symbol the failure named* may lead -- not how much
    # of the repository may be trawled. Setting max_search_terms to 0 disables
    # expansion entirely and leaves inspection purely traceback-driven.
    max_search_terms: int = 3
    max_searched_files: int = 3
    # One summary, mechanism, fix description or evidence reference.
    max_root_cause_text_chars: int = 800
    max_related_files: int = 5
    max_evidence_refs: int = 5
    # Named separately from max_plan_validation_commands: a plan's commands and
    # a root cause's are different claims about different things, and coupling
    # them would mean tuning one silently retunes the other.
    max_rootcause_validation_commands: int = 3
    rootcause_max_tokens: int = 1_500

    # Capabilities (C3). Test detection reads configuration only, so these bound
    # a small fixed candidate list rather than a repository walk. A truncated
    # read can only fail to find a section, never invent one, so the bound
    # degrades a CERTAIN verdict to UNKNOWN rather than to a wrong answer.
    max_testenv_files_read: int = 8
    max_testenv_file_bytes: int = 32_000

    # Repository graph (C10). A deterministic AST/import scan, bounded the same
    # way testenv detection is -- by file count and by bytes per file -- plus a
    # ceiling on how many matches one query may render, since a graph exists to
    # avoid reads and an unbounded answer would spend the budget it was meant
    # to save.
    max_graph_files_scanned: int = 3_000
    max_graph_file_bytes: int = 300_000
    max_graph_results: int = 30

    def as_dict(self) -> dict[str, object]:
        """Serializable form, for recording which limits a run executed under."""
        return dict(asdict(self))


DEFAULT_LIMITS = Limits()
