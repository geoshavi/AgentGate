# Pre-registration — Phase 4C: R-a on the Debug path

**Status: PRE-REGISTERED. No paid call has been made under it. No production code changed.**

| | |
|---|---|
| Registered | 2026-09-02 |
| Branch | `feature/agent-capabilities-layer` |
| HEAD at registration | `f4da8d242a6fa2ef10ce4d3c31dc7867e5ec85d0` |
| Judge model | `claude-sonnet-5` (current production judge) |
| Fixtures / harness | `experiments/phase4c/` |

## 0. Standing, and the limit of what this can establish

**Phase 4 remains INCONCLUSIVE.** Its registered ACCEPT criteria are stated against the
40-case benchmark in `OFFLENS_BLOCKING_REGISTRATION.md` and are **not amended, relaxed or
reinterpreted** by this document. Run 44 stands as recorded: R-a safety-clean in Run 1,
benefit unproven.

This is a **separate experiment** with its own criteria, measuring a different population.

> **BENEFIT SHOWN does not authorize R-a for production. It only establishes Debug-path
> benefit evidence; implementation still requires a separate approval phase.**

A REJECT here, by contrast, is decisive against the rule generally: evidence that R-a can
unblock genuinely broken code is disqualifying wherever it comes from.

## 1. Why the Debug path

The benchmark cannot observe this rule working. Measured sole-blocker exposure is **0.6%
on benchmark cases** against **25% on Debug-shaped fixtures** (Phase 3B Stage 1), because
on a correct fix the on-lens lenses correctly stay silent and an off-lens finding is left
without company. Run 44 confirmed the mechanism is live under Sonnet — 4 blocking off-lens
defects, 3 of them the `security -> CORRECTNESS/HIGH` signature from the live Debug
failure — but never decisive there.

## 2. Fixtures

Five deterministic bug classes, each in three states: `prefix` (bug present), `p` (correct
modest fix, PROVEN), `n` (plausible-but-wrong fix, still broken).

| id | bug class | correct fix |
|---|---|---|
| G1-prune | mutation during iteration (`RuntimeError`) | iterate a copy |
| G2-export | lossy ASCII encoding | stop transcoding |
| G3-session | naive vs aware `datetime` | compare in UTC |
| G4-upload | over-broad `except` swallowing failure | catch the specific error, return False |
| G5-leaderboard | numeric sort done lexicographically | sort numerically |

**Freshly authored. None is reused from Phase 3B Stage 1, and none was selected because of
a Stage 1 outcome** — Stage 1's four classes (ZeroDivisionError, off-by-one,
order-of-operations, mutable default) are deliberately excluded. Docstrings are neutral;
none narrates its own bug, so the Phase 1 fixture-prose confound stays isolated.

Fixture source lives in string literals in `experiments/phase4c/fixtures.py` because
`ruff check .` scans the whole repository and the `n` variants are wrong on purpose.

**Offline verification gate, free, before any paid call.** Every fixture must satisfy all
four or the experiment does not run: `prefix` reproduction FAILS; `p` reproduction PASSES;
`p` full suite GREEN; `n` reproduction STILL FAILS. Condition four is load-bearing — a
negative control that quietly got fixed would silently become a second positive case.

## 3. Design

5 fixtures x 2 variants x 2 replicates = **20 trials = 60 paid lens calls.**

Two replicates rather than three: Stage 1 showed the effect is concentrated per fixture and
near-deterministic within one (3/3 on the affected fixture, 0/3 elsewhere), so fixture
breadth buys more than repetition. Order is shuffled per replicate under seed 20260902.

**One set of calls scores both arms.** R-a is merge/gate-only, so the identical stored
defects are scored twice and the A/B contrast carries no sampling error:

- **Arm A** — current semantics: any CRITICAL/HIGH defect blocks.
- **Arm B** — R-a: `off_lens(d) := d.lens in LENS_DIMENSION and d.category != LENS_DIMENSION[d.lens]`.
  Off-lens defects are still recorded and reported; they carry no blocking authority. A
  defect with no lens, or from the automated gates, is never off-lens and always blocks.

`verdict.gate(..., automated_passed=True, ...)` is held constant. On the N controls the
real pytest gate would fail and block regardless of what a lens said, which would mask the
effect under test. Registered modelling choice; `gate` takes the flag as a parameter, so no
semantics change.

