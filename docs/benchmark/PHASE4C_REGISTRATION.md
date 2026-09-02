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
