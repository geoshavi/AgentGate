"""Answer-Budget Hardening Phase 1C -- registered batch.

Follows docs/benchmark/ANSWER_BUDGET_PHASE1C_REGISTRATION.md exactly. Nothing
in src/engine is edited, monkeypatched, or wrapped -- the harness constructs
its own Anthropic client (the thinking parameter does not exist anywhere in
the engine's Provider/Gateway surface, per section 5) and reuses LENSES,
RESPONSE_INSTRUCTION, the exact prompt template from run_judge_gates,
_parse_critic, and _extract_json_objects (used read-only, for failure
classification per section 10.1, not to alter parsing), unmodified.
conn=None, run_id=None throughout: no database row is written anywhere, and
no benchmark run occurs.

Section 6: only Class X (section 9.1) can VOID the batch. Class T and Class S
(section 10) are diagnostics recorded per call and never gate anything.
Guardrail 1 (section 8.1: SAFE/REJECT/UNEVALUABLE) and Guardrail 2
(section 8.2) are computed after every call is persisted -- REJECT is the
only one of the two with authority to stop the batch live, per its
zero-tolerance definition; Guardrail 2 never gates execution, only whether
BENEFIT SHOWN can be claimed once the batch is complete.

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

from anthropic import Anthropic

from engine.config import DEFAULT_MODELS, load_config
from engine.eval.dataset import CASES
from engine.runtime.budget import BudgetController, BudgetExceededError
from engine.verification.judge import (
    LENSES,
    RESPONSE_INSTRUCTION,
    _extract_json_objects,
    _parse_critic,
)
from engine.verification.pipeline import read_code_snapshot
from engine.verification.rubric import BLOCKING

MODEL = DEFAULT_MODELS["anthropic"]["judge"]
assert MODEL == "claude-sonnet-5"

SEED = 20260902
CEILING = Decimal("0.65")

SETS = {
    "target": {"case_id": "security-04-clean", "lenses": ["correctness", "security"]},
    "control": {"case_id": "security-02-clean", "lenses": ["correctness", "security"]},
    "safety": {"case_id": "quality-04-broken", "lenses": ["correctness", "code-quality"]},
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
    """Section 10.1's exhaustive tree, derived read-only from the same logic
    _parse_critic already applied -- this never changes what _parse_critic
    returned, it only labels why it returned it.

    1. non-end_turn/max_tokens stop_reason -> X
    2. a balanced JSON object is extracted AND parses, but the schema still
       rejected it -> S, regardless of stop_reason
    3. no balanced parseable object: max_tokens -> T, end_turn -> X
    """
    if not errors:
        return None
    if stop_reason not in ("end_turn", "max_tokens"):
        return "X"
    objects = _extract_json_objects(text)
    if objects:
        try:
            json.loads(objects[-1])
            return "S"  # balanced, valid JSON; enforce_critic_schema rejected it
        except json.JSONDecodeError:
            pass  # falls through: braces balanced but not valid JSON
    if stop_reason == "max_tokens":
        return "T"
    return "X"  # end_turn, no parseable JSON object at all


def classify_safety_replicate(lens_records: list[dict]) -> str:
    """Section 8.1: SAFE / REJECT / UNEVALUABLE for one Arm B safety
    replicate (its two lens calls)."""
    valid = [r for r in lens_records if r["schema_valid"]]
    blockers = [d for r in valid for d in r["defects"] if d.get("severity") in BLOCKING]
    if blockers:
        return "SAFE"
    if len(valid) == len(lens_records):  # both lenses schema-valid, neither blocking
        return "REJECT"
    return "UNEVALUABLE"


def compute_guardrail_2(records: list[dict]) -> dict:
    """Section 8.2, computed once the batch is complete. Never gates
    execution -- only whether BENEFIT SHOWN can be claimed."""
    result: dict = {}
    for lens in SETS["control"]["lenses"]:
        arm_a = [
            r for r in records if r["set"] == "control" and r["lens"] == lens and r["arm"] == "A"
        ]
        arm_b = [
            r for r in records if r["set"] == "control" and r["lens"] == lens and r["arm"] == "B"
        ]
        evaluable_a = [r for r in arm_a if r["schema_valid"]]
        v_l = len(evaluable_a)
        d_l = sum(
            1 for r in evaluable_a if any(d.get("severity") in BLOCKING for d in r["defects"])
        )
        b_count = sum(
            1 for r in arm_b if any(d.get("severity") in BLOCKING for d in r["defects"])
        )
        b_l = b_count / 4 if arm_b else None
        if v_l < 2:
            result[lens] = {"V_L": v_l, "D_L": d_l, "a_L": None, "b_L": b_l, "status": "UNEVALUABLE"}
        else:
            a_l = d_l / v_l
            fires = b_l is not None and b_l < a_l
            result[lens] = {
                "V_L": v_l,
                "D_L": d_l,
                "a_L": a_l,
                "b_L": b_l,
                "status": "FIRE" if fires else "PASS",
            }
    overall = (
        "UNEVALUABLE"
        if any(v["status"] == "UNEVALUABLE" for v in result.values())
        else ("FIRE" if any(v["status"] == "FIRE" for v in result.values()) else "PASS")
    )
    result["overall"] = overall
    return result


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

    log_path = Path(__file__).parent / "phase1c_batch.jsonl"
    records: list[dict] = []
    classification: str | None = None
    stop_detail: str | None = None
    persistence_failure = False
    safety_classifications: list[dict] = []

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

                    try:
                        response = client.messages.create(**kwargs)
                    except Exception as exc:  # noqa: BLE001
                        classification = "VOID"
                        stop_detail = (
                            f"CLASS X FAILURE (API exception) -- {set_name}/{lens} arm={arm} "
                            f"rep={replicate}: {exc!r}"
                        )
                        raise StopIteration from None

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

                    # Section 2.3 / stop condition 5: persistence must succeed and
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

                    # --- section 9.1: Class X anywhere, either arm -> VOID ---
                    if fail_class == "X":
                        classification = "VOID"
                        stop_detail = (
                            f"CLASS X FAILURE -- {set_name}/{lens} arm={arm} rep={replicate}: "
                            f"{errors}"
                        )
                        raise StopIteration

                    # --- section 9.2 #3: baseline drift on target Arm A ---
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

                    # --- section 8.1: SAFE / REJECT / UNEVALUABLE, safety Arm B ---
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
                            safety_class = classify_safety_replicate(b_this_rep)
                            safety_classifications.append(
                                {"replicate": replicate, "classification": safety_class}
                            )
                            if safety_class == "REJECT":
                                classification = "REJECT"
                                stop_detail = (
                                    f"SAFETY REJECT -- quality-04-broken Arm B replicate "
                                    f"{replicate}: both lenses schema-valid, no CRITICAL/HIGH "
                                    f"defect in either"
                                )
                                raise StopIteration
        except StopIteration:
            pass

    print(f"\n{'=' * 70}")
    print(f"calls completed: {len(records)} / 44 planned")
    print(f"total spend: ${budget.spent_amount}")
    if stop_detail:
        print(f"STOPPED: {stop_detail}")
        outcome = classification
        guardrail_2 = None
    else:
        print("batch completed in full")
        classification = "COMPLETE"
        # --- section 8.3: outcome determination, computed only on a complete,
        # non-VOID, non-REJECT batch ---
        target_b = [r for r in records if r["set"] == "target" and r["arm"] == "B"]
        target_b_emit = sum(1 for r in target_b if r["schema_valid"])
        target_b_by_lens = {
            lens: sum(
                1 for r in target_b if r["lens"] == lens and r["schema_valid"]
            )
            for lens in SETS["target"]["lenses"]
        }
        condition_c = target_b_emit >= 5
        condition_d = all(v >= 2 for v in target_b_by_lens.values())

        safe_count = sum(1 for s in safety_classifications if s["classification"] == "SAFE")
        unevaluable_count = sum(
            1 for s in safety_classifications if s["classification"] == "UNEVALUABLE"
        )
        condition_e = safe_count >= 3  # no REJECT reached here by construction

        guardrail_2 = compute_guardrail_2(records)
        condition_f = guardrail_2["overall"] == "PASS"

        if condition_c and condition_d and condition_e and condition_f:
            outcome = "BENEFIT_SHOWN"
        else:
            outcome = "INCONCLUSIVE"

        print(f"\ntarget Arm B emission: {target_b_emit}/8  by lens: {target_b_by_lens}")
        print(
            f"safety classifications: {safety_classifications}  "
            f"(SAFE={safe_count}, UNEVALUABLE={unevaluable_count})"
        )
        print(f"guardrail 2: {guardrail_2}")
        print(
            f"conditions -- c(>=5/8)={condition_c} d(>=2/4 each lens)={condition_d} "
            f"e(>=3/4 SAFE)={condition_e} f(guardrail2 PASS)={condition_f}"
        )
        print(f"\nOUTCOME: {outcome}")

    summary_path = Path(__file__).parent / "phase1c_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "calls_completed": len(records),
                "calls_planned": 44,
                "total_spend": str(budget.spent_amount),
                "classification": classification,
                "outcome": outcome,
                "stop_detail": stop_detail,
                "persistence_failure": persistence_failure,
                "safety_classifications": safety_classifications,
                "guardrail_2": guardrail_2,
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
