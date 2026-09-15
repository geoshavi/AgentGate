"""Answer-Budget Hardening Phase 1 -- Stage 0 reachability probe.

Registered in docs/benchmark/ANSWER_BUDGET_REGISTRATION.md, section 11,
stop condition 1. Exactly ONE Arm B call: quality-04-broken x correctness,
with thinking={"type": "disabled"}, to confirm the API accepts that
configuration on claude-sonnet-5 before any batch spend.

Reuses LENSES, RESPONSE_INSTRUCTION, the exact prompt template from
run_judge_gates, and _parse_critic from the real engine.verification.judge
module, unmodified -- per the registration's harness description. Nothing
in src/engine is edited, monkeypatched, or wrapped. conn=None, run_id=None:
no database row is written anywhere.
"""

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
from engine.runtime.budget import BudgetController
from engine.verification.judge import LENSES, RESPONSE_INSTRUCTION, _parse_critic
from engine.verification.pipeline import read_code_snapshot

CASE_ID = "quality-04-broken"
LENS = "correctness"
MODEL = DEFAULT_MODELS["anthropic"]["judge"]
assert MODEL == "claude-sonnet-5", f"unexpected judge model: {MODEL}"


def main() -> int:
    config = load_config()
    if not config.anthropic_api_key:
        print("ANTHROPIC_API_KEY not resolved -- aborting before any call.")
        return 1

    case = next(c for c in CASES if c.eval_case_id == CASE_ID)

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

    client = Anthropic(api_key=config.anthropic_api_key)
    budget = BudgetController(max_tokens=400_000, planned_budget=Decimal("0.02"))
    budget.check_before_call(MODEL, 1600)

    print(f"model={MODEL}  case={CASE_ID}  lens={LENS}  arm=B (thinking disabled)")
    print("issuing single call...\n")

    try:
        response = client.messages.create(
            model=MODEL,
            system=LENSES[LENS],
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1600,
            thinking={"type": "disabled"},
        )
    except Exception as exc:  # noqa: BLE001 -- Stage 0 must report rejection, not raise
        print(f"API REJECTED: {type(exc).__name__}: {exc}")
        print("\nSTAGE 0 RESULT: REJECTED")
        return 2

    text = "".join(block.text for block in response.content if block.type == "text")
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

    print("API ACCEPTED")
    print(f"stop_reason        = {response.stop_reason}")
    print(f"input_tokens       = {response.usage.input_tokens}")
    print(f"output_tokens      = {response.usage.output_tokens}")
    print(f"thinking_tokens    = {thinking_tokens}")
    print(f"text_chars         = {len(text)}")
    print(f"answer_emitted     = {'yes' if text.strip() else 'no'}")
    print(f"schema_valid       = {'yes' if not errors else 'no'}")
    if errors:
        print(f"schema_errors      = {errors}")
    else:
        print(f"defect_count       = {len(critic.get('defects', []))}")
        print(f"verdict            = {critic.get('verdict')}")
    print(f"cost               = ${spend}")
    print("\nSTAGE 0 RESULT: ACCEPTED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
