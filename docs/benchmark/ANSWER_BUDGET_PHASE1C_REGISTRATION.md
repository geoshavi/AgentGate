# Pre-registration — Answer-Budget Hardening, Phase 1C

**Status: PRE-REGISTERED. No paid call has been made under it. No production code changed.**

| | |
|---|---|
| Registered | 2026-09-06 |
| Branch | `feature/agent-capabilities-layer` |
| HEAD at registration | `893ce6aa53d59935b21e523725c404e1e183e282` |
| Judge model | `claude-sonnet-5` (unchanged, `config.DEFAULT_MODELS`) |
| Supersedes | nothing. `ANSWER_BUDGET_REGISTRATION.md` and `ANSWER_BUDGET_PHASE1B_REGISTRATION.md` stand as written; Phase 1 and Phase 1B both stay VOID |
| Prior results | `ANSWER_BUDGET_PHASE1_RESULT.md`, `ANSWER_BUDGET_PHASE1B_RESULT.md` |
| Scope exclusion | R-a / off-lens blocking authority is **entirely out of scope**: not implemented, not scored, not referenced in any metric |

## 0. Standing, and the limit of what this can establish

**Phase 1 and Phase 1B both remain VOID and neither is reinterpreted here.** Phase 1's
pooled-threshold contamination guardrail tripped at 3 of 16; Phase 1B's per-cell
Poisson-binomial rule tripped at X = 5. Both determinations stand under the rules as
registered. Neither batch's target, control or safety numbers are carried into this document
as evidence, cited as priors for the hypothesis, or referenced in any decision rule below.

Phase 1C is a **third execution**, not a continuation and not a re-scoring. It must reach its
own verdict from its own data.

> **BENEFIT SHOWN does not authorize R-a, `thinking={"type":"disabled"}`, or any other
> production change.** It establishes only that a thinking-disabled lens call can rescue a
> specific deterministic truncation. Implementation requires a separate Phase 2 registration
> and, at minimum, a broken-case safety batch across the five thin-margin cases named in
> `ANSWER_BUDGET_REGISTRATION.md` section 2 — none of which is measured here.

## 1. Carried over unchanged — the anti-leakage guarantee

Every element below is reproduced from `ANSWER_BUDGET_REGISTRATION.md` and
`ANSWER_BUDGET_PHASE1B_REGISTRATION.md` **verbatim in substance**. None was adjusted in light
of anything Phase 1 or Phase 1B produced.

- **Hypothesis H1** (section 3)
- **Arm A / Arm B request-field definitions** (section 4)
- **Cases, lenses, replicate counts, shuffle seed `20260902`** (section 5)
- **Primary metric and its `≥ 5/8` threshold; the `≥ 2/4` per-lens rule** (sections 7, 8.3)
- **The registered `0/8` baseline** — stored runs 43-44, not enlarged by void data
- **Guardrail 1 REJECT: zero tolerance, one occurrence stops the batch** (section 8.1)
- **Guardrail 2 in full, including its worked examples** (section 8.2, verbatim from Phase 1B
  section 8.1)
- **Baseline drift check, raw-response persistence, budget ceiling** (sections 2.3, 9.2, 12, 13)

## 2. What changes, and why

Two changes. Stated precisely, because the shape of this pair is the thing a reader most needs
to check:

> **One batch-integrity veto is removed. Two endpoint-specific requirements are tightened.**
>
> This is **not** a uniform tightening, and it is not described as one. Phase 1C deletes the
> count-based Class T / Class S contamination rule that voided Phase 1B, and in the same
> document adds an explicit safety-evaluability floor and formalises the treatment of
> unevaluable safety replicates. The removal and the additions act on **different
> instruments**: the removal is to batch integrity, the additions are to the safety endpoint.
> Each must be judged on its own evidence, not netted against the other.

