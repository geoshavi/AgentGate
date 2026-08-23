"""The structured root-cause hypothesis: the one thing only a model can supply.

D1 established that the harness owns every fact available to it. This module
applies the same rule one phase later. The model proposes a diagnosis; nothing
here believes it on its own say-so:

* ``primary_file`` must resolve, through the same ``Workspace`` guard the tools
  use, to a real file inside the workspace. A diagnosis pointing at a file that
  is not there is not a weak diagnosis, it is a rejected one.
* ``primary_line`` is bounds-checked against that file's actual length.
* ``related_files`` each face the same guard.
* ``validation_plan`` commands are policy-checked here, never run. Catching
  ``git push`` now costs one retry; catching it later costs a whole session.
* ``confidence`` is **computed, never accepted.** A model asserting OBSERVED for
  a file the traceback never mentioned gets INFERRED, because the traceback is
  a fact and the assertion is not.

What is deliberately *not* checked: whether the stated mechanism is true. No
code can determine that. It is stored as the agent's stated reasoning, labelled
by a confidence the harness derived, and the later fix gate is what actually
holds the line.

Nothing here persists model prose beyond the structured fields it validated.
A rejected attempt is logged as its errors and a character count, never as the
response body -- the same rule ``protocol.py`` and ``plan.py`` follow.
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
from engine.codeagent.state import SessionStatus
from engine.codeagent.workspace import Workspace, WorkspaceError
from engine.debugagent.context import DebugContext, build_context
from engine.debugagent.evidence import FailureEvidence
from engine.debugagent.repro import FrozenRepro
from engine.llm_types import Message
from engine.runtime.budget import BudgetController, BudgetExceededError
from engine.runtime.gateway import LLMGateway

AGENT_NAME = "DebugAgent.rootcause"

REQUIRED_TEXT_FIELDS = ("summary", "mechanism", "proposed_fix")


class Confidence(str, Enum):
    """How well the traceback corroborates the location the model named.

    Three levels, all derived from observable evidence:

    OBSERVED     the traceback names this file AND this line
    CORROBORATED the traceback names this file, at a different line
    INFERRED     the traceback does not name this file, or there is no traceback

    INFERRED is not a failure. A bug's cause often sits one frame above where it
    surfaced. It is a label saying the harness could not confirm the location,
    so a reader knows which claims rest on evidence and which rest on argument.
    """

    OBSERVED = "OBSERVED"
    CORROBORATED = "CORROBORATED"
    INFERRED = "INFERRED"


class DiagnosisStatus(str, Enum):
    OK = "OK"
    REJECTED = "REJECTED"  # attempts exhausted without a valid hypothesis
    UNAVAILABLE = "UNAVAILABLE"  # the call never produced an answer


@dataclass(frozen=True)
class RootCause:
    """A validated hypothesis. Every path in it has been checked to exist."""

    summary: str
    mechanism: str
    primary_file: str
    primary_line: int
    proposed_fix: str
    confidence: Confidence
    related_files: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    validation_plan: list[list[str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        payload = dict(asdict(self))
        payload["confidence"] = self.confidence.value
        return payload

    def location(self) -> str:
        return f"{self.primary_file}:{self.primary_line}"


@dataclass(frozen=True)
class DiagnosisOutcome:
    """What the diagnosis phase produced, and what it cost."""

    status: DiagnosisStatus
    root_cause: RootCause | None = None
    attempts: int = 0
    errors: list[str] = field(default_factory=list)
    reason: str = ""
    inspected_files: list[str] = field(default_factory=list)
    # Usage, totalled across every attempt rather than reported for the one
    # that happened to succeed: a diagnosis that needed a retry cost two calls,
    # and accounting that hides the first would understate what the run spent.
    #
    # model_calls counts gateway.generate *attempts*, incremented before each
    # invocation -- so a call that raised is counted, because it was still made.
    # The token fields count only what a GenerationResult actually returned, and
    # are never estimated for a failed call. The two can therefore disagree: one
    # attempt with zero tokens is a request that never came back, which is
    # exactly what a reader needs to be able to see.
    #
    # Every token field comes from GenerationResult, which the gateway already
    # populates. thinking_tokens is a COUNT -- the reasoning text itself is
    # never carried, per that dataclass's own rule. Zero means "not reported",
    # which is not the same claim as "no reasoning happened".
    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0

    @property
    def ok(self) -> bool:
        return self.status is DiagnosisStatus.OK and self.root_cause is not None

    @property
    def terminal_status(self) -> SessionStatus | None:
        """The status the run must end on, or None to continue.

        Both failure modes land on the same terminal status for the reason D1's
        gate does: the distinction informs a human, it does not give the loop a
        second way to proceed toward editing code.
        """
        return None if self.ok else SessionStatus.ABORTED_NO_ROOT_CAUSE


# -- parsing ----------------------------------------------------------------


def parse_rootcause_block(text: str) -> tuple[dict[str, Any] | None, str | None]:
    """Extract the ```rootcause block's JSON object. Returns (payload, error).

    Shares ``find_blocks`` with the turn parser and the planner so all three
    agree on what a block is; a fence inside a JSON string still cannot open one.
    """
    if not isinstance(text, str) or not text.strip():
        return None, "the response was empty; emit exactly one ```rootcause block"

    blocks = find_blocks(text, ("rootcause",))
    if not blocks:
        return None, (
            "no ```rootcause block found; emit exactly one, opened at the start of a line"
        )
    if len(blocks) > 1:
        return None, f"found {len(blocks)} ```rootcause blocks; emit exactly one"

    try:
        payload = json.loads(blocks[0][1])
    except json.JSONDecodeError as exc:
        return None, f"the ```rootcause block body is not valid JSON: {exc.msg} (line {exc.lineno})"

    if not isinstance(payload, dict):
        return None, (
            f"the ```rootcause block body must be a JSON object, got {type(payload).__name__}"
        )
    return payload, None


