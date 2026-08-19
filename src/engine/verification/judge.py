import json
import sqlite3
from collections.abc import Callable

from engine.llm_types import Effort, Message
from engine.runtime.budget import BudgetController
from engine.runtime.gateway import LLMGateway
from engine.verification.schema import enforce_critic_schema

LENSES = {
    "correctness": (
        "You are a strict, adversarial code reviewer focused ONLY on correctness: does the "
        "code do what the task asked, are there logic errors, edge cases, or bugs. Ignore "
        "style and security — those are reviewed separately."
    ),
    "security": (
        "You are a strict, adversarial code reviewer focused ONLY on security: injection "
        "risks, unsafe subprocess/eval usage, secrets handling, unvalidated input. Ignore "
        "correctness and style — those are reviewed separately."
    ),
    "code-quality": (
        "You are a strict, adversarial code reviewer focused ONLY on code quality. First, "
        "check naming (a naming defect exists when an identifier creates a misleading "
        "contract about the function's actual behavior — for example, a getter name that "
        "also creates state; do not flag normal naming preferences). Then check magic "
        "numbers (only flag a literal when it represents configurable policy, a threshold, "
        "a limit, or a domain decision that would reasonably benefit from a named constant), "
        "structure, unnecessary complexity, dead code. Do NOT flag cryptographic parameters, "
        "protocol/algorithm constants, mathematical constants, one-off labels/messages, or "
        "obvious self-documenting values. Ignore correctness and security — those are "
        "reviewed separately."
    ),
}

# Sonnet 5 runs adaptive thinking whenever the request omits a thinking
# config, at a default effort of "high". Those thinking tokens are output
# tokens and count against max_tokens, but never appear in the extracted text
# -- which is how three Phase 9C lens calls spent the entire 1600-token budget
# and returned 0 and 831 bytes of visible answer. Two of the three produced no
# text at all, so the cap could not be sized from the data: there was no upper
# bound on what they needed, only a lower one.
#
# "medium", not "low": the aim is to reclaim budget for the answer, not to
# make the judge shallow. Every broken case in Phase 9C was blocked on a
# genuine semantic defect, and losing that is a far worse outcome than a
# truncation, which at least fails closed.
#
# Scoped to the judge deliberately. The generation agents are untouched --
# see the guard test in tests/test_agents.py.
JUDGE_EFFORT: Effort = "medium"

RESPONSE_INSTRUCTION = (
    "\n\nRespond with ONLY a JSON object, no prose before or after, no markdown fences:\n"
    '{"defects": [{"id": "C1", "category": "CORRECTNESS|SECURITY|CODE-QUALITY", '
    '"severity": "CRITICAL|HIGH|MEDIUM|LOW", '
    '"location": "path:line or description", "fix": "what to change"}], '
    '"verdict": "OK|FAIL"}\n'
    "verdict must be 'FAIL' iff at least one defect has severity CRITICAL or HIGH, else 'OK'. "
    "category must be exactly one of CORRECTNESS, SECURITY, or CODE-QUALITY — use the "
    "closest match, never invent a more specific label. "
    "Return {\"defects\": [], \"verdict\": \"OK\"} if you find nothing to flag."
)


def _extract_json_objects(text: str) -> list[str]:
    """Every complete, balanced top-level {...} span in ``text``, in order.

    Tracks brace depth by hand rather than a regex: a naive greedy
    ``\\{.*\\}`` spans from the first '{' to the LAST '}' in the whole
    response, which merges multiple objects into one invalid blob if the
    model second-guesses itself mid-answer (observed in production: a
    defect, then "Wait, let me reconsider more carefully" and a corrected
    verdict, as two separate complete JSON objects). Depth tracking finds
    each object's true boundary instead. String contents are skipped
    (honoring \\" escapes) so a brace quoted inside a "fix"/"location" value
    -- e.g. a defect describing a literal dict in the reviewed code -- can't
    be mistaken for a new top-level object.
    """
    objects: list[str] = []
    depth = 0
    start: int | None = None
    in_string = False
    escaped = False
    for i, ch in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start is not None:
                objects.append(text[start : i + 1])
                start = None
    return objects