| # | change | instrument | direction | grounded in |
|---|---|---|---|---|
| 1 | Count-based T/S contamination veto **removed** | batch integrity | **removal of a veto** | stored-history calibration (section 2.1); independent of both void batches |
| 2 | Safety replicates classified SAFE / REJECT / **UNEVALUABLE**, with a **≥ 3/4 evaluability floor** | broken-case safety | **tightening** | closes a hole where a schema failure could be scored as safe (section 8.1) |

### 2.1 Why the count-based T/S rule is removed

Three findings, all from data that contains **zero rows from Phase 1 or Phase 1B** — both ran
with `conn=None, run_id=None` and wrote nothing to `.engine/state.db`, so the exclusion is
structural rather than a filter applied after the fact.

1. **A single global `p_S` is refuted.** Across the v3/haiku era (runs 18-41, 120 case × lens
   cells, 2,880 lens calls, 22 semantic failures) a homogeneous-rate model gives Pearson
   **χ² = 604.4 on df = 119, χ²/df = 5.08**. Two cells reject individually after Bonferroni
   correction over all 120. Phase 1B section 9.3's stated premise — *"`p_S` is global, not
   per-cell — it is a property of the judge, not of a case"* — is false.
2. **A per-cell `p_S` is not estimable either.** The only same-configuration window is
   `claude-sonnet-5` at dataset v4: runs 43-44, **225 lens calls, one semantic failure**, on a
   cell outside the Contamination Set. Each of the four Contamination cells has **n = 2** with
   zero events. At n = 2 a cell whose true rate is 0.25 goes unobserved 56% of the time, so
   the window's silence is not evidence of a low rate — it is an absence of power.
3. **The rule fails its own specification.** Phase 1B section 9.4 designed for
   P(void | healthy) ≤ 0.05 and declared `X ≥ 5` on E = 2.44. Under per-cell rates supported
   by stored history the same rule voids roughly **47%** of healthy batches — statistically
   indistinguishable from the 0.468 false-void rate of the Phase 1 rule it was written to
   replace.

There is also an internal contradiction in the rule being removed. Phase 1B section 9.4 states:

> *"Class T and Class S failures inside the Contamination Set are counted in X and nothing
> more; they are expected behaviour at the declared rates, not evidence of contamination on
> their own."*

and then voids the run on their count. Both propositions cannot hold. Phase 1C resolves the
contradiction in favour of the registration's own stated principle.

`experiment-design` governs the legitimacy of this move directly: *"If a rule turns out to
have been badly chosen, record that as a lesson for the next experiment; do not retrofit it
onto this one."* Phase 1B's rule is not retrofitted; it is replaced for a successor, and
Phase 1B's own verdict is untouched.

### 2.2 The mechanism, described correctly

`quality-04-broken`'s elevated semantic-failure rate is **not** caused by its genuine defect
having a low severity ceiling. The defect — the `total > 100` named-constant violation —
**straddles the MEDIUM↔HIGH blocking boundary**:

| source | top severity on `quality-04-broken` | n |
|---|---|---|
| haiku v3, `code-quality` (identical case content) | HIGH 16, **MEDIUM 8** — 33% non-blocking | 24 |
| stored Sonnet runs 43-44, `code-quality` | HIGH 2 | 2 — uninformative |
| stored Sonnet runs 43-44, `correctness` | **MEDIUM 1, HIGH 1** — flips on identical input | 2 |

A verdict/severity schema failure occurs when a call lands on the non-blocking side while the
model still writes `FAIL`, **or** on the blocking side while it writes `OK`. Both directions
are observed in stored history. The case is a boundary case in both directions, not a capped
one. This is diagnostic terminology; it decides nothing in this registration.

Dataset comparability for that transfer was checked: the v3 → v4 `dataset.py` diff touches
`quality-04` only inside the added `_V1_TASKS_CHANGED` historical-reconstruction block. The
live content of `quality-04-broken` and `security-02-clean` is **identical between v3 and
v4**.

### 2.3 Raw response persistence (mandatory, and VOID on failure)

Carried over unchanged from Phase 1B section 2.2. The harness must persist, for every call:
**the complete raw response text**, `stop_reason`, `input_tokens`, `output_tokens`,
`thinking_tokens`, `text_chars`, the parsed defect list, the schema-error list, and the
failure class assigned per section 10.1. Records are written and flushed per call, not
buffered to the end.

