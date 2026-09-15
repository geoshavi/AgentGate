"""Phase 4C measurement harness.

Calls the REAL judge lenses through the REAL ``run_judge_gates``, on the REAL
post-fix snapshot built by the REAL ``read_code_snapshot``, using the REAL
Debug Agent verification framing from HEAD. Nothing in ``src/engine`` is
modified, monkeypatched or wrapped, and **R-a is not implemented** -- it exists
only as an offline scoring function here.

Because R-a is merge/gate-only, one set of paid lens calls scores both arms:

    Arm A -- current semantics: any CRITICAL/HIGH defect blocks.
    Arm B -- R-a: an off-lens defect is recorded but carries no blocking authority.

``verdict.gate`` is called with automated_passed=True throughout. On the N
controls the real pytest gate would fail and block regardless of what a lens
said, which would mask the effect under test; holding it constant isolates lens
behaviour. Registered modelling choice -- ``gate`` takes the flag as a parameter,
so no semantics are changed.

conn=None and run_id=None: no row is written to any database.
"""

import argparse
import json
import os
import random
import sys
import tempfile
import time
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from fixtures import FIXTURES

from engine.config import DEFAULT_MODELS, load_config
from engine.debugagent.app import _verification_task
from engine.debugagent.repro import FrozenRepro
from engine.runtime.budget import BudgetController, BudgetExceededError
from engine.runtime.gateway import LLMGateway
from engine.verification import verdict
from engine.verification.judge import run_judge_gates
from engine.verification.pipeline import read_code_snapshot

ROOT = Path(__file__).parent
# Built outside the repository -- see build_and_verify.py for why.
BUILD = Path(
    os.environ.get("PHASE4C_WORKSPACES", Path(tempfile.gettempdir()) / "phase4c_workspaces")
)
SEED = 20260902
LENS_DIMENSION = {
    "correctness": "CORRECTNESS",
    "security": "SECURITY",
    "code-quality": "CODE-QUALITY",
}
BLOCKING = ("CRITICAL", "HIGH")
SUITE_ARGV = ("python", "-m", "pytest", "-q")
# A P fixture is a proven fix, so OK is correct. An N fixture is still broken,
# so a block is correct.
EXPECTED = {"p": "OK", "n": "UNVERIFIED"}


def off_lens(defect: dict) -> bool:
    """The registered rule: lens is a judge lens and its category disagrees.

    A defect with no lens, or from the automated gates, is never off-lens and
    always keeps its blocking authority.
    """
    own = LENS_DIMENSION.get(defect.get("lens"))
    return own is not None and defect.get("category") != own


def score(defects: list[dict], schema_errors: list[str]) -> tuple[str, str, int, int]:
    """Both arms from one set of defects. Returns (arm_a, arm_b, n_off, n_on)."""
    blockers = [d for d in defects if d.get("severity") in BLOCKING]
    on_lens = [d for d in blockers if not off_lens(d)]
    merged_a = {"defects": defects}
    merged_b = {"defects": on_lens}
    arm_a = verdict.gate(merged_a, True, schema_errors)
    arm_b = verdict.gate(merged_b, True, schema_errors)
    return arm_a, arm_b, len(blockers) - len(on_lens), len(on_lens)


