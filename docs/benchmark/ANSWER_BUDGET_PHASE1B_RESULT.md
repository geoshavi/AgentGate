# Answer-Budget Hardening — Phase 1B result and forensic

**Status: VOID.** The registered contamination guardrail (§9.4 of
`ANSWER_BUDGET_PHASE1B_REGISTRATION.md`) tripped. Phase 1B produced no citable finding.

| | |
|---|---|
| Registration | `docs/benchmark/ANSWER_BUDGET_PHASE1B_REGISTRATION.md` (unmodified) |
| HEAD at execution | `a097c8082f59ee27078fbe614d7ccac1fadd83d0` |
| Judge model | `claude-sonnet-5` |
| Batch | 44/44 registered calls completed; `classification: COMPLETE`, `persistence_failure: false` |
| Spend | **$0.384688**, against the registered $0.65 ceiling |
| Raw artifact | `experiments/answer_budget/phase1b_batch.jsonl` (44 records, one per call, raw response text persisted per §2.2) |
| Summary | `experiments/answer_budget/phase1b_summary.json` |
| Harness | `experiments/answer_budget/phase1b_batch.py` — **the executed original**, not a lint-edited copy (see §5) |
| Benchmark runs | none. No row in `.engine/state.db`, no `BASELINE.md` row |

## 1. Why Phase 1B is VOID

Registered stop condition 5 / §9.4: **VOID if X ≥ 5**, where X is the count of schema
failures across the enumerated 16-call Contamination Set (the non-target Arm A calls of
`security-02-clean` and `quality-04-broken`, both lenses).

Observed: **X = 5.** The measurement is void.

| # | case | lens | rep | stop_reason | class |
|---|---|---|---|---|---|
| 1 | `security-02-clean` | security | 1 | `max_tokens` | T |
| 2 | `security-02-clean` | correctness | 2 | `max_tokens` | T |
| 3 | `quality-04-broken` | code-quality | 2 | `end_turn` | S |
| 4 | `security-02-clean` | security | 4 | `max_tokens` | T |
| 5 | `quality-04-broken` | correctness | 4 | `end_turn` | S |

Zero Class X failures in either arm. The target-set drift check reproduced the stored
baseline exactly (4/4 Arm A calls `max_tokens`, 0 chars). No REJECT event.

**No BENEFIT SHOWN claim may be made from Phase 1B.** Target Arm B reached 8/8
schema-valid emission (4/4 on each lens) against the registered 0/8 baseline, and no
REJECT fired on the safety case — but the measurement is void, so these numbers are not
findings, per the same rule that applied to Phase 1.

## 2. What the numbers were — observational only

Recorded so a successor can size itself. **None of this is a finding, and none of it may
be cited as evidence for or against R-a, the answer-budget hypothesis, or any production
change.**

- **Target `security-04-clean`: Arm A 0/4 emission (drift-check reproduced), Arm B 8/8
  schema-valid**, split 4/4 per lens.
- **Safety `quality-04-broken`: no REJECT.** Every Arm B replicate retained at least one
  CRITICAL/HIGH-severity defect where required; no Arm B replicate returned OK on a case
  Arm A blocks.
- **Control `security-02-clean`: no calibration loss observed**, though Guardrail 2 could
  not be meaningfully evaluated given the void.
- **Schema-failure rate by arm (non-target Arm A calls only, excluding target-set drift
  checks): Arm A 5/16 (31.2%), Arm B 3/24 (12.5%).** The intervention arm remained cleaner
  than the baseline arm on the metric that voided the batch, consistent with Phase 1.

## 3. Forensic — the five Contamination Set failures

Full per-call detail (stop_reason, token counts, exact raw text, parsed defects) is in
`phase1b_batch.jsonl`; this section summarizes the classification.

| # | call | stop_reason | output / thinking | class | mechanism |
|---|---|---|---|---|---|
| 1 | `security-02-clean` × security, rep 1 | `max_tokens` | 1600 / 1070 (67%) | T | mid-answer truncation |
| 2 | `security-02-clean` × correctness, rep 2 | `max_tokens` | 1600 / 1523 (95%) | T | mid-answer truncation |
| 3 | `quality-04-broken` × code-quality, rep 2 | `end_turn` | 276 / 0 | S | verdict/severity schema inconsistency |
| 4 | `security-02-clean` × security, rep 4 | `max_tokens` | 1600 / 1503 (94%) | T | mid-answer truncation |
| 5 | `quality-04-broken` × correctness, rep 4 | `end_turn` | 151 / 0 | S | verdict/severity schema inconsistency |

