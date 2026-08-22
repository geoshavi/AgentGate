"""The planning step: one bounded model call before the loop starts.

A plan is **advisory context, never a constraint**. Nothing downstream consults
it to decide whether a tool may run -- that is what P1's workspace and command
guards are for, and routing authority through a document the model wrote before
reading a single file would be putting the weakest link in charge. What a plan
buys is a shared statement of intent at turn 1 instead of turn 6.

Because it is advisory, the failure mode is mild by design: an unusable plan
does not stop the session, it just means the session runs without one. What the
failure must never do is disappear. ``PlanOutcome`` distinguishes three
outcomes, and every one of them is recorded:

    OK           a plan parsed and passed every structural check
    REJECTED     the model answered, but no attempt validated
    UNAVAILABLE  the call itself could not be made (provider or budget)

There is no fourth state where planning quietly did not happen.

**This module cannot execute anything.** It never imports the tool registry --
it is handed tool *names* as strings, purely to write them into the prompt. The
only P1 machinery it touches is ``Workspace.resolve`` and ``CommandPolicy.check``,
both of which are pure checks that refuse rather than act. So "no tool execution
during planning" is a structural property here, not a discipline to remember.

Validation is structural only, mirroring ``execution_plan.validate_execution_plan``
in the existing engine: it judges whether a plan is *safe and well-formed to
carry forward*, never whether it is a good plan. A planner that started grading
plan quality would be a second, unaccountable judge.
"""

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from engine.codeagent.limits import DEFAULT_LIMITS, Limits
from engine.codeagent.log import SessionLog
from engine.codeagent.policy import DEFAULT_POLICY, CommandDenied, CommandPolicy
from engine.codeagent.protocol import find_blocks
from engine.codeagent.workspace import Workspace, WorkspaceError
from engine.llm_types import Message
from engine.runtime.budget import BudgetController, BudgetExceededError
from engine.runtime.gateway import LLMGateway

AGENT_NAME = "CodingAgent.plan"


class PlanStatus(str, Enum):
    OK = "OK"
    REJECTED = "REJECTED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class Plan:
    """A validated plan. Only ``goal`` and ``steps`` are required.

    Everything else is optional because the model is allowed not to know yet --
    demanding a file list before any file has been read would just teach it to
    invent one. ``assumptions`` and ``risks`` are advisory notes: they are
    rendered into the session's opening context and nothing enforces them.
    """

    goal: str
    steps: list[str]
    assumptions: list[str] = field(default_factory=list)
    likely_files: list[str] = field(default_factory=list)
    validation_commands: list[list[str]] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    completion_criteria: str = ""

    def as_dict(self) -> dict[str, Any]:
        return dict(asdict(self))


@dataclass(frozen=True)
class PlanOutcome:
    status: PlanStatus
    plan: Plan | None = None
    attempts: int = 0
    errors: list[str] = field(default_factory=list)
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.status is PlanStatus.OK and self.plan is not None


# -- parsing ----------------------------------------------------------------


def parse_plan_block(text: str) -> tuple[dict[str, Any] | None, str | None]:
    """Extract the ```plan block's JSON object. Returns (payload, error)."""
    if not isinstance(text, str) or not text.strip():
        return None, "the response was empty; emit exactly one ```plan block"

    blocks = find_blocks(text, ("plan",))
    if not blocks:
        return None, "no ```plan block found; emit exactly one, opened at the start of a line"
    if len(blocks) > 1:
        return None, f"found {len(blocks)} ```plan blocks; emit exactly one"

    try:
        payload = json.loads(blocks[0][1])
    except json.JSONDecodeError as exc:
        return None, f"the ```plan block body is not valid JSON: {exc.msg} (line {exc.lineno})"

    if not isinstance(payload, dict):
        return None, f"the ```plan block body must be a JSON object, got {type(payload).__name__}"
    return payload, None


# -- validation -------------------------------------------------------------