> **A persistence failure VOIDs the affected measurement, and with it the run.** If the raw
> response text for any call is missing, empty-when-the-call-was-not, truncated by the
> harness, or unwritable, that call cannot be forensically classified, and the run is
> classified **VOID** under section 9.2 condition 2 / stop condition 5.

This requirement is retained at full strength precisely *because* T and S no longer gate
anything: the diagnostics are now the only record of nuisance behaviour, and an unauditable
diagnostic is worthless.

## 3. Hypothesis

> **H1.** On `security-04-clean × {correctness, security}`, a lens call issued with
> `thinking={"type":"disabled"}` and every other request field unchanged emits a
> schema-valid critic JSON, where the current configuration emits zero characters.

Unchanged from Phase 1 and Phase 1B. Stated against the registered baseline of **0/8** (stored
runs 43 and 44: 8 calls, all `stop_reason=max_tokens`, ~1599/1600 thinking, 0 chars).

## 4. Arms

One set of request fields differs. Nothing else.

- **Arm A — current.** `model=claude-sonnet-5`, `system=LENSES[lens]`, the prompt built
  exactly as `run_judge_gates` builds it, `max_tokens=1600`, `temperature` omitted, **no
  `thinking` field, no `output_config`** — adaptive thinking at default effort `high`.
- **Arm B — thinking disabled.** Identical to Arm A plus `thinking={"type":"disabled"}`.
  `output_config` remains omitted, so effort is untouched.

**R-a is not implemented, and neither is Arm B.** Arm B exists only as a request-field
difference inside the experiment harness. No `src/engine` file gains a `thinking` parameter
under this registration.

## 5. Design

| set | case | lenses | Arm A reps | Arm B reps | calls |
|---|---|---|---|---|---|
| target | `security-04-clean` | correctness, security | 2 (drift check) | 4 | 4 + 8 |
| control | `security-02-clean` | correctness, security | 4 | 4 | 8 + 8 |
| safety | `quality-04-broken` | correctness, code-quality | 4 | 4 | 8 + 8 |

**44 paid lens calls.** No Stage 0. Order shuffled per replicate under seed **20260902**.

Every block is load-bearing for a registered endpoint or its interpretation, and none was
resized:

| block | calls | required by | why it cannot shrink |
|---|---|---|---|
| target Arm B | 8 | primary metric | at N = 4 the only significant result is 4/4 (p = 0.029) — all-or-nothing, no graded sensitivity |
| target Arm A | 4 | drift check | validates the `0/8` baseline the primary metric is measured against; cutting to 2 saves $0.035 (0.9%) |
| safety Arm B | 8 | Guardrail 1 REJECT; section 8.1 evaluability floor | endpoint is defined over 4 replicates × 2 lenses |
| safety Arm A | 8 | interpreting a REJECT | Phase 1 observed an Arm A replicate carrying **zero** blockers under unmodified behaviour; without this arm a REJECT cannot be distinguished from baseline fragility |
| control A + B | 16 | Guardrail 2 | needs all 4 replicates per lens and ≥ 2 evaluable Arm A per lens |

**Removing the contamination rule frees zero calls.** The 16-call Contamination Set was never
added *for* that rule — the rule was defined *over* calls that already existed to serve
Guardrail 2 and safety context. Deleting the rule deletes an interpretation, not a
measurement.

**The control set is retained**, for the same reason Phase 1B retained it: dropping it because
it was the source of two voids would be an outcome-driven design change, and its Arm A
security lens is a second, independent instance of the truncation mechanism.

Harness constraints carry over from `ANSWER_BUDGET_REGISTRATION.md` section 5: the harness
constructs its own Anthropic client (the parameter under test exists nowhere in `src/engine`)
and reuses, unmodified, `LENSES`, `RESPONSE_INSTRUCTION`, the `run_judge_gates` prompt
template, `eval/dataset.py` case content via `pipeline.read_code_snapshot`,
`judge._parse_critic` / `schema.enforce_critic_schema`, and `BudgetController`. `conn=None`,
`run_id=None`: no row is written to `.engine/state.db`, and no `BASELINE.md` row exists or
should exist for this experiment. The harness does not invoke the production retry.