**R-a is not implemented.** It exists only as an offline scoring function in the harness.

## 4. Metrics

- **Primary (benefit):** on the 10 **P** trials, false-unverified under Arm A vs Arm B. A
  trial with `A = UNVERIFIED, B = OK` is a fixed false-unverified.
- **Guardrail (safety):** on the 10 **N** trials, blocking under Arm A vs Arm B.
- **Recorded:** every defect's lens/category/severity, off-lens and on-lens blocker counts,
  per-trial verdicts under both arms, schema failures, elapsed time.

The REJECT denominator is **N trials where Arm A blocked**. Where A already returned OK,
R-a cannot make matters worse and the trial is uninformative for safety.

## 5. Decision rules

- **REJECT (hard, zero tolerance).** Any N trial where Arm A blocked and Arm B returned OK.
  One occurrence rejects the rule, and the batch stops immediately.
- **BENEFIT SHOWN.** Zero REJECT events and at least one P trial fixed. Subject in full to
  section 0: this is Debug-path benefit evidence and authorizes no implementation.
- **INCONCLUSIVE.** Zero REJECT events and zero P fixes.

Written before the first paid call and not to be edited afterward.

**Conservatism, stated in advance.** In production the Debug Agent's proof gate blocks a
still-broken fix *before* AgentGate ever runs, so Class N is synthetic and real-world
false-pass exposure on this path is lower than modelled here. The design is deliberately
harsher than reality.

## 6. Cost

Basis: Phase 3B Stage 1 measured **$0.005228 per lens call** on Debug-shaped fixtures with
this exact judge model (36 calls, $0.1882).

| | |
|---|---|
| expected | 60 x $0.005228 ~= **$0.314** |
| worst realistic (10% of calls reaching the 1600 cap) | ~= **$0.388** |
| **hard ceiling** | **$0.40**, enforced by `BudgetController.planned_budget` |

## 7. Stop conditions

1. **Fixture verification fails** — do not run at all. Free.
2. **Safety** — one candidate-induced false pass on an N trial: stop immediately, REJECT.
3. **Budget** — `BudgetController` raises at $0.40: stop, report partial.
4. **Contamination** — more than 15% of lens calls returning schema errors voids the
   measurement. A live risk: Phase 4A recorded deterministic Sonnet truncation on
   `security-04-clean`. If it appears here it is **recorded, not fixed** — the answer-budget
   question is a separate registration and must not be bundled into this one.

## 8. Frozen — must not change

Lens prompts (`LENSES`), `RESPONSE_INSTRUCTION`, `judge.py`, `schema.py`, `rubric.py`,
`verdict.py`, `eval/dataset.py`, the benchmark, and model config. No benchmark run is part
of this experiment.

---

# Result — 2026-09-02

**Outcome: INCONCLUSIVE. R-a is safety-clean on this batch, benefit unproven, and is NOT
authorized for production.**

This section supersedes the header line "No paid call has been made under it". Sections
0-8 are the registered text and are unchanged; nothing in them was edited, relaxed or
reinterpreted after the fact.

| | |
|---|---|
| Executed | 2026-09-02 |
| HEAD at execution | `b61a2cd752aa67915bf0ce0670c755f72a6b85f5` |
| Judge model | `claude-sonnet-5` |
| Trials | **15 of 20 planned** (partial batch) |
| Paid lens calls | **45 of 60 planned** |
| Spend | **$0.400806** |
| Schema failures | 2 / 45 calls (4.4%) |
| Raw artifact | `experiments/phase4c/phase4c_batch.jsonl` — 15 records, one per trial |
| Benchmark runs | **none.** `run_batch.py` passes `conn=None, run_id=None`; no row was written to `.engine/state.db` and no `BASELINE.md` row exists or should exist for this experiment |

## R.1 — Why the batch is partial

Registered stop condition 3 fired: `BudgetController` raised at the $0.40 ceiling after 45
calls. Not a safety stop and not a contamination void — the batch ran out of registered
budget. Replicate 1 completed in full (10/10 trials); replicate 2 reached 5/10. Missing:
`G1-prune/n r2`, `G3-session/p r2`, `G3-session/n r2`, `G5-leaderboard/p r2`,
`G5-leaderboard/n r2`. Order was the registered seed-20260902 shuffle, so the truncation is
a budget cut at a fixed point in a pre-committed order, not a selection on outcome.