def validate_plan(
    payload: dict[str, Any],
    *,
    workspace: Workspace,
    policy: CommandPolicy = DEFAULT_POLICY,
    limits: Limits = DEFAULT_LIMITS,
) -> tuple[Plan | None, list[str]]:
    """Structurally validate a parsed plan payload.

    Returns ``(plan, [])`` or ``(None, errors)``. Every error names the field
    and what would fix it, because the errors are handed straight back to the
    model as its one retry.

    Length caps normalize (truncate); everything else rejects. The line is
    drawn there deliberately: shortening an over-long sentence keeps what the
    model meant, whereas dropping a step from an over-long list, or picking one
    of two malformed commands, would be inventing intent. What is stored is
    exactly what is used, so a truncation is visible in the persisted plan.
    """
    errors: list[str] = []

    goal = _text_field(payload, "goal", limits, errors, required=True)
    steps = _steps(payload, limits, errors)
    assumptions = _notes(payload, "assumptions", limits, errors)
    risks = _notes(payload, "risks", limits, errors)
    likely_files = _likely_files(payload, workspace, limits, errors)
    commands = _validation_commands(payload, policy, limits, errors)
    criteria = _text_field(payload, "completion_criteria", limits, errors, required=False)

    if errors:
        return None, errors

    return (
        Plan(
            goal=goal,
            steps=steps,
            assumptions=assumptions,
            likely_files=likely_files,
            validation_commands=commands,
            risks=risks,
            completion_criteria=criteria,
        ),
        [],
    )


def _clip(value: str, limits: Limits) -> str:
    return " ".join(value.split())[: limits.max_plan_text_chars]


def _text_field(
    payload: dict[str, Any], key: str, limits: Limits, errors: list[str], *, required: bool
) -> str:
    value = payload.get(key, "")
    if value is None:
        value = ""
    if not isinstance(value, str):
        errors.append(f"'{key}' must be a string, got {type(value).__name__}")
        return ""
    cleaned = _clip(value, limits)
    if required and not cleaned:
        errors.append(f"'{key}' is required and must be a non-empty string")
    return cleaned


def _steps(payload: dict[str, Any], limits: Limits, errors: list[str]) -> list[str]:
    raw = payload.get("steps")
    if not isinstance(raw, list):
        errors.append(f"'steps' must be a list of strings, got {type(raw).__name__}")
        return []
    if not all(isinstance(item, str) for item in raw):
        errors.append("every entry in 'steps' must be a string")
        return []

    steps = [_clip(item, limits) for item in raw if item.strip()]
    if not steps:
        errors.append("'steps' must contain at least one non-empty step")
    elif len(steps) > limits.max_plan_steps:
        errors.append(
            f"'steps' has {len(steps)} entries, more than max_plan_steps "
            f"({limits.max_plan_steps}); plan at a coarser grain"
        )
    return steps


def _notes(payload: dict[str, Any], key: str, limits: Limits, errors: list[str]) -> list[str]:
    raw = payload.get(key, [])
    if raw is None:
        raw = []
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        errors.append(f"'{key}' must be a list of strings")
        return []
    notes = [_clip(item, limits) for item in raw if item.strip()]
    if len(notes) > limits.max_plan_notes:
        errors.append(f"'{key}' has {len(notes)} entries, more than max_plan_notes ({limits.max_plan_notes})")
    return notes


def _likely_files(
    payload: dict[str, Any], workspace: Workspace, limits: Limits, errors: list[str]
) -> list[str]:
    raw = payload.get("likely_files", [])
    if raw is None:
        raw = []
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        errors.append("'likely_files' must be a list of strings")
        return []

    paths = [item.strip() for item in raw if item.strip()]
    if len(paths) > limits.max_plan_files:
        errors.append(
            f"'likely_files' has {len(paths)} entries, more than max_plan_files "
            f"({limits.max_plan_files})"
        )
        return []

    accepted: list[str] = []
    for candidate in paths:
        try:
            # The same guard the tools use, so a path that could never be
            # opened is refused while it is still cheap to say so. resolve()
            # checks and refuses; it never reads or writes.
            resolved = workspace.resolve(candidate)
        except WorkspaceError as exc:
            # Type name included, matching tools/base.py:guarded. It is the
            # difference between "that path is outside the workspace" and "that
            # file is off limits", which call for different corrections.
            errors.append(
                f"'likely_files' entry {candidate!r} is not usable: "
                f"{type(exc).__name__}: {exc}"
            )
            continue
        accepted.append(workspace.relative(resolved))
    return accepted