def _parse_critic(response_text: str) -> tuple[dict, list[str]]:
    objects = _extract_json_objects(response_text)
    if not objects:
        return {}, ["response did not contain a JSON object"]
    try:
        parsed = json.loads(objects[-1])  # the model's final answer, not an earlier draft
    except json.JSONDecodeError as exc:
        return {}, [f"response was not valid JSON: {exc}"]
    errors = enforce_critic_schema(parsed)
    if errors:
        return {}, errors
    return parsed, []


def run_judge_gates(
    gateway: LLMGateway,
    budget: BudgetController,
    model: str,
    task_text: str,
    code_snapshot: str,
    *,
    run_id: int | None,
    task_id: str,
    conn: sqlite3.Connection | None,
    timeout_seconds: float | None = None,
    on_schema_failure: Callable[[str, str, list[str]], None] | None = None,
) -> tuple[list[dict], list[str]]:
    critics: list[dict] = []
    schema_errors: list[str] = []
    prompt = (
        f"Task given to the coding agent:\n{task_text}\n\n"
        f"Resulting code (all files concatenated):\n{code_snapshot}"
    )
    for lens_name, lens_system in LENSES.items():
        # Phase 2.1 scope note (deliberately NOT changed here): if this call
        # raises -- budget exceeded, network error, provider error -- the
        # exception propagates straight out of run_judge_gates, and any
        # critics already collected from earlier lenses in this loop are
        # discarded along with it; the caller never sees them. That's
        # intentional/out of scope for Phase 2.1, which only adds
        # observability for the success path -- it does not change judge
        # behavior. Per-lens fault isolation (catch here, return partial
        # critics plus a per-lens error marker instead of raising) is
        # future work: it would change what gate() sees when a lens fails,
        # which is a verdict-semantics decision, not an observability one.
        response = gateway.generate(
            budget=budget,
            messages=[
                Message(
                    role="user",
                    content=prompt + RESPONSE_INSTRUCTION,
                )
            ],
            model=model,
            system=lens_system,
            # 1600, not 800: Sonnet 5 spends a large and variable share of
            # its output budget before the JSON begins. In the Phase 9B
            # canary 11 of 120 lens calls hit the old 800 cap, 9 of them
            # returning zero text, and gate() fails a truncated lens closed
            # to UNVERIFIED -- so the cap was deciding verdicts. The same
            # case/lens pairs need only 26-587 output tokens of JSON under
            # Haiku, and the largest complete JSON measured on this dataset
            # is ~800, so 1600 covers the observed pre-JSON consumption
            # (~730-800) plus a worst-case answer. A call that still
            # overruns truncates and fails closed, as before.
            max_tokens=1600,
            effort=JUDGE_EFFORT,
            agent_name=f"judge:{lens_name}",
            run_id=run_id,
            task_id=task_id,
            conn=conn,
            timeout_seconds=timeout_seconds,
        )
        critic, errors = _parse_critic(response.text)
        if errors:
            schema_errors.extend(f"judge:{lens_name}: {e}" for e in errors)
            if on_schema_failure is not None:
                # response.text is typed str, but normalize defensively --
                # callers persist this raw text and must never see None.
                on_schema_failure(lens_name, response.text or "", errors)
        else:
            # Tag by the lens that actually produced this defect, not by
            # its self-reported "category" -- the two are expected to
            # agree (each lens's prompt fixes its category string) but
            # nothing enforces that a defect's category matches the lens
            # that emitted it, and eval/'s observability tables need the
            # ground truth of which lens ran, not the model's claim.
            for defect in critic.get("defects", []):
                defect["lens"] = lens_name
            critics.append(critic)
    return critics, schema_errors