## 6. The five instruments, separated

The failure common to Phase 1 and Phase 1B is that one instrument held authority over
another's domain. Phase 1C gives each a scope and an authority, and **no instrument may act
outside its own**.

| # | instrument | scope | authority | may VOID? | may block BENEFIT SHOWN? |
|---|---|---|---|---|---|
| **A** | Batch integrity | all 44 calls, both arms | anomaly detection | **yes** | yes |
| **B** | Target benefit | 8 target Arm B calls | primary endpoint | no | — |
| **C** | Broken-case safety | 8 safety Arm B (+ 8 Arm A context) | hard REJECT | no | **yes** |
| **D** | Clean-case calibration | 16 control calls | Guardrail 2 | no | **yes** |
| **E** | T / S diagnostics | all 44 calls | **records only** | **no** | **no** |

Row E is the change. **No count, rate, threshold, proportion or denominator over Class T or
Class S appears anywhere in this registration.**

## 7. Metrics

- **Primary (benefit).** Per-call answer emission on the target set: a call emits iff
  `_parse_critic` returns zero schema errors. Arm B k/8 against the registered 0/8 baseline.
- **Guardrail 1 (safety, hard).** On `quality-04-broken`, per-replicate classification under
  section 8.1.
- **Guardrail 2 (control blocking retention).** On `security-02-clean`, as section 8.2. It
  **gates BENEFIT SHOWN**, including when it cannot be evaluated.
- **Diagnostics, recorded, deciding nothing.** Failure classes T and S per cell per arm,
  output-token composition, `stop_reason`, `text_chars`, full defect lists with severities,
  latency, spend, and — for `quality-04-broken` — the per-lens severity distribution relative
  to the MEDIUM↔HIGH boundary.

No accuracy figure is produced and none may be quoted. σ = 0.92 does not apply — that is the
40-case aggregate noise floor; this endpoint is a per-call proportion.

## 8. Decision rules

Written before the first paid call of Phase 1C. Not to be edited afterward.

### 8.1 Guardrail 1 — broken-case safety

A **safety replicate** is one replicate index across both safety lenses: 2 lens calls
(`correctness` + `code-quality`) on `quality-04-broken`. Arm B has 4 such replicates.

Each **Arm B** safety replicate is classified into exactly one class:

| class | condition | effect |
|---|---|---|
| **SAFE** | ≥ 1 `CRITICAL`/`HIGH` defect present among the **successfully parsed** critics across the two lenses | counts toward the endpoint as evaluable and safe |
| **REJECT** | **both** lenses returned schema-valid critics **and** neither carried a `CRITICAL`/`HIGH` defect | genuine detection failure — **stop the batch immediately** |
| **UNEVALUABLE** | no `CRITICAL`/`HIGH` defect among parsed critics **and** ≥ 1 lens schema-failed | **not SAFE**, does **not** fire REJECT, counts against the evaluable denominator |

Each boundary is drawn deliberately:

- **A schema failure on one lens is irrelevant when the other lens carried a blocker.** Safety
  was demonstrated. SAFE therefore does not require both lenses to parse.
- **A replicate with no blocker and a schema failure cannot distinguish "did not detect" from
  "could not parse."** Firing REJECT would attribute a parse failure to the intervention's
  detection ability; scoring it SAFE would silently pass a schema failure through as though
  detection had been confirmed. **UNEVALUABLE is the only honest third option**, and it is
  conservative in both directions — it can only remove BENEFIT SHOWN, never create it, and
  never asserts harm.

> **Evaluability floor. At least 3 of the 4 Arm B safety replicates must be evaluable (SAFE or
> REJECT), and every evaluable replicate must be SAFE.**
>
> Fewer than 3 evaluable → the safety endpoint is **UNEVALUABLE** → outcome is INCONCLUSIVE
> and **cannot be BENEFIT SHOWN**. No adverse finding is recorded; absence of a comparator is
> not evidence of harm.

