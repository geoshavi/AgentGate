"""Answer-Budget Hardening Phase 1B -- registered batch.

Follows docs/benchmark/ANSWER_BUDGET_PHASE1B_REGISTRATION.md exactly. Nothing
in src/engine is edited, monkeypatched, or wrapped -- the harness constructs
its own Anthropic client (the thinking parameter does not exist anywhere in
the engine's Provider/Gateway surface, per section 5) and reuses LENSES,
RESPONSE_INSTRUCTION, the exact prompt template from run_judge_gates,
_parse_critic, and _extract_json_objects (used read-only, for failure
classification per section 9.1, not to alter parsing), unmodified.
conn=None, run_id=None throughout: no database row is written anywhere, and
no benchmark run occurs.

R-a / off-lens blocking authority is not referenced anywhere in this file.
"""

import json
import random
import subprocess
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

repo_root = Path(
    subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True
    ).stdout.strip()
)
sys.path.insert(0, str(repo_root / "src"))

from anthropic import Anthropic  # noqa: E402

from engine.config import DEFAULT_MODELS, load_config  # noqa: E402
from engine.eval.dataset import CASES  # noqa: E402
from engine.runtime.budget import BudgetController, BudgetExceededError  # noqa: E402
from engine.verification.judge import (  # noqa: E402
    LENSES,
    RESPONSE_INSTRUCTION,
    _extract_json_objects,
    _parse_critic,
)
from engine.verification.pipeline import read_code_snapshot  # noqa: E402
from engine.verification.rubric import BLOCKING  # noqa: E402

MODEL = DEFAULT_MODELS["anthropic"]["judge"]
assert MODEL == "claude-sonnet-5"

SEED = 20260902
CEILING = Decimal("0.65")

SETS = {
    "target": {"case_id": "security-04-clean", "lenses": ["correctness", "security"]},
    "control": {"case_id": "security-02-clean", "lenses": ["correctness", "security"]},
    "safety": {"case_id": "quality-04-broken", "lenses": ["correctness", "code-quality"]},
}

# Section 9.2: the Contamination Set is exactly these 16 calls.
CONTAMINATION_SET = {
    ("control", "correctness", "A"),
    ("control", "security", "A"),
    ("safety", "correctness", "A"),
    ("safety", "code-quality", "A"),
}


def build_replicate_calls(replicate: int) -> list[tuple[str, str, str]]:
    """(set_name, lens, arm) tuples for one replicate, per section 5's reps."""
    calls: list[tuple[str, str, str]] = []
    for lens in SETS["target"]["lenses"]:
        if replicate <= 2:
            calls.append(("target", lens, "A"))
        calls.append(("target", lens, "B"))
    for lens in SETS["control"]["lenses"]:
        calls.append(("control", lens, "A"))
        calls.append(("control", lens, "B"))
    for lens in SETS["safety"]["lenses"]:
        calls.append(("safety", lens, "A"))
        calls.append(("safety", lens, "B"))
    return calls


def classify_failure(stop_reason: str, text: str, errors: list[str]) -> str | None:
    """Section 9.1 failure classes, derived read-only from the same logic
    _parse_critic already applied -- this never changes what _parse_critic
    returned, it only labels why it returned it."""
    if not errors:
        return None
    if stop_reason == "max_tokens":
        return "T"
    if stop_reason == "end_turn":
        objects = _extract_json_objects(text)
        if not objects:
            return "X"  # end_turn response containing no JSON object at all
        try:
            json.loads(objects[-1])
        except json.JSONDecodeError:
            return "X"  # balanced braces but not valid JSON -- anomalous
        return "S"  # valid JSON, schema violation -> enforce_critic_schema failed it
    return "X"  # any other stop_reason: API error, refusal, pause_turn, etc.