# -- validation -------------------------------------------------------------


def compute_confidence(
    primary_file: str, primary_line: int, evidence: FailureEvidence
) -> Confidence:
    """Derive the confidence label from the traceback, ignoring any claim.

    Deliberately a free function of observable inputs: it cannot read anything
    the model wrote, so there is no path by which a model-supplied value could
    influence it.
    """
    matching = [frame for frame in evidence.frames if frame.file == primary_file]
    if not matching:
        return Confidence.INFERRED
    if any(frame.line == primary_line for frame in matching):
        return Confidence.OBSERVED
    return Confidence.CORROBORATED


def validate_rootcause(
    payload: dict[str, Any],
    *,
    workspace: Workspace,
    evidence: FailureEvidence,
    policy: CommandPolicy = DEFAULT_POLICY,
    limits: Limits = DEFAULT_LIMITS,
) -> tuple[RootCause | None, list[str]]:
    """Validate a parsed payload. Returns ``(root_cause, [])`` or ``(None, errors)``.

    Length caps normalize; everything else rejects. That is the same line
    ``plan.py`` draws, and for the same reason: shortening a sentence keeps what
    the model meant, whereas dropping a bad path or picking one of two malformed
    commands would be inventing intent.
    """
    errors: list[str] = []

    texts = {
        key: _text(payload, key, limits, errors, required=True) for key in REQUIRED_TEXT_FIELDS
    }
    primary_file = _primary_file(payload, workspace, errors)
    primary_line = _primary_line(payload, workspace, primary_file, errors)
    related = _related_files(payload, workspace, primary_file, limits, errors)
    refs = _evidence_refs(payload, limits, errors)
    plan = _validation_plan(payload, policy, limits, errors)

    if errors:
        return None, errors

    assert primary_file is not None and primary_line is not None
    return (
        RootCause(
            summary=texts["summary"],
            mechanism=texts["mechanism"],
            proposed_fix=texts["proposed_fix"],
            primary_file=primary_file,
            primary_line=primary_line,
            # Computed here, from evidence, after everything else validated.
            # A 'confidence' key in the payload is never read.
            confidence=compute_confidence(primary_file, primary_line, evidence),
            related_files=related,
            evidence_refs=refs,
            validation_plan=plan,
        ),
        [],
    )


def _text(
    payload: dict[str, Any], key: str, limits: Limits, errors: list[str], *, required: bool
) -> str:
    value = payload.get(key, "")
    if value is None:
        value = ""
    if not isinstance(value, str):
        errors.append(f"'{key}' must be a string, got {type(value).__name__}")
        return ""
    cleaned = " ".join(value.split())[: limits.max_root_cause_text_chars]
    if required and not cleaned:
        errors.append(f"'{key}' is required and must be a non-empty string")
    return cleaned