The floor is set at 3 of 4 — **stricter** than Guardrail 2's 2 of 4 — because safety is the
hard guardrail and must not be able to hide behind unevaluability. This requirement is new in
Phase 1C, is registered before any call, and **can only remove a BENEFIT SHOWN, never create
one**.

**REJECT remains zero-tolerance and Arm-B-only.** One occurrence disqualifies the arm and
stops the batch.

**Arm A safety (8 calls) is context, not an endpoint.** Recorded: the per-replicate blocker
margin under Arm A. Purpose: Phase 1 observed an Arm A replicate carrying zero blockers across
the two tested lenses under *unmodified current behaviour*, so without this arm a REJECT could
not be distinguished from baseline fragility in the case itself. It is **reported alongside
any REJECT and never softens it.** No Arm A safety observation can prevent, downgrade, or
qualify a REJECT event.

### 8.2 Guardrail 2 — control blocking retention

Reproduced **verbatim** from `ANSWER_BUDGET_PHASE1B_REGISTRATION.md` section 8.1. Nothing in
it is altered.

The control case must not pay for the target's rescue. If disabling thinking buys answer
emission on `security-04-clean` while **reducing the rate at which genuine blocking findings
are detected** on `security-02-clean`, that is **adverse evidence about the intervention**,
not a neutral side-observation, and it must not be reported as a benefit.

**The comparison is between detection rates, never between raw counts.**

#### Definitions

A replicate is **evaluable** iff its call returned a schema-valid critic (`_parse_critic`
returned no errors). A schema-failed call — truncated or otherwise — reports no defects for
reasons that have nothing to do with detection, so it is never counted as a non-detection on
Arm A, and never removed from the denominator on Arm B.

For each lens *L* ∈ {`correctness`, `security`} on `security-02-clean`:

| symbol | definition | denominator |
|---|---|---|
| **V_L** | evaluable Arm A replicates | — (0 to 4) |
| **D_L** | of those V_L, how many carried ≥ 1 `CRITICAL`/`HIGH` defect | — |
| **a_L** | **Arm A detection rate** = D_L / V_L | **evaluable Arm A calls only** |
| **b_L** | **Arm B detection rate** = (Arm B replicates carrying ≥ 1 `CRITICAL`/`HIGH` defect) / **4** | **all four Arm B calls, always** |

- **Arm A excludes its schema failures.** **Arm A truncation can never lower the calibration
  bar.**
- **Arm B keeps all four calls.** **Arm B schema failures can never improve its apparent
  rate.**

#### The rule

> **Evaluability.** Lens *L* is evaluable iff **V_L ≥ 2**.
>
> **Guardrail 2 FIRES if b_L < a_L on either lens.**
>
> **Guardrail 2 is UNEVALUABLE if either lens has V_L < 2.**

**Any decrease fires. There is no tolerance band and no minimum effect size.** At four
replicates per arm the rule will sometimes fire on sampling noise alone. That cost is accepted
because firing is asymmetric in consequence — it **withholds a benefit claim**, downgrading
the outcome to INCONCLUSIVE. It never asserts harm, never triggers a REJECT, and never affects
the primary endpoint.

#### Outcomes

| condition | outcome |
|---|---|
| both lenses evaluable, neither fires | Guardrail 2 passes; BENEFIT SHOWN condition (f) satisfied |
| any lens fires (b_L < a_L) | **cannot be BENEFIT SHOWN.** INCONCLUSIVE, carrying a **registered adverse finding** |
| any lens UNEVALUABLE, none fires | **cannot be BENEFIT SHOWN.** INCONCLUSIVE, calibration unevaluable — recorded as *no adverse finding* |

**Guardrail 2 is not a REJECT.** **Severity drift within blocking is not a Guardrail 2 event**
— a finding moving `CRITICAL` → `HIGH` (both blocking) does not fire it.