**The section 6 cost basis was low by 1.70x.** Measured **$0.008907 per lens call**
($0.400806 / 45) against the registered $0.005228 carried from Phase 3B Stage 1. At the
measured rate the full 60-call design costs ~$0.534 — above the $0.40 ceiling, so
truncation was arithmetically certain from the first call. Any successor batch must be
re-planned on $0.008907/call and cannot reuse the Stage 1 figure.

## R.2 — Decision, against the rules exactly as registered

Section 5, unedited: REJECT on any N trial where Arm A blocked and Arm B returned OK;
BENEFIT SHOWN on zero REJECT events and at least one P trial fixed; INCONCLUSIVE on zero
REJECT events and zero P fixes.

| metric | registered role | result |
|---|---|---|
| N trials where Arm A blocked, Arm B returned OK | REJECT (hard, zero tolerance) | **0**, denominator 7 of 7 informative |
| P trials with `A = UNVERIFIED, B = OK` | primary (benefit) | **0** of 8 |
| Any per-trial verdict change A -> B | — | **0** of 15 |

Zero REJECT events and zero P fixes: **INCONCLUSIVE**. Per section 0 this leaves Phase 4
itself INCONCLUSIVE and unamended; the Run 44 status recorded in `BASELINE.md` — R-a
safety-clean, benefit unproven — is unchanged, not upgraded.

Arm totals: P n=8, blocked A=2 B=2; N n=7, blocked A=7 B=7. The A/B contrast carries no
sampling error by construction (one set of calls scores both arms), so there is no
dispersion estimate on the contrast itself; the uncertainty that matters is the per-trial
event rate, and it is wide — see R.4.

## R.3 — Mechanism: R-a had no purchase on this corpus

The aggregate zero is not the finding. The mechanism is:

- **7 off-lens defects were emitted, all 7 on N trials, 0 on P trials.** All 7 carried
  category `CORRECTNESS` (5 from the `security` lens, 2 from `code-quality`); 6 were
  blocking severity and 1 was MEDIUM. Four are the `security -> CORRECTNESS/HIGH`
  signature of the live Debug failure that originated the rule.
- **Zero sole-blocker trials in the entire batch.** Every N trial carrying an off-lens
  blocker also carried at least one on-lens blocker, so R-a could not unblock it — which is
  why the safety guardrail is clean, and it is clean for a structural reason rather than
  because the rule was tested and held.
- **Neither of the two P-trial false-unverifieds was off-lens-caused**, so R-a could not
  have fixed either even in principle. `G2-export/p r1` blocked on a genuine on-lens
  finding (`security` lens, SECURITY/HIGH, CSV-injection quoting). `G3-session/p r1`
  returned zero defects and blocked because `verdict.gate` failed closed on a `correctness`
  schema error — the same fail-closed shape as `security-04-clean` in `BASELINE.md`, and a
  class of false-unverified no blocking-authority rule can address.

Against the section 1 prior of **25% sole-blocker exposure on Debug-shaped fixtures**
(Phase 3B Stage 1), this batch observed **0 of 15**. The two fixture sets are disjoint by
design (section 2), so this is a between-corpus difference, not a repeat measurement that
contradicts Stage 1.

## R.4 — Limits

- **Not a clearance.** 0 events on 7 informative N trials bounds the candidate-induced
  false-pass rate at roughly **43%** (rule of three, one-sided 95%); 0 of 8 P trials bounds
  the P-side sole-blocker rate at roughly **38%**. A batch this size cannot exclude a large
  effect in either direction.
- **Guardrail untested, not passed.** With zero sole-blocker trials, the safety guardrail
  was never presented with a case where the arms could differ.
- **Schema failures are recorded, not fixed** (stop condition 4): 2 of 45 calls, 4.4%,
  below the 15% contamination threshold, so the measurement stands. One of the two
  (`G3-session/p r1`, `correctness`) is directly responsible for one of the two P-trial
  false-unverifieds.
- **No production authorization.** Section 0 governs: even BENEFIT SHOWN would not have
  authorized R-a, and this result is weaker than that. R-a remains unimplemented — an
  offline scoring function in `experiments/phase4c/run_batch.py` and nothing more.
- No `src/engine/` file, dataset, lens prompt, model config or verifier semantic was
  changed by this experiment.