def _existing_file(candidate: str, workspace: Workspace, field_name: str, errors: list[str]) -> str | None:
    """Resolve one model-supplied path, or record why it cannot be used."""
    try:
        resolved = workspace.resolve(candidate)
    except WorkspaceError as exc:
        errors.append(f"'{field_name}' {candidate!r} is not usable: {type(exc).__name__}: {exc}")
        return None
    if not resolved.is_file():
        errors.append(f"'{field_name}' {candidate!r} does not exist in the workspace")
        return None
    return workspace.relative(resolved)


def _primary_file(payload: dict[str, Any], workspace: Workspace, errors: list[str]) -> str | None:
    raw = payload.get("primary_file")
    if not isinstance(raw, str) or not raw.strip():
        errors.append("'primary_file' is required and must be a non-empty workspace-relative path")
        return None
    return _existing_file(raw.strip(), workspace, "primary_file", errors)


def _primary_line(
    payload: dict[str, Any], workspace: Workspace, primary_file: str | None, errors: list[str]
) -> int | None:
    raw = payload.get("primary_line")
    if isinstance(raw, bool) or not isinstance(raw, int):
        errors.append(f"'primary_line' must be an integer, got {type(raw).__name__}")
        return None
    if raw < 1:
        errors.append(f"'primary_line' must be >= 1, got {raw}")
        return None
    if primary_file is None:
        # The file already failed; a range check against nothing would only add
        # a second, confusing error for the same fault.
        return None

    total = _line_count(workspace, primary_file)
    if total is not None and raw > total:
        errors.append(
            f"'primary_line' {raw} is past the end of {primary_file}, which has {total} line(s)"
        )
        return None
    return raw


def _line_count(workspace: Workspace, relative: str) -> int | None:
    try:
        text = workspace.resolve(relative).read_text(encoding="utf-8", errors="replace")
    except (WorkspaceError, OSError):
        return None
    return len(text.splitlines())


def _related_files(
    payload: dict[str, Any],
    workspace: Workspace,
    primary_file: str | None,
    limits: Limits,
    errors: list[str],
) -> list[str]:
    raw = payload.get("related_files", [])
    if raw is None:
        raw = []
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        errors.append("'related_files' must be a list of workspace-relative paths")
        return []

    candidates = [item.strip() for item in raw if item.strip()]
    if len(candidates) > limits.max_related_files:
        errors.append(
            f"'related_files' has {len(candidates)} entries, more than max_related_files "
            f"({limits.max_related_files}); name only the files that matter"
        )
        return []

    accepted: list[str] = []
    for candidate in candidates:
        relative = _existing_file(candidate, workspace, "related_files", errors)
        if relative is None:
            continue
        # The primary file is already named; repeating it says nothing.
        if relative == primary_file or relative in accepted:
            continue
        accepted.append(relative)
    return accepted


def _evidence_refs(payload: dict[str, Any], limits: Limits, errors: list[str]) -> list[str]:
    raw = payload.get("evidence_refs", [])
    if raw is None:
        raw = []
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        errors.append("'evidence_refs' must be a list of strings")
        return []
    refs = [" ".join(item.split())[: limits.max_root_cause_text_chars] for item in raw if item.strip()]
    if len(refs) > limits.max_evidence_refs:
        errors.append(
            f"'evidence_refs' has {len(refs)} entries, more than max_evidence_refs "
            f"({limits.max_evidence_refs})"
        )
        return []
    return refs


