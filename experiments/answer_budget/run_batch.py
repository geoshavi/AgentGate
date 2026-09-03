"""Answer-Budget Hardening Phase 1 -- registered batch.

Follows docs/benchmark/ANSWER_BUDGET_REGISTRATION.md sections 4-11 exactly.
Nothing in src/engine is edited, monkeypatched, or wrapped -- the harness
constructs its own Anthropic client (the thinking parameter does not exist
anywhere in the engine's Provider/Gateway surface, per section 5) and reuses
LENSES, RESPONSE_INSTRUCTION, the exact prompt template from run_judge_gates,
and _parse_critic, unmodified. conn=None, run_id=None throughout: no database
row is written anywhere, and no benchmark run occurs.

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
from engine.verification.judge import LENSES, RESPONSE_INSTRUCTION, _parse_critic
from engine.verification.pipeline import read_code_snapshot
from engine.verification.rubric import BLOCKING

MODEL = DEFAULT_MODELS["anthropic"]["judge"]
assert MODEL == "claude-sonnet-5"

SEED = 20260902
CEILING = Decimal("0.55")

# Stage 0 already executed and reported separately -- pre-recorded here so
# the $0.55 ceiling is enforced against the true running total (registration
# section: "enforce the registered $0.55 total hard ceiling, including
# Stage 0"). Figures are exactly what Stage 0 printed.
STAGE0_INPUT_TOKENS = 735
STAGE0_OUTPUT_TOKENS = 150

# ---- section 5 design table -----------------------------------------------
SETS = {
    "target": {"case_id": "security-04-clean", "lenses": ["correctness", "security"]},
    "control": {"case_id": "security-02-clean", "lenses": ["correctness", "security"]},
    "safety": {"case_id": "quality-04-broken", "lenses": ["correctness", "code-quality"]},
}


def build_replicate_calls(replicate: int) -> list[tuple[str, str, str]]:
    """(set_name, lens, arm) tuples for one replicate, per section 5's reps."""
    calls: list[tuple[str, str, str]] = []
    # target: Arm A = 2 reps (drift check only), Arm B = 4 reps
    for lens in SETS["target"]["lenses"]:
        if replicate <= 2:
            calls.append(("target", lens, "A"))
        calls.append(("target", lens, "B"))
    # control: Arm A = 4 reps, Arm B = 4 reps
    for lens in SETS["control"]["lenses"]:
        calls.append(("control", lens, "A"))
        calls.append(("control", lens, "B"))
    # safety: Arm A = 4 reps, Arm B = 4 reps
    for lens in SETS["safety"]["lenses"]:
        calls.append(("safety", lens, "A"))
        calls.append(("safety", lens, "B"))
    return calls


def main() -> int:
    config = load_config()
    if not config.anthropic_api_key:
        print("ANTHROPIC_API_KEY not resolved -- aborting before any call.")
        return 1
    client = Anthropic(api_key=config.anthropic_api_key)

    budget = BudgetController(max_tokens=400_000, planned_budget=CEILING)
    budget.record_usage(
        MODEL,
        input_tokens=STAGE0_INPUT_TOKENS,
        output_tokens=STAGE0_OUTPUT_TOKENS,
        cache_read_tokens=0,
        cache_creation_tokens=0,
    )
    print(f"Stage 0 pre-recorded: spend so far = ${budget.spent_amount}")

    # Build each case's prompt once (files are static per case).
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

    log_path = Path(__file__).parent / "stage1_batch.jsonl"
    records: list[dict] = []
    stop_reason_batch: str | None = None

    rng = random.Random(SEED)

    with log_path.open("w", encoding="utf-8") as log:
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
                    stop_reason_batch = f"BUDGET STOP -- {exc}"
                    break

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

                record = {
                    "replicate": replicate,
                    "set": set_name,
                    "case_id": case_id,
                    "lens": lens,
                    "arm": arm,
                    "stop_reason": response.stop_reason,
                    "output_tokens": response.usage.output_tokens,
                    "thinking_tokens": thinking_tokens,
                    "text_chars": len(text),
                    "schema_valid": not errors,
                    "schema_errors": errors,
                    "defects": critic.get("defects", []) if not errors else [],
                    "verdict": critic.get("verdict") if not errors else None,
                    "spend": str(spend),
                }
                records.append(record)
                log.write(json.dumps(record) + "\n")
                log.flush()

                mark = ""
                blockers = [d for d in record["defects"] if d.get("severity") in BLOCKING]
                print(
                    f"  {set_name:8s} {case_id:20s} {lens:12s} arm={arm} "
                    f"stop={response.stop_reason:12s} think={thinking_tokens:5d} "
                    f"chars={len(text):5d} schema_valid={not errors} "
                    f"blockers={len(blockers)}{mark}"
                )

                # --- stop condition 4: baseline drift on the target Arm A calls ---
                if set_name == "target" and arm == "A":
                    reproduces = response.stop_reason == "max_tokens" and len(text) == 0
                    if not reproduces:
                        stop_reason_batch = (
                            f"BASELINE DRIFT -- target Arm A ({lens}, replicate {replicate}) "
                            f"did not reproduce stop_reason=max_tokens/zero-text "
                            f"(got stop_reason={response.stop_reason}, text_chars={len(text)})"
                        )
                        break

                # --- stop condition 2: hard safety REJECT on quality-04-broken Arm B ---
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
                            stop_reason_batch = (
                                f"SAFETY REJECT -- quality-04-broken Arm B replicate "
                                f"{replicate}: no CRITICAL/HIGH defect survived across "
                                f"both lenses"
                            )
                            break

            if stop_reason_batch:
                break

    print(f"\n{'=' * 70}")
    print(f"calls completed: {len(records)} / 44 planned")
    print(f"total spend (incl. Stage 0): ${budget.spent_amount}")
    if stop_reason_batch:
        print(f"BATCH STOPPED: {stop_reason_batch}")
    else:
        print("batch completed in full")

    # Summary written for the report step to consume.
    summary_path = Path(__file__).parent / "stage1_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "calls_completed": len(records),
                "calls_planned": 44,
                "total_spend": str(budget.spent_amount),
                "stop_reason_batch": stop_reason_batch,
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