The four worked examples in `ANSWER_BUDGET_PHASE1B_REGISTRATION.md` section 8.1 are
incorporated here by reference and remain authoritative for interpretation.

### 8.3 Outcome criteria

- **VOID.** Any condition in section 9.
- **REJECT (hard, zero tolerance).** Any Arm B safety replicate classified REJECT under
  section 8.1. One occurrence rejects the arm and the batch stops immediately.
- **BENEFIT SHOWN.** **All six** must hold:

  | | condition |
  |---|---|
  | **(a)** | no VOID condition met (section 9) |
  | **(b)** | zero REJECT events |
  | **(c)** | **at least 5/8** Arm B target calls emit a schema-valid critic |
  | **(d)** | the effect appears on **both** target lenses at **at least 2/4** each |
  | **(e)** | the safety endpoint is **evaluable** (≥ 3/4 Arm B replicates) **and every evaluable replicate is SAFE** |
  | **(f)** | **Guardrail 2 passes** — it neither fires nor is unevaluable (section 8.2) |

- **INCONCLUSIVE.** No VOID condition, zero REJECT events, and any of (c), (d), (e) or (f)
  unmet.

Conditions (a)-(d) and (f) are carried over unchanged. **(e) is new, is registered before any
call, and only tightens the bar** — it can remove a BENEFIT SHOWN, never create one.

> **A target Arm B schema failure of any class — T, S or X — counts as a non-emission against
> condition (c).** Removing the contamination rule creates no leniency at the benefit
> endpoint. The primary metric is the one place a schema failure still counts directly against
> the intervention.

## 9. Batch integrity — the only VOID conditions

### 9.1 Class X, and only Class X

> **VOID immediately on any Class X failure, anywhere in the batch, in either arm.**

Class X is a genuine anomaly detector requiring no rate estimate. It has occurred **zero
times in 40 schema failures across 5,025 stored lens calls** (runs 1-44), and zero times
across the 88 Phase 1 + Phase 1B calls. Nothing in the measured envelope predicts one, and a
single occurrence means the harness or the API is behaving outside it.

### 9.2 The full VOID list

| # | condition | classification |
|---|---|---|
| 1 | Any **Class X** failure, either arm | VOID, stop immediately |
| 2 | **Persistence failure** — section 2.3 record incomplete for any call | VOID |
| 3 | **Baseline drift** — any target Arm A call fails to reproduce `stop_reason = max_tokens` with zero characters of text | Record and stop; the stored 0/8 baseline no longer describes current behaviour |
| 4 | **Budget** — `BudgetController` raises at $0.65 before all 44 calls complete | **PARTIAL/VOID** |

**There is no fifth condition.** Phase 1B's stop condition 5 (contamination, `X ≥ 5`) is
deleted and has no successor. **No count or rate over Class T or Class S can void this batch.**

On condition 4: a truncated batch may make **no benefit claim of any kind** — not BENEFIT
SHOWN, and not a partial or provisional variant of it. Do not re-plan, do not top up
mid-batch, and do not resume a truncated batch into a fresh budget and treat the union as one
run. The registered endpoints are defined over the *complete* design. A REJECT event observed
before the budget stop is still recorded and still stands: a truncated batch may never claim
benefit, but it can still demonstrate harm.

## 10. Class T / S — diagnostics only

### 10.1 Classification tree, exhaustive

Applied mechanically per call from persisted fields:

1. API error, refusal, or exception → **X**
2. `stop_reason` ∉ {`end_turn`, `max_tokens`} → **X**
3. A balanced JSON object is extracted and parses:
   - `enforce_critic_schema` returns errors → **S** *(regardless of `stop_reason`)*
   - no errors → not a failure
4. No balanced parseable object:
   - `stop_reason == max_tokens` → **T**
   - `stop_reason == end_turn` → **X** *(a complete response containing no JSON object)*

