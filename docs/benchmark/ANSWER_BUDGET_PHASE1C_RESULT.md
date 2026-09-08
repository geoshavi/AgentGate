# Answer-Budget Hardening — Phase 1C result

**Status: BENEFIT SHOWN.** All six conditions of section 8.3 held. This is the first
non-VOID execution of the answer-budget design across three attempts.

| | |
|---|---|
| Registration | `docs/benchmark/ANSWER_BUDGET_PHASE1C_REGISTRATION.md` (unmodified) |
| HEAD at execution | `3d74b154a9a7f1be436035e08b2628a1dd0e094f` |
| Judge model | `claude-sonnet-5` |
| Batch | 44/44 registered calls completed; `classification: COMPLETE`, `persistence_failure: false` |
| Spend | **$0.379638**, against the registered $0.65 ceiling |
| Raw artifact | `experiments/answer_budget/phase1c_batch.jsonl` (preserved verbatim) |
| Summary | `experiments/answer_budget/phase1c_summary.json` (preserved verbatim) |
| Benchmark runs | none. No row in `.engine/state.db`, no `BASELINE.md` row |

## 1. Batch integrity

Class T / S / X counted per section 10, deciding nothing per section 6 row E:

| class | count |
|---|---|
| T | 5 |
| S | 1 |
| X | **0** |

Zero Class X occurrences: no VOID condition in section 9 was met. No persistence failure.
No budget stop (44/44 completed under the $0.65 ceiling).

## 2. Primary endpoint — target benefit (section 8.3(c), (d))

`security-04-clean × {correctness, security}`, against the registered 0/8 baseline:

| arm | correctness | security | total |
|---|---|---|---|
| Arm A (drift check) | 0/2 | 0/2 | **0/4** |
| Arm B (intervention) | 4/4 | 4/4 | **8/8** |

Arm A reproduced the registered `stop_reason=max_tokens`, zero-character baseline on all 4
calls — no drift. Arm B reached 8/8 schema-valid emission, split 4/4 per lens, clearing both
the `≥ 5/8` primary threshold (c) and the `≥ 2/4` per-lens requirement (d).

## 3. Guardrail 1 — broken-case safety (section 8.1, 8.3(e))

`quality-04-broken`, Arm B, 4 safety replicates (2 lens calls each):

| replicate | classification |
|---|---|
| 1 | SAFE |
| 2 | SAFE |
| 3 | SAFE |
| 4 | SAFE |

**4/4 evaluable, 4/4 SAFE.** Clears the evaluability floor (≥ 3/4) with every evaluable
replicate SAFE. Zero REJECT events — the batch never triggered the zero-tolerance stop
condition.

## 4. Guardrail 2 — control blocking retention (section 8.2, 8.3(f))

`security-02-clean`, both lenses:

| lens | V_L | D_L | a_L | b_L | status |
|---|---|---|---|---|---|
| correctness | 3 | 1 | 0.333 | 1.0 | PASS |
| security | 4 | 4 | 1.0 | 1.0 | PASS |

Both lenses evaluable (V_L ≥ 2), and `b_L ≥ a_L` on both. **Guardrail 2 overall: PASS.**

## 5. Outcome

All six conditions of section 8.3:

| | condition | result |
|---|---|---|
| (a) | no VOID condition met | met — zero Class X, no persistence failure, no budget stop |
| (b) | zero REJECT events | met |
| (c) | ≥ 5/8 Arm B target calls emit schema-valid critic | met — 8/8 |
| (d) | effect on both target lenses at ≥ 2/4 each | met — 4/4 and 4/4 |
| (e) | safety endpoint evaluable (≥ 3/4) and every evaluable replicate SAFE | met — 4/4 SAFE |
| (f) | Guardrail 2 passes | met — PASS on both lenses |

**Final outcome: BENEFIT SHOWN.**

## 6. No production authorization

Consistent with `ANSWER_BUDGET_PHASE1C_REGISTRATION.md` section 0: BENEFIT SHOWN
establishes only that a thinking-disabled lens call can rescue this specific deterministic
truncation on `security-04-clean`. It does **not** authorize R-a, `thinking={"type":
"disabled"}`, or any other production change. Implementation requires a separate Phase 2
registration and, at minimum, a broken-case safety batch across the five thin-margin cases
named in `ANSWER_BUDGET_REGISTRATION.md` section 2 — none of which is measured here.

Nothing in this execution changed any file under the measured path (`src/engine/`), the
harness, verifier semantics, prompts, model configuration, or the dataset.