def _validation_commands(
    payload: dict[str, Any], policy: CommandPolicy, limits: Limits, errors: list[str]
) -> list[list[str]]:
    raw = payload.get("validation_commands", [])
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        errors.append("'validation_commands' must be a list of argv lists")
        return []
    if len(raw) > limits.max_plan_validation_commands:
        errors.append(
            f"'validation_commands' has {len(raw)} entries, more than "
            f"max_plan_validation_commands ({limits.max_plan_validation_commands})"
        )
        return []

    commands: list[list[str]] = []
    for candidate in raw:
        if isinstance(candidate, str):
            errors.append(
                f"validation command {candidate!r} must be an argv list, not a shell string"
            )
            continue
        if not isinstance(candidate, list) or not all(isinstance(part, str) for part in candidate):
            errors.append("each validation command must be a list of strings")
            continue
        try:
            # Checked, never run. Catching `git push` here costs one planning
            # retry; catching it at turn 12 costs the whole session's budget.
            policy.check(candidate)
        except CommandDenied as exc:
            errors.append(f"validation command {candidate!r} is not allowed: {exc}")
            continue
        commands.append(list(candidate))
    return commands


# -- prompting --------------------------------------------------------------


def build_planner_prompt(tool_names: list[str], limits: Limits) -> str:
    """Generated rather than stored as a file, matching how P2 builds the turn
    system prompt: the advertised tool list is derived from what the caller
    actually registered, so it cannot name a tool that no longer exists.
    """
    return f"""You are planning a coding task before any file has been read.

Reply with exactly one fenced block and nothing after it:

```plan
{{"goal": "<one sentence>",
 "steps": ["<step>", ...],
 "assumptions": ["<assumption>", ...],
 "likely_files": ["<workspace-relative path>", ...],
 "validation_commands": [["python", "-m", "pytest", "-q"]],
 "risks": ["<risk>", ...],
 "completion_criteria": "<how you will know the task is done>"}}
```

Rules:
- 'goal' and 'steps' are required. Everything else may be omitted or empty.
- At most {limits.max_plan_steps} steps, {limits.max_plan_files} likely files,
  {limits.max_plan_validation_commands} validation commands, and
  {limits.max_plan_notes} assumptions or risks.
- Paths are workspace-relative. Absolute paths, '..' and credential files are
  refused.
- Validation commands are argv lists, never shell strings, and only these
  programs run: python, pytest, ruff, mypy, and read-only git.
- Do not guess file contents. You have not read anything yet; the plan is a
  starting direction, not a commitment.

Tools that will be available during execution: {", ".join(sorted(tool_names))}"""


def render_plan_context(outcome: PlanOutcome) -> str:
    """The plan as the session's opening context, or an explicit statement that
    there is no plan. Never silence: a session running without a plan should
    know it is, so it starts by looking rather than by assuming.
    """
    if not outcome.ok or outcome.plan is None:
        return (
            "PLAN: none.\n"
            f"Planning did not produce a usable plan ({outcome.status.value}: "
            f"{outcome.reason or 'no reason recorded'}).\n"
            "Proceed without one: inspect the workspace before changing anything, "
            "make the smallest change that satisfies the task, and verify it before "
            "you finish."
        )

    plan = outcome.plan
    lines = [f"PLAN\ngoal: {plan.goal}", "steps:"]
    lines += [f"  {i}. {step}" for i, step in enumerate(plan.steps, start=1)]
    if plan.likely_files:
        lines.append(f"likely files: {', '.join(plan.likely_files)}")
    if plan.validation_commands:
        rendered = "; ".join(" ".join(argv) for argv in plan.validation_commands)
        lines.append(f"validation: {rendered}")
    if plan.assumptions:
        lines.append(f"assumptions: {'; '.join(plan.assumptions)}")
    if plan.risks:
        lines.append(f"risks: {'; '.join(plan.risks)}")
    if plan.completion_criteria:
        lines.append(f"done when: {plan.completion_criteria}")
    lines.append(
        "This plan is a starting direction, not a constraint. Depart from it when what "
        "you read says otherwise."
    )
    return "\n".join(lines)