def trial(fixture, variant, replicate, gateway, budget, model, log):
    stem = fixture["module"].removesuffix(".py")
    node = f"tests/test_{stem}.py::{fixture['repro_test']}"
    repro = FrozenRepro(("python", "-m", "pytest", "-q", node))
    suite = FrozenRepro(SUITE_ARGV)

    workspace = BUILD / variant / fixture["id"]
    snapshot = read_code_snapshot(workspace)
    task_text = _verification_task(fixture["bug_report"], repro, suite)

    schema_hits: list[str] = []
    started = time.monotonic()
    critics, schema_errors = run_judge_gates(
        gateway,
        budget,
        model,
        task_text,
        snapshot,
        run_id=None,
        task_id=f"p4c-{fixture['id']}-{variant}-r{replicate}",
        conn=None,
        timeout_seconds=180.0,
        on_schema_failure=lambda lens, raw, errs: schema_hits.append(lens),
    )
    elapsed_ms = int((time.monotonic() - started) * 1000)

    defects = [d for critic in critics for d in critic.get("defects", [])]
    arm_a, arm_b, n_off, n_on = score(defects, schema_errors)
    expected = EXPECTED[variant]

    record = {
        "fixture": fixture["id"],
        "variant": variant,
        "replicate": replicate,
        "expected": expected,
        "arm_a": arm_a,
        "arm_b": arm_b,
        "changed": arm_a != arm_b,
        "off_lens_blockers": n_off,
        "on_lens_blockers": n_on,
        "defect_count": len(defects),
        "schema_failures": schema_hits,
        "elapsed_ms": elapsed_ms,
        "defects": defects,
    }
    log.write(json.dumps(record) + "\n")
    log.flush()

    mark = ""
    if arm_a != arm_b:
        mark = "  <== CHANGED"
        if variant == "n":
            mark = "  <== CANDIDATE-INDUCED FALSE PASS"
    print(
        f"  {fixture['id']:<16} {variant.upper()} r{replicate}  "
        f"A={arm_a:<11} B={arm_b:<11} off={n_off} on={n_on} defects={len(defects)}{mark}"
    )
    return record


class CandidateFalsePass(Exception):
    """Stop condition: R-a unblocked genuinely broken code."""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replicates", type=int, default=2)
    parser.add_argument("--budget", default="0.40")
    parser.add_argument("--out", default="phase4c_batch.jsonl")
    args = parser.parse_args()

    config = load_config()
    model = DEFAULT_MODELS["anthropic"]["judge"]
    gateway = LLMGateway.from_config("anthropic", config)
    budget = BudgetController(max_tokens=400_000, planned_budget=Decimal(args.budget))

    planned = len(FIXTURES) * 2 * args.replicates
    print(f"model={model}  fixtures={len(FIXTURES)}  replicates={args.replicates}")
    print(f"trials={planned}  lens calls={planned * 3}  ceiling=${args.budget}\n")

    records: list[dict] = []
    rng = random.Random(SEED)
    stopped = None
    with (ROOT / args.out).open("w", encoding="utf-8") as log:
        try:
            for replicate in range(1, args.replicates + 1):
                order = list(FIXTURES)
                rng.shuffle(order)
                print(f"replicate {replicate}  order={[f['id'] for f in order]}")
                for fixture in order:
                    for variant in ("p", "n"):
                        record = trial(
                            fixture, variant, replicate, gateway, budget, model, log
                        )
                        records.append(record)
                        if variant == "n" and record["arm_a"] != record["arm_b"]:
                            raise CandidateFalsePass(
                                f"{fixture['id']} r{replicate}: A blocked, B returned OK"
                            )
        except CandidateFalsePass as exc:
            stopped = f"SAFETY STOP -- {exc}"
        except BudgetExceededError as exc:
            stopped = f"BUDGET STOP -- {exc}"

    print(f"\nspend ${budget.spent_amount}  tokens {budget.spent_tokens}")
    if stopped:
        print(stopped)

    for variant in ("p", "n"):
        rows = [r for r in records if r["variant"] == variant]
        if not rows:
            continue
        a_block = sum(1 for r in rows if r["arm_a"] == "UNVERIFIED")
        b_block = sum(1 for r in rows if r["arm_b"] == "UNVERIFIED")
        changed = sum(1 for r in rows if r["changed"])
        print(
            f"{variant.upper()}: n={len(rows)}  blocked A={a_block} B={b_block}  changed={changed}"
        )
    schema_total = sum(len(r["schema_failures"]) for r in records)
    print(f"schema failures: {schema_total} / {len(records) * 3} lens calls")

    per_fixture: dict = defaultdict(lambda: defaultdict(int))
    for r in records:
        per_fixture[r["fixture"]][r["variant"]] += int(r["changed"])
    print("changed trials per fixture:", {k: dict(v) for k, v in per_fixture.items()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