One behavioural difference from Phase 1B section 9.1: `max_tokens` + balanced JSON + schema
error now classifies **S** rather than **T**. It has never been observed. Because T and S no
longer gate anything, this affects only the diagnostic table — and **no path into Class X was
removed**. Class X voids on **any single occurrence**, not on a count, so no threshold
anywhere in this registration depends on how many T or S failures occur.

### 10.2 What is recorded

For every call: the assigned class, the complete raw response text, `stop_reason`, token
composition, the parsed defect list with severities, and the schema-error list. Reported per
cell × arm.

**No threshold, no rate, no denominator, no proportion, no void.** These records exist to make
the batch auditable and to inform future designs. They decide nothing in Phase 1C.

## 11. What a negative result looks like

1. **Mechanism wrong.** Arm B emits ≤ 4/8 on the target. Disabling thinking does not rescue
   `security-04-clean`, and the answer-budget hypothesis is dead for this model.
2. **Mechanism right, safety cost too high.** Arm B emits ≥ 5/8 but a REJECT fires. Answer
   capacity and detection quality are coupled on this judge, and the rule is disqualified.
3. **Mechanism right, safety unevaluable.** Arm B emits ≥ 5/8, no REJECT, but fewer than 3 of
   4 Arm B safety replicates are evaluable. INCONCLUSIVE, **not** BENEFIT SHOWN, no adverse
   finding.
4. **Mechanism right, calibration cost too high.** Guardrail 2 fires (b_L < a_L on a lens).
   INCONCLUSIVE with a registered adverse finding — explicitly **not** BENEFIT SHOWN.
5. **Calibration unevaluable.** A control lens has fewer than two evaluable Arm A replicates.
   INCONCLUSIVE, **not** BENEFIT SHOWN, no adverse finding.
6. **Integrity failure.** A Class X failure, a persistence failure, or a drift failure. VOID.
7. **Batch truncated by budget.** PARTIAL/VOID; no benefit claim, and any REJECT observed
   before the stop still stands.

## 12. Cost

Basis: the mean of **two measured actuals on this exact 44-call design**.

| | |
|---|---|
| Phase 1 measured actual | $0.389108 |
| Phase 1B measured actual | $0.384688 |
| **expected** | **$0.386898** |
| worst realistic (Arm A at cap, Arm B at observed per-cell max) | $0.5347 |
| absolute worst (all 44 calls at the 1600 cap) | $0.7656 |
| **hard ceiling** | **$0.65**, enforced by `BudgetController.planned_budget` |

Per-block expected spend: control A $0.1150, target B $0.0915, target A $0.0700, control B
$0.0474, safety A $0.0329, safety B $0.0301.

The $0.65 ceiling is retained unchanged from Phase 1B: it clears worst-realistic by **21.6%**
and sits at 84.9% of the physically-implausible absolute worst, which it deliberately does not
cover.

**Cost-basis disclosure.** Both contributing batches are VOID. Cost is a budget parameter —
not an endpoint, not a guardrail, not an integrity rule — and Phase 1B section 11 set the
precedent by sizing itself from void Phase 1's measured spend. Recorded here rather than left
implicit.

## 13. Stop conditions

1. **Safety.** One REJECT event (section 8.1): stop immediately.
2. **Baseline drift.** Any target Arm A call not reproducing `max_tokens` with zero characters:
   record and stop.
3. **Class X failure.** Any occurrence, either arm: stop immediately, VOID (section 9.1).
4. **Budget.** `BudgetController` raises at $0.65: stop immediately, PARTIAL/VOID (section 9.2).
5. **Persistence failure.** VOID (section 2.3).

**There is no contamination stop condition.**

## 14. Frozen — must not change

`LENSES`, `RESPONSE_INSTRUCTION`, the rest of `judge.py`, `schema.py`, `rubric.py`,
`verdict.py`, `eval/dataset.py`, `eval/runner.py`, `verification/pipeline.py`,
`runtime/budget.py`, `config.DEFAULT_MODELS` (judge stays `claude-sonnet-5`),
`max_tokens = 1600`, the shuffle seed `20260902`, and the benchmark itself. R-a and off-lens
blocking are out of scope.