def main() -> int:
    config = load_config()
    if not config.anthropic_api_key:
        print("ANTHROPIC_API_KEY not resolved -- aborting before any call.")
        return 1
    client = Anthropic(api_key=config.anthropic_api_key)

    budget = BudgetController(max_tokens=400_000, planned_budget=CEILING)

    prompts: dict[str, str] = {}
    for set_name, spec in SETS.items():
        case = next(c for c in CASES if c.eval_case_id == spec["case_id"])
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            for rel_path, content in case.files.items():
                dest = workspace / rel_path
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(content, encoding="utf-8")
            snapshot = read_code_snapshot(workspace)
        prompt = (
            f"Task given to the coding agent:\n{case.task_text}\n\n"
            f"Resulting code (all files concatenated):\n{snapshot}"
        ) + RESPONSE_INSTRUCTION
        prompts[set_name] = prompt

    log_path = Path(__file__).parent / "phase1b_batch.jsonl"
    records: list[dict] = []
    classification: str | None = None  # None | "PARTIAL_VOID" | "VOID" | terminal-safety
    stop_detail: str | None = None
    persistence_failure = False

    rng = random.Random(SEED)

    with log_path.open("w", encoding="utf-8") as log:
        try:
            for replicate in range(1, 5):
                call_list = build_replicate_calls(replicate)
                rng.shuffle(call_list)
                print(f"\n--- replicate {replicate}: {len(call_list)} calls ---")

                for set_name, lens, arm in call_list:
                    spec = SETS[set_name]
                    case_id = spec["case_id"]

                    try:
                        budget.check_before_call(MODEL, 1600)
                    except BudgetExceededError as exc:
                        classification = "PARTIAL_VOID"
                        stop_detail = f"BUDGET STOP -- {exc}"
                        raise StopIteration from None

                    kwargs = {
                        "model": MODEL,
                        "system": LENSES[lens],
                        "messages": [{"role": "user", "content": prompts[set_name]}],
                        "max_tokens": 1600,
                    }
                    if arm == "B":
                        kwargs["thinking"] = {"type": "disabled"}

                    response = client.messages.create(**kwargs)
                    text = "".join(b.text for b in response.content if b.type == "text")
                    details = response.usage.output_tokens_details
                    thinking_tokens = details.thinking_tokens if details is not None else 0

                    spend = budget.record_usage(
                        MODEL,
                        input_tokens=response.usage.input_tokens,
                        output_tokens=response.usage.output_tokens,
                        cache_read_tokens=response.usage.cache_read_input_tokens or 0,
                        cache_creation_tokens=response.usage.cache_creation_input_tokens or 0,
                    )
                    critic, errors = _parse_critic(text)
                    fail_class = classify_failure(response.stop_reason, text, errors)

                    record = {
                        "replicate": replicate,
                        "set": set_name,
                        "case_id": case_id,
                        "lens": lens,
                        "arm": arm,
                        "stop_reason": response.stop_reason,
                        "input_tokens": response.usage.input_tokens,
                        "output_tokens": response.usage.output_tokens,
                        "thinking_tokens": thinking_tokens,
                        "text_chars": len(text),
                        "raw_response": text,
                        "schema_valid": not errors,
                        "schema_errors": errors,
                        "failure_class": fail_class,
                        "defects": critic.get("defects", []) if not errors else [],
                        "verdict": critic.get("verdict") if not errors else None,
                        "spend": str(spend),
                    }

                    # Section 2.2 / stop condition 6: persistence must succeed and
                    # round-trip before the call is considered measured.
                    try:
                        line = json.dumps(record)
                        log.write(line + "\n")
                        log.flush()
                        readback = json.loads(line)
                        if readback.get("raw_response") != text or (
                            text and not readback.get("raw_response")
                        ):
                            raise ValueError("raw_response did not round-trip")
                    except Exception as exc:  # noqa: BLE001
                        persistence_failure = True
                        classification = "VOID"
                        stop_detail = f"PERSISTENCE FAILURE -- {exc}"
                        raise StopIteration from None

                    records.append(record)

                    blockers = [d for d in record["defects"] if d.get("severity") in BLOCKING]
                    print(
                        f"  {set_name:8s} {case_id:20s} {lens:12s} arm={arm} "
                        f"stop={response.stop_reason:12s} think={thinking_tokens:5d} "
                        f"chars={len(text):5d} valid={not errors} class={fail_class} "
                        f"blockers={len(blockers)}"
                    )

                    # --- stop condition 3: Class X anywhere, either arm ---
                    if fail_class == "X":
                        classification = "VOID"
                        stop_detail = (
                            f"CLASS X FAILURE -- {set_name}/{lens} arm={arm} rep={replicate}: "
                            f"{errors}"
                        )
                        raise StopIteration

                    # --- stop condition 2: baseline drift on target Arm A ---
                    if set_name == "target" and arm == "A":
                        reproduces = response.stop_reason == "max_tokens" and len(text) == 0
                        if not reproduces:
                            classification = "BASELINE_DRIFT"
                            stop_detail = (
                                f"BASELINE DRIFT -- target Arm A ({lens}, replicate "
                                f"{replicate}) did not reproduce stop_reason=max_tokens/"
                                f"zero-text (got stop_reason={response.stop_reason}, "
                                f"text_chars={len(text)})"
                            )
                            raise StopIteration

                    # --- stop condition 1: hard safety REJECT, quality-04-broken Arm B ---
                    if set_name == "safety" and arm == "B":
                        b_this_rep = [
                            r
                            for r in records
                            if r["set"] == "safety"
                            and r["arm"] == "B"
                            and r["replicate"] == replicate
                        ]
                        lenses_seen = {r["lens"] for r in b_this_rep}
                        if lenses_seen == set(SETS["safety"]["lenses"]):
                            all_defects = [d for r in b_this_rep for d in r["defects"]]
                            has_blocker = any(d.get("severity") in BLOCKING for d in all_defects)
                            if not has_blocker:
                                classification = "REJECT"
                                stop_detail = (
                                    f"SAFETY REJECT -- quality-04-broken Arm B replicate "
                                    f"{replicate}: no CRITICAL/HIGH defect survived across "
                                    f"both lenses"
                                )
                                raise StopIteration
        except StopIteration:
            pass

    print(f"\n{'=' * 70}")
    print(f"calls completed: {len(records)} / 44 planned")
    print(f"total spend: ${budget.spent_amount}")
    if stop_detail:
        print(f"STOPPED: {stop_detail}")
    else:
        print("batch completed in full")
        classification = "COMPLETE"

    summary_path = Path(__file__).parent / "phase1b_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "calls_completed": len(records),
                "calls_planned": 44,
                "total_spend": str(budget.spent_amount),
                "classification": classification,
                "stop_detail": stop_detail,
                "persistence_failure": persistence_failure,
                "records": records,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nfull records -> {log_path}")
    print(f"summary -> {summary_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