# -- the planning call ------------------------------------------------------


def make_plan(
    *,
    task_text: str,
    workspace: Workspace,
    gateway: LLMGateway,
    budget: BudgetController,
    model: str,
    task_id: str,
    tool_names: list[str],
    repo_context: str = "",
    run_id: int | None = None,
    conn: sqlite3.Connection | None = None,
    limits: Limits = DEFAULT_LIMITS,
    policy: CommandPolicy = DEFAULT_POLICY,
    log: SessionLog | None = None,
) -> PlanOutcome:
    """Ask for a plan, validate it, and retry once with the errors fed back.

    Never raises for an unusable plan: the caller gets a ``PlanOutcome`` whose
    status says what happened. A provider or budget failure is also returned
    rather than raised, because planning is optional and a session that can
    still run should not be killed by an optional step.
    """
    sink = log if log is not None else SessionLog()
    system = build_planner_prompt(tool_names, limits)
    messages = [
        Message(role="user", content=_render_request(task_text, repo_context, limits))
    ]
    errors: list[str] = []

    for attempt in range(1, limits.max_plan_attempts + 1):
        try:
            result = gateway.generate(
                budget=budget,
                messages=messages,
                model=model,
                system=system,
                max_tokens=limits.plan_max_tokens,
                agent_name=AGENT_NAME,
                conn=conn,
                run_id=run_id,
                task_id=task_id,
            )
        except BudgetExceededError as exc:
            return _unavailable(sink, attempt - 1, f"budget exhausted before planning: {exc}")
        except Exception as exc:  # noqa: BLE001 - planning is optional; it must not kill the session
            return _unavailable(
                sink, attempt - 1, f"planning call failed: {type(exc).__name__}: {exc}"
            )

        sink.emit(
            "plan_attempt",
            attempt,
            # Counts, never content -- the same rule the turn loop follows.
            text_chars=len(result.text),
            stop_reason=result.stop_reason,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )

        payload, parse_error = parse_plan_block(result.text)
        if parse_error is not None:
            errors = [parse_error]
        else:
            assert payload is not None
            plan, errors = validate_plan(
                payload, workspace=workspace, policy=policy, limits=limits
            )
            if plan is not None:
                sink.emit("plan_result", attempt, status=PlanStatus.OK.value, plan=plan.as_dict())
                return PlanOutcome(status=PlanStatus.OK, plan=plan, attempts=attempt, errors=[])

        sink.emit("plan_rejected", attempt, errors=errors, response_chars=len(result.text))
        if attempt < limits.max_plan_attempts:
            messages.append(Message(role="assistant", content=result.text))
            messages.append(Message(role="user", content=_render_errors(errors)))

    reason = f"no valid plan after {limits.max_plan_attempts} attempt(s)"
    sink.emit(
        "plan_result", limits.max_plan_attempts, status=PlanStatus.REJECTED.value, errors=errors
    )
    return PlanOutcome(
        status=PlanStatus.REJECTED,
        plan=None,
        attempts=limits.max_plan_attempts,
        errors=errors,
        reason=reason,
    )


def _unavailable(sink: SessionLog, attempts: int, reason: str) -> PlanOutcome:
    sink.emit("plan_result", attempts, status=PlanStatus.UNAVAILABLE.value, reason=reason)
    return PlanOutcome(
        status=PlanStatus.UNAVAILABLE, plan=None, attempts=attempts, errors=[reason], reason=reason
    )


def _render_request(task_text: str, repo_context: str, limits: Limits) -> str:
    parts = [f"TASK\n{task_text.strip()}"]
    if repo_context.strip():
        parts.append(
            "WORKSPACE (names and sizes only, no contents)\n"
            f"{repo_context.strip()[: limits.max_plan_context_chars]}"
        )
    parts.append("Produce the plan.")
    return "\n\n".join(parts)


def _render_errors(errors: list[str]) -> str:
    listed = "\n".join(f"- {error}" for error in errors)
    return (
        "PLAN REJECTED\nThe plan did not validate:\n"
        f"{listed}\n"
        "Emit one corrected ```plan block. This is the last attempt."
    )