def _validation_plan(
    payload: dict[str, Any], policy: CommandPolicy, limits: Limits, errors: list[str]
) -> list[list[str]]:
    raw = payload.get("validation_plan", [])
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        errors.append("'validation_plan' must be a list of argv lists")
        return []
    if len(raw) > limits.max_rootcause_validation_commands:
        errors.append(
            f"'validation_plan' has {len(raw)} entries, more than "
            f"max_rootcause_validation_commands ({limits.max_rootcause_validation_commands})"
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
            # Checked, never run. D2 forms a hypothesis; it executes nothing.
            policy.check(candidate)
        except CommandDenied as exc:
            errors.append(f"validation command {candidate!r} is not allowed: {exc}")
            continue
        commands.append(list(candidate))
    return commands


# -- prompting --------------------------------------------------------------


def build_diagnosis_prompt(limits: Limits) -> str:
    """The diagnosing system prompt.

    Generated rather than stored, matching the planner and turn prompts. It
    advertises no editing tool, because D2 has none to offer: the phase produces
    a hypothesis and nothing else.
    """
    return f"""You are diagnosing a reproduced software failure. You are NOT fixing it.

You have been given the failure's own evidence and the contents of the files
that failure referenced. Identify the root cause.

Reply with exactly one fenced block and nothing after it:

```rootcause
{{"summary": "<one sentence: what is actually wrong>",
 "mechanism": "<how that produces the observed failure>",
 "primary_file": "<workspace-relative path of the defect>",
 "primary_line": <line number in that file>,
 "related_files": ["<other file that matters>", ...],
 "evidence_refs": ["<observation from the evidence supporting this>", ...],
 "proposed_fix": "<the smallest change that addresses the cause>",
 "validation_plan": [["python", "-m", "pytest", "-q"]]}}
```

Rules:
- 'summary', 'mechanism', 'primary_file', 'primary_line' and 'proposed_fix' are
  required. The rest may be omitted or empty.
- 'primary_file' must be a real file shown to you, and 'primary_line' must be a
  real line in it. A path that does not exist is rejected outright.
- Name the cause, not the symptom. The line the traceback raised on is often
  not the line that is wrong.
- Prefer the smallest fix that addresses the cause. Do not propose a rewrite.
- At most {limits.max_related_files} related files and
  {limits.max_evidence_refs} evidence references.
- Validation commands are argv lists, never shell strings, and only these
  programs run: python, pytest, ruff, mypy, and read-only git.
- Do not include a 'confidence' field. It is computed from the traceback, and
  anything you supply is discarded.
- Change nothing. You have no editing tools in this phase."""


def render_request(task_text: str, repro: FrozenRepro, context: DebugContext) -> str:
    return "\n\n".join(
        [
            f"REPORTED BUG\n{task_text.strip()}",
            f"REPRODUCTION COMMAND (frozen)\n{repro.display()}",
            context.render(),
            "Diagnose the root cause.",
        ]
    )


def render_errors(errors: list[str], *, last: bool) -> str:
    listed = "\n".join(f"- {error}" for error in errors)
    closing = (
        "Emit one corrected ```rootcause block. This is the last attempt."
        if last
        else "Emit one corrected ```rootcause block."
    )
    return f"ROOT CAUSE REJECTED\nThe hypothesis did not validate:\n{listed}\n{closing}"


@dataclass
class _Usage:
    """Running totals over a diagnosis's attempts.

    A mutable accumulator rather than four loop variables, so every return path
    reports the same set of fields and none can drift out of sync.

    Counting an attempt and recording its tokens are deliberately **two** steps,
    because they answer different questions and become true at different moments:

    ``attempt()`` runs immediately *before* ``gateway.generate``, so a call that
    raises -- a provider error, an exhausted budget -- is still counted. A call
    was made; whether it came back is a separate fact. Counting on return would
    report a run that burned two provider round-trips as having made one.

    ``record()`` runs only on a returned ``GenerationResult``. Tokens are never
    estimated or carried over for a failed call: a request that produced no
    result reports no usage, because inventing a number here would put a
    fabricated figure into cost accounting.
    """

    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0

    def attempt(self) -> None:
        """One gateway.generate invocation, counted before it is made."""
        self.model_calls += 1

    def record(self, result: Any) -> None:
        """Usage the gateway actually returned. Never called for a failed call."""
        self.input_tokens += result.input_tokens
        self.output_tokens += result.output_tokens
        self.thinking_tokens += result.thinking_tokens


# -- the bounded call -------------------------------------------------------


def diagnose(
    *,
    task_text: str,
    evidence: FailureEvidence,
    repro: FrozenRepro,
    workspace: Workspace,
    gateway: LLMGateway,
    budget: BudgetController,
    model: str,
    task_id: str,
    run_id: int | None = None,
    conn: sqlite3.Connection | None = None,
    limits: Limits = DEFAULT_LIMITS,
    policy: CommandPolicy = DEFAULT_POLICY,
    log: SessionLog | None = None,
) -> DiagnosisOutcome:
    """Ask for a root cause, validate it, and retry once with the errors fed back.

    Never raises. A provider failure, an exhausted budget and an unusable
    hypothesis are all outcomes with a status, because the caller's next
    decision -- refuse to edit -- is the same in every case and should not be
    reached through an exception handler.
    """
    sink = log if log is not None else SessionLog()
    context = build_context(
        evidence=evidence, workspace=workspace, policy=policy, limits=limits
    )
    sink.emit("diagnosis_context", payload={"inspected_files": context.inspected_files})

    system = build_diagnosis_prompt(limits)
    messages = [Message(role="user", content=render_request(task_text, repro, context))]
    errors: list[str] = []
    usage = _Usage()
    attempts = max(1, limits.max_rootcause_attempts)

    for attempt in range(1, attempts + 1):
        # Counted before the call, so a request that raises is still a request
        # that was made. See _Usage for why this is not counted on return.
        usage.attempt()
        try:
            result = gateway.generate(
                budget=budget,
                messages=messages,
                model=model,
                system=system,
                max_tokens=limits.rootcause_max_tokens,
                agent_name=AGENT_NAME,
                conn=conn,
                run_id=run_id,
                task_id=task_id,
            )
        except BudgetExceededError as exc:
            return _unavailable(
                sink, context, attempt - 1, f"budget exhausted before diagnosis: {exc}", usage
            )
        except Exception as exc:  # noqa: BLE001 - a failed call is a status, not a crash
            return _unavailable(
                sink, context, attempt - 1,
                f"diagnosis call failed: {type(exc).__name__}: {exc}", usage
            )

        usage.record(result)
        sink.emit(
            "rootcause_attempt",
            attempt,
            # Counts, never content -- the rule the whole codebase follows.
            text_chars=len(result.text),
            stop_reason=result.stop_reason,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            thinking_tokens=result.thinking_tokens,
        )

        payload, parse_error = parse_rootcause_block(result.text)
        if parse_error is not None:
            errors = [parse_error]
        else:
            assert payload is not None
            cause, errors = validate_rootcause(
                payload, workspace=workspace, evidence=evidence, policy=policy, limits=limits
            )
            if cause is not None:
                sink.emit(
                    "rootcause_result",
                    attempt,
                    status=DiagnosisStatus.OK.value,
                    root_cause=cause.as_dict(),
                )
                return DiagnosisOutcome(
                    status=DiagnosisStatus.OK,
                    root_cause=cause,
                    attempts=attempt,
                    inspected_files=context.inspected_files,
                    reason=f"root cause identified at {cause.location()}",
                    model_calls=usage.model_calls,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    thinking_tokens=usage.thinking_tokens,
                )

        sink.emit(
            "rootcause_rejected", attempt, errors=errors, response_chars=len(result.text)
        )
        if attempt < attempts:
            messages.append(Message(role="assistant", content=result.text))
            messages.append(
                Message(role="user", content=render_errors(errors, last=attempt + 1 == attempts))
            )

    reason = f"no valid root cause after {attempts} attempt(s)"
    sink.emit("rootcause_result", attempts, status=DiagnosisStatus.REJECTED.value, errors=errors)
    return DiagnosisOutcome(
        status=DiagnosisStatus.REJECTED,
        attempts=attempts,
        errors=errors,
        reason=reason,
        inspected_files=context.inspected_files,
            model_calls=usage.model_calls,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            thinking_tokens=usage.thinking_tokens,
    )


def _unavailable(
    sink: SessionLog,
    context: DebugContext,
    attempts: int,
    reason: str,
    usage: "_Usage",
) -> DiagnosisOutcome:
    """A call that never returned an answer -- but earlier calls still cost."""
    sink.emit("rootcause_result", attempts, status=DiagnosisStatus.UNAVAILABLE.value, reason=reason)
    return DiagnosisOutcome(
        status=DiagnosisStatus.UNAVAILABLE,
        attempts=attempts,
        errors=[reason],
        reason=reason,
        inspected_files=context.inspected_files,
            model_calls=usage.model_calls,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            thinking_tokens=usage.thinking_tokens,
    )


__all__ = [
    "AGENT_NAME",
    "Confidence",
    "DiagnosisOutcome",
    "DiagnosisStatus",
    "RootCause",
    "build_diagnosis_prompt",
    "compute_confidence",
    "diagnose",
    "parse_rootcause_block",
    "validate_rootcause",
]