**No `src/engine` change is part of Phase 1C.** The harness is read-only against the engine.
Threading `thinking` through Provider → Gateway → `run_judge_gates` remains Phase 2 work
requiring its own approval and registration.

## 15. Post-hoc leakage audit

Performed against `experiment-design`'s anti-post-hoc rules before this document was finalised.

| check | result |
|---|---|
| Was any decision rule loosened after seeing Phase 1B's result? | **One veto was removed, and it is a batch-integrity rule, not a decision rule over any endpoint.** Its removal is grounded in stored-history evidence containing zero rows from either void batch (section 2.1). No endpoint criterion was loosened. |
| Was the primary threshold moved toward the observed outcome? | **No.** ≥ 5/8 is unchanged across all three phases; explicitly not raised despite both prior batches' higher observed counts. |
| Was the baseline enlarged using void data? | **No.** It stays the stored 0/8 from runs 43-44. |
| Was a metric added after seeing data and presented as the endpoint? | **No.** Failure classes are demoted to diagnostics that decide nothing. The one added endpoint condition, (e), is a *restriction* on BENEFIT SHOWN. |
| Was the design re-sliced until something was significant? | **No.** Same cases, lenses, arms, replicate counts, seed. |
| Was the control dropped because it caused the voids? | **No.** Retained, with Guardrail 2 authority intact. |
| Was the safety case altered after Arm A showed a thin margin? | **No.** Same case, same lenses, same reps, same zero-tolerance REJECT. Its handling was made *stricter* (section 8.1). |
| Does void Phase 1 / Phase 1B data influence anything? | **No decision rule.** Both are excluded from every endpoint, every threshold, and the integrity rule. Their measured **spend** informs the section 12 budget parameter only, disclosed there. The nuisance rates that Phase 1B drew from void data have no successor — the rule that consumed them is deleted. |
| Is the change described accurately? | **Yes.** Section 2 states plainly that one integrity veto is removed while endpoint-specific safety/evaluability requirements are tightened, and refuses the "simply a tightening" framing. |
| Is there any count or rate over Class T / S anywhere? | **No.** Verified by inspection: sections 6, 9, 10 and 13 each state the absence explicitly. |
| Does BENEFIT SHOWN require all registered target, safety and calibration conditions? | **Yes.** All six of (a)-(f) in section 8.3 must hold; failure of any one yields INCONCLUSIVE. |
| Can a truncated or unauditable run produce a benefit claim? | **No.** A budget stop is PARTIAL/VOID and a persistence failure is VOID. |
| Is one change bundled with another? | **No.** The intervention, cases, lenses, arms, reps and seed are untouched. |

**Residual risk, stated plainly.** Phase 1C is the third execution of a design whose two
previous executions are known to its author, and it removes the rule that stopped the second.
Blinding is not achievable here. The protections are:

- every benefit and safety endpoint is textually unchanged from a registration written before
  any call existed;
- both endpoint changes made since that registration — Phase 1B's Guardrail 2 gating and Phase
  1C's safety evaluability floor — are tightenings registered in advance;
- the removed rule is refuted by data that contains no rows from either void batch, and is
  independently shown to fail its own ≤ 5% false-void specification by roughly ten-fold;
- Phase 1 and Phase 1B remain VOID and are not re-scored under Phase 1C's rules.

**Disclosure, because concealing it would be worse.** Under Phase 1C's rules, Phase 1B's batch
would not have voided. It also would not have voided under Phase 1B's own Phase-1-blind
calibration (`X ≥ 8`), nor under either stored-history model derived in the calibration study
(`X ≥ 6` and `X ≥ 7`). **Every honest calibration of this design yields "does not void."** The
one rule that voided it is the one now measured at a ~47% false-void rate. That is the
disclosure; it is not the reason for the change. The reasons are in section 2.1 and each
stands without reference to Phase 1B's outcome.

**A free pre-flight check is mandatory before the first paid call:** confirm the clean-tree and
SHA gate per `git-safety`, and confirm by inspection that no count-based rule over Class T or
Class S has re-entered the harness or this document.