**None matches the `security-04-clean` zero-answer thinking-exhaustion mechanism** — that
signature is `max_tokens` with thinking at ~100% of the 1600-token cap and **zero**
characters of answer text, reproduced 4/4 in this batch's own drift check. All five
Contamination Set failures produced substantial answer text before failing.

**Two mechanisms, matching Phase 1's two mechanisms exactly, on the same two cases:**

- **Rows 1, 2, 4 — mid-answer truncation (mechanism B)**, on `security-02-clean`, now
  observed on *both* lenses (security and correctness) rather than security only. This is
  the documented stochastic-truncation cell, consistent with the historical ~50% at-cap
  rate on `security-02-clean × security` and now also present on `security-02-clean ×
  correctness`.
- **Rows 3, 5 — verdict/severity schema inconsistency (mechanism C)**, on
  `quality-04-broken`, now observed on *both* lenses (code-quality and correctness) rather
  than code-quality only. Each raw response is complete, balanced JSON with only
  MEDIUM/LOW-severity defects and `verdict: "FAIL"`, which `enforce_critic_schema` rejects
  because no CRITICAL/HIGH defect justifies a FAIL verdict.

**No new mechanism. No Class X.** Phase 1B's five failures are the same two documented
mechanisms as Phase 1's three, spread from one lens to both lenses on each of the same two
cases.

## 4. Integrity model — materially miscalibrated

The registered per-cell nuisance rates (§9.3) held for the truncation mechanism but not
for the semantic mechanism.

| cell | declared p | Phase 1 | Phase 1B | pooled (n=8) | pooled rate |
|---|---|---|---|---|---|
| `security-02-clean` × correctness | 0.08 | 0/4 | 1/4 | 1/8 | 0.125 |
| `security-02-clean` × security | 0.51 | 2/4 | 2/4 | 4/8 | 0.500 |
| `quality-04-broken` × correctness | 0.01 | 0/4 | 1/4 | 1/8 | 0.125 |
| `quality-04-broken` × code-quality | 0.01 | 1/4 | 1/4 | 2/8 | 0.250 |

The dominant truncation cell's declared rate (0.51) landed within measurement noise of the
pooled observation (0.500) — the physical/empirical reasoning in §9.3 for mechanism B held.

The semantic mechanism's rate was declared as a single global constant, `p_S = 0.01`,
"a property of the judge, not of a case" (§9.3). It is case-specific: pooled across both
phases and all arms, `quality-04-broken × code-quality` shows a 25.0% semantic-failure
rate versus 6.25% (1/16) on `security-02-clean × correctness` — a difference of **4×**,
not the declared assumption of a single uniform rate. Modeling `p_S` as global rather than
per-cell under-declared the two `quality-04-broken` cells by roughly one order of
magnitude, and the recalibrated Poisson-binomial false-void probability on a healthy batch
rises from the designed 0.039 to approximately 0.47 under pooled per-cell rates — close to
Phase 1's own 0.468 false-void rate under its since-replaced pooled threshold.

This is recorded as a defect in the nuisance model for a successor to fix. It is not a
retrofit of Phase 1B's own X = 5 outcome, which stands as VOID under the rule as
registered.

## 5. Provenance of the preserved harness

`phase1b_batch.py` is preserved as the **executed original**. Unlike Phase 1's harness
copies, it has not been passed through `ruff check` or otherwise lint-edited before being
committed. If a repo-wide `ruff` gate is run against this file and it fails, that is
expected and is not a defect to fix by editing the executed harness after the fact — doing
so would break the guarantee that this file is byte-identical to what produced
`phase1b_batch.jsonl`. Any lint failure here is a property of an experiment-scratch file,
not of production code, and should be excluded from the gate or accepted as a known,
documented exception rather than silently modified.

## 6. No production authorization

Nothing here authorizes R-a, `thinking={"type":"disabled"}`, or any other change to
`src/engine`. Phase 1B changed no production code and registered no such change. A
successor experiment requires its own pre-registration, informed by the integrity-model
fix in §4, before any further paid call.
