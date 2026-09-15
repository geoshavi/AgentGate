# Pre-registration — Answer-Budget Hardening, Phase 1B

**Status: PRE-REGISTERED. No paid call has been made under it. No production code changed.**

| | |
|---|---|
| Registered | 2026-09-02 |
| Branch | `feature/agent-capabilities-layer` |
| HEAD at registration | `5eab23ad69f78f157f9b03c66076c287416469d1` |
| Judge model | `claude-sonnet-5` (unchanged, `config.DEFAULT_MODELS`) |
| Supersedes | nothing. `ANSWER_BUDGET_REGISTRATION.md` stands as written; Phase 1 stays VOID |
| Prior result | `ANSWER_BUDGET_PHASE1_RESULT.md` |
| Scope exclusion | R-a / off-lens blocking authority is **entirely out of scope**: not implemented, not scored, not referenced in any metric |

## 0. Standing, and the limit of what this can establish

**Phase 1 remains VOID and is not reinterpreted here.** Its contamination guardrail tripped
at 3 of 16 non-target Arm A schema failures (18.75% against a 15% threshold). That
determination stands. Phase 1's target, control and safety numbers are **not** carried into
this document as evidence, are not cited as priors for the hypothesis, and do not appear in
any decision rule below.

Phase 1B is a **replication**, not a continuation. It re-runs the identical design under a
corrected integrity specification, and it must reach its own verdict from its own data.

> **BENEFIT SHOWN does not authorize R-a, `thinking={"type":"disabled"}`, or any other
> production change.** It establishes only that a thinking-disabled lens call can rescue a
> specific deterministic truncation. Implementation requires a separate Phase 2 registration
> and, at minimum, a broken-case safety batch across the five thin-margin cases named in
> `ANSWER_BUDGET_REGISTRATION.md` section 2 — none of which is measured here.

## 1. Carried over unchanged — the anti-leakage guarantee

Every element below is reproduced from `ANSWER_BUDGET_REGISTRATION.md` **verbatim in
substance**. None was adjusted in light of anything Phase 1 produced.

- **Hypothesis H1** (section 3)
- **Arm A and Arm B definitions** (section 4)
- **Cases, lenses, replicate counts, shuffle seed** (section 5) — 44 paid lens calls
- **Primary metric and its ≥ 5/8 threshold**, and the ≥ 2/4 both-lenses requirement (sections 6-8)
- **Hard REJECT criterion** (section 8)
- **Guardrail 2, control calibration** (section 6) — retained from Phase 1
- **Baseline drift check** (stop condition 4)
- **Registered baseline: the stored 0/8** from runs 43 and 44

**One addition, disclosed here rather than left to be discovered in section 8.** BENEFIT
SHOWN gains a fourth condition (d): Guardrail 2 must **pass** — neither firing nor coming out
unevaluable (section 8.1). This is the only
change to a decision rule anywhere in Phase 1B. It is registered before any Phase 1B call, it
is **strictly a tightening** — it can only remove a BENEFIT SHOWN, never produce one — and it
was not chosen in response to any Phase 1 outcome on the control case. Conditions (a), (b)
and (c) are untouched.

Three further points deserve explicit statement, because leaving them silent is where leakage
would hide:

**The ≥ 5/8 primary threshold is NOT raised.** Phase 1 observed a high Arm B emission count.
Ratcheting the bar upward to match an observed result — or downward to guarantee clearing it
— would be fitting the endpoint to void data. The threshold stays exactly where it was
written before any call was made.

**The registered baseline stays the stored 0/8 from runs 43-44.** Phase 1's own Arm A
drift-check observations are *not* pooled into it. A void batch does not get to enlarge the
baseline it is being compared against.

**Guardrail 2 is preserved, not weakened.** Phase 1 registered it and Phase 1B keeps it,
now with an operational definition and with authority to block a benefit claim.

## 2. What changes, and why

Five changes. Three are methods, one is the integrity rule that voided Phase 1, and one
tightens BENEFIT SHOWN.

| # | change | reason | endpoint affected? |
|---|---|---|---|
| 1 | Contamination rule replaced (section 9) | Phase 1's pooled threshold had a **46.8%** false-void rate by construction | no |
| 2 | Raw response text persisted per call, VOID on failure (section 2.2) | Phase 1's forensic had to infer truncation points indirectly | no |
| 3 | Stage 0 not repeated | `thinking={"type":"disabled"}` acceptance on `claude-sonnet-5` is measured, not assumed | no |
| 4 | Cost basis updated to measured per-call spend | Phase 1 measured the identical design | no |
| 5 | Guardrail 2 operationalised as a detection-rate test and made a BENEFIT SHOWN condition (section 8.1) | a benefit bought by lowering the rate at which genuine findings are detected on the control is not a benefit | **yes — tightening only** |

Change 5 is the one endpoint change in this document. It can only make BENEFIT SHOWN harder
to reach, never easier, and it is registered before any Phase 1B call.

### 2.1 Why Phase 1's contamination rule had to be replaced

The rule pooled one 15% threshold across heterogeneous cells, one of which —
`security-02-clean × security` on Arm A — has a documented truncation rate near 50%. Under
the per-cell rates declared in section 9, Phase 1's rule voided at ≥ 3 failures, which on a
**completely healthy batch** carries probability **0.468**. It was close to a coin flip on a
batch where nothing was wrong. That is a specification defect, not a data problem, and it is
the sole reason Phase 1 is void.

### 2.2 Raw text persistence (mandatory, and VOID on failure)

The harness must persist, for every call: **the complete raw response text**, `stop_reason`,
`input_tokens`, `output_tokens`, `thinking_tokens`, `text_chars`, the parsed defect list, the
schema-error list, and the failure class assigned per section 9.1. Records are written and
flushed per call, not buffered to the end, so a crash cannot destroy completed measurements.

> **A persistence failure VOIDs the affected measurement, and with it the run.** If the raw
> response text for any call is missing, empty-when-the-call-was-not, truncated by the
> harness, or unwritable, that call cannot be forensically classified, and the run is
> classified **VOID** under stop condition 6.

This is registered as a void condition rather than something to repair afterwards because
Phase 1 demonstrated the failure mode is not recoverable after the fact: its harness recorded
token counts but not response text, so the three failures that voided it had to be classified
by inference from `stop_reason` and character counts rather than by reading what the model
actually returned. Re-running to recover the text would be a new batch, not a repair. A
measurement that cannot be audited is not a measurement.

## 3. Hypothesis

> **H1.** On `security-04-clean × {correctness, security}`, a lens call issued with
> `thinking={"type":"disabled"}` and every other request field unchanged emits a
> schema-valid critic JSON, where the current configuration emits zero characters.

Unchanged from Phase 1. Stated against the registered baseline of **0/8** (stored runs 43
and 44: 8 calls, all `stop_reason=max_tokens`, ~1599/1600 thinking, 0 chars).

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

The control set is **retained**. Dropping it because it was the source of Phase 1's
contamination would be an outcome-driven design change; and its Arm A security lens is a
second, independent instance of the truncation mechanism — stochastic where the target is
deterministic — which the primary endpoint cannot supply on its own.

Harness constraints carry over from `ANSWER_BUDGET_REGISTRATION.md` section 5: the harness
constructs its own Anthropic client (the parameter under test exists nowhere in
`src/engine`) and reuses, unmodified, `LENSES`, `RESPONSE_INSTRUCTION`, the `run_judge_gates`
prompt template, `eval/dataset.py` case content via `pipeline.read_code_snapshot`,
`judge._parse_critic` / `schema.enforce_critic_schema`, and `BudgetController`. `conn=None`,
`run_id=None`: no row is written to `.engine/state.db`, and no `BASELINE.md` row exists or
should exist for this experiment. The harness does not invoke the production retry.

## 6. Metrics

- **Primary (benefit).** Per-call answer emission on the target set: a call emits iff
  `_parse_critic` returns zero schema errors. Arm B k/8 against the registered 0/8 baseline.
- **Guardrail 1 (safety, hard).** On `quality-04-broken`, whether at least one
  `CRITICAL`/`HIGH` defect survives across its two lenses under Arm B.
- **Guardrail 2 (control blocking retention).** On `security-02-clean`, whether Arm B's
  **rate** of detecting blocking-severity findings holds up against Arm A's. Compared as
  rates, never as raw counts, and operationalised in section 8.1; it **gates BENEFIT
  SHOWN**, including when it cannot be evaluated.
- **Secondary, recorded, deciding nothing.** Output-token composition, `stop_reason`,
  `text_chars`, full defect lists, failure classes, latency, spend.

No accuracy figure is produced and none may be quoted. σ = 0.92 does not apply — that is the
40-case aggregate noise floor; this endpoint is a per-call proportion.

## 7. Sample size

Unchanged. Against a 0/N baseline, `experiment-design`'s Fisher table governs: at **N = 8**,
5/8 gives p = 0.026 (significant), 4/8 gives p = 0.077 (not sufficient), 3/8 is noise. Eight
target Arm B calls = 2 lenses × 4 replicates.

## 8. Decision rules

Written before the first paid call of Phase 1B. Reproduced unchanged from Phase 1. Not to be
edited afterward.

- **REJECT (hard, zero tolerance).** Any Arm B replicate of `quality-04-broken` in which no
  `CRITICAL`/`HIGH` defect survives across both lenses — i.e. the case would return `OK`
  where Arm A blocks. One occurrence rejects the arm and the batch stops immediately.
- **BENEFIT SHOWN.** All four must hold: (a) zero REJECT events; (b) **at least 5/8** Arm B
  target calls emit a schema-valid critic; (c) the effect appears on **both** target lenses
  at **at least 2/4** each; (d) **Guardrail 2 passes** — it neither fires nor is unevaluable
  (section 8.1).
- **INCONCLUSIVE.** Zero REJECT events, and any of (b), (c) or (d) unmet.

Conditions (a), (b) and (c) are carried over from Phase 1 unchanged. Condition (d) is added
here, before any Phase 1B call, and **only tightens** the bar — it can remove a BENEFIT
SHOWN, never create one. A tightening registered in advance cannot function as a post-hoc
rescue, which is why adding it is compatible with section 1's carry-over guarantee.

### 8.1 Guardrail 2 — control blocking retention

The control case must not pay for the target's rescue. If disabling thinking buys answer
emission on `security-04-clean` while **reducing the rate at which genuine blocking findings
are detected** on `security-02-clean`, that is **adverse evidence about the intervention**,
not a neutral side-observation, and it must not be reported as a benefit.

**The comparison is between detection rates, never between raw counts.** Raw counts are
unusable here because the two arms have different effective denominators: Arm A truncates on
this case and Arm B does not, so a count-to-count comparison would let detection degrade
without firing. Worked example 1 below is the case that forced this formulation.

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

The two denominators are deliberately asymmetric, and each asymmetry moves the bar in the
strict direction:

- **Arm A excludes its schema failures.** A truncated Arm A call would otherwise read as a
  non-detection and depress a_L, lowering the bar Arm B must clear. Excluding them keeps the
  bar at Arm A's demonstrated detection ability. **Arm A truncation can never lower the
  calibration bar.**
- **Arm B keeps all four calls.** An Arm B schema failure detected nothing, and dropping it
  from the denominator would flatter Arm B's apparent rate. **Arm B schema failures can never
  improve its apparent rate.**

#### The rule

> **Evaluability.** Lens *L* is evaluable iff **V_L ≥ 2**. With fewer than two evaluable Arm A
> calls there is no usable comparator on that lens.
>
> **Guardrail 2 FIRES if b_L < a_L on either lens.**
>
> **Guardrail 2 is UNEVALUABLE if either lens has V_L < 2.**

**Any decrease fires. There is no tolerance band and no minimum effect size** — b_L = 0.75
against a_L = 1.00 fires exactly as b_L = 0.00 against a_L = 1.00 does. This is deliberate
and it is not a precision instrument: at four replicates per arm the rule will sometimes fire
on sampling noise alone. That cost is accepted because firing is asymmetric in consequence —
it **withholds a benefit claim**, downgrading the outcome to INCONCLUSIVE. It never asserts
harm, never triggers a REJECT, and never affects the primary endpoint. Registering a
tolerance band instead would require calibrating a threshold from data not in hand, which is
the exact class of specification defect that voided Phase 1.

#### Outcomes

| condition | outcome |
|---|---|
| both lenses evaluable, neither fires | Guardrail 2 passes; BENEFIT SHOWN condition (d) satisfied |
| any lens fires (b_L < a_L) | **cannot be BENEFIT SHOWN.** INCONCLUSIVE, carrying a **registered adverse finding** |
| any lens UNEVALUABLE, none fires | **cannot be BENEFIT SHOWN.** INCONCLUSIVE, calibration unevaluable — recorded as *no adverse finding*, since absence of a comparator is not evidence of harm |

An unevaluable calibration blocking a benefit claim is intentional. It closes the hole where
heavy Arm A truncation on the control leaves too thin a comparator and the guardrail passes
vacuously — the arm that fails to produce a comparator must not thereby earn the benefit
claim it was supposed to police.

The adverse finding, when one is recorded, must be reported even though losing a blocking
finding on a clean case moves `security-02-clean` *toward* its expected `OK` verdict and
would look like an accuracy improvement.

**Guardrail 2 is not a REJECT.** REJECT is reserved for `quality-04-broken` under Guardrail 1,
where a lost blocking defect is a false pass on genuinely broken code. Nothing in this section
alters Guardrail 1, the REJECT criterion, or any primary benefit criterion.

**Severity drift within blocking is not a Guardrail 2 event.** Both rates count whether a
replicate carried at least one blocking defect, not which severity label or category it
carried, so a finding moving `CRITICAL` → `HIGH` (both blocking) does not fire it. That drift
is recorded as secondary data.

#### Worked examples

Each is one lens. "A" lists the four Arm A replicates, "B" the four Arm B replicates.

**1 — the count/denominator bug this rule exists to fix.**
A: 2 evaluable, both with a blocker; 2 truncated. B: 4 calls, 2 with a blocker.
V=2, D=2 → **a = 2/2 = 1.00**. **b = 2/4 = 0.50**. Since 0.50 < 1.00 → **FIRES.**
Detection fell from 100% to 50%. Under the previous count rule this tied 2 = 2 and passed;
it must not, and now does not.

**2 — genuine retention.**
A: 2 evaluable, both with a blocker; 2 truncated. B: 4 calls, all 4 with a blocker.
**a = 2/2 = 1.00**, **b = 4/4 = 1.00**. Not less → **does not fire**, lens evaluable
(V = 2 ≥ 2). Arm B matched Arm A's demonstrated detection across every call.

**3 — unevaluable Arm A.**
A: 1 evaluable with a blocker; 3 truncated. B: 4 calls, all 4 with a blocker.
V = 1 < 2 → **UNEVALUABLE.** Outcome is INCONCLUSIVE and **cannot be BENEFIT SHOWN**, despite
Arm B detecting on 4 of 4, because there is no adequate comparator. No adverse finding is
recorded. (V = 0, all four Arm A calls schema-failed, resolves identically.)

**4 — Arm B schema failure must not flatter Arm B.**
A: 4 evaluable, 3 with a blocker. B: 4 calls — 3 with a blocker, 1 schema failure.
**a = 3/4 = 0.75**. b uses the full denominator: **b = 3/4 = 0.75** — *not* 3/3 = 1.00. Not
less → does not fire. Had Arm B instead produced 2 blockers and 2 schema failures,
b = 2/4 = 0.50 < 0.75 → fires, rather than being rescued to 2/2 = 1.00 by dropping its own
failures.

## 9. Integrity rule — replaces Phase 1's contamination guardrail

### 9.1 Failure classes, declared in advance

Every schema failure is assigned exactly one class, mechanically, from stored fields:

- **Class T (truncation).** `stop_reason == "max_tokens"` **and** `_parse_critic` returns
  errors. The mechanism under study.
- **Class S (semantic).** `stop_reason == "end_turn"`, a balanced JSON object *was*
  extracted, **and** `enforce_critic_schema` returned errors — a complete response violating
  the schema (e.g. a verdict/severity inconsistency). The dominant historical class:
  25 of 40 stored schema failures.
- **Class X (anomalous).** Any schema failure that is neither T nor S — an API error, a
  refusal, or an `end_turn` response containing no JSON object at all.

### 9.2 The Contamination Set — enumerated, not described

Phase 1's rule said "Arm A calls ... outside the target set", which admitted two
denominators. **Phase 1B removes the ambiguity by enumerating the set and testing a count,
not a rate.** There is no denominator and no percentage anywhere in this rule.

The **Contamination Set** is exactly these 16 calls:

| # | case | lens | arm | n | declared p_T | p_S | declared p |
|---|---|---|---|---|---|---|---|
| 1 | `security-02-clean` | correctness | A | 4 | 0.07 | 0.01 | **0.08** |
| 2 | `security-02-clean` | security | A | 4 | 0.50 | 0.01 | **0.51** |
| 3 | `quality-04-broken` | correctness | A | 4 | 0.00 | 0.01 | **0.01** |
| 4 | `quality-04-broken` | code-quality | A | 4 | 0.00 | 0.01 | **0.01** |

Expected total failures **E = 2.44** of 16.

The four target Arm A calls are excluded: their failure is the phenomenon under study and is
governed by the drift check (stop condition 4), which requires them to fail in a specific
way.

### 9.3 How each p was derived

A call produces a Class T failure only if its output reaches the 1600-token cap, so p_T is
estimated from the Arm A output-token distribution for that cell across all
same-configuration evidence (stored runs 43-44 plus Phase 1's Arm A calls, n = 6 per cell).

**Two different kinds of estimate are used, and they are not equally strong. Stating them as
one would misdescribe the evidence:**

- **Headroom argument (physical).** Where every observed output sits far below the cap,
  p_T is declared **0.00** because truncation would require a multiple-fold excursion beyond
  anything the cell has ever produced. This does not depend on how often failures were
  observed; it depends on where the output distribution sits.
- **Observed at-cap frequency (empirical, Jeffreys-smoothed).** Where outputs do reach or
  approach the cap, p_T is an **observed frequency of at-cap events** — an empirical rate,
  not a mechanism argument. Phase 1's Arm A calls contribute to these counts.

| cell | pooled n | at cap (≥1600) | max output | declared p_T | estimate kind and basis |
|---|---|---|---|---|---|
| `security-02-clean` × correctness | 6 | 0 | 1592 | 0.07 | **empirical** — Jeffreys on 0/6; declared non-zero because one call reached 1592, 8 tokens short of the cap |
| `security-02-clean` × security | 6 | 3 | 1600 | 0.50 | **empirical** — Jeffreys on 3/6 at-cap. Phase 1 supplies 2 of those 3 events (stored runs 43-44 supply 1 of 2) |
| `quality-04-broken` × correctness | 6 | 0 | 154 | 0.00 | **headroom** — max output is 9.6% of cap |
| `quality-04-broken` × code-quality | 6 | 0 | 504 | 0.00 | **headroom** — max output is 31% of cap |

So the dominant cell's **p = 0.50 is an observed at-cap frequency that includes Phase 1
data**, not a cap-proximity argument that stands independently of it. Section 9.5 bounds what
that dependence can and cannot do.

**p_S is global, not per-cell** — it is a property of the judge, not of a case. Sonnet-era
evidence gives 2 semantic failures across 274 same-configuration lens calls; a Jeffreys
estimate is 0.9%, declared as **p_S = 0.01** uniformly.

### 9.4 The rule

Let *X* = the total number of schema failures observed across the 16 Contamination Set calls.
Under the declared p, *X* follows an exact Poisson-binomial distribution:

| k | 0 | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|---|
| P(X = k) | 0.038 | 0.175 | 0.319 | 0.290 | 0.139 | 0.034 | 0.005 |
| P(X ≤ k) | 0.038 | 0.213 | 0.532 | 0.822 | 0.961 | 0.995 | 1.000 |

> **VOID if X ≥ 5.** (95th-percentile threshold K = 4; P(X > 4) = **0.039** on a healthy
> batch.)

> **VOID immediately on any Class X failure, anywhere in the batch, in either arm.** Nothing
> in the declared model predicts one, and a single occurrence means the harness or the API
> is behaving outside the measured envelope.

Class T and Class S failures inside the Contamination Set are counted in *X* and nothing
more; they are expected behaviour at the declared rates, not evidence of contamination on
their own.

### 9.5 Leakage control — what void Phase 1 data may and may not inform

**The governing rule, stated plainly:**

> **Phase 1 is VOID. Its data may inform the nuisance / integrity model of Phase 1B — the
> per-cell rates p_T and p_S in section 9.3, and nothing else. It may not inform any primary
> benefit endpoint or any safety endpoint, which are carried over from
> `ANSWER_BUDGET_REGISTRATION.md` unchanged.**

Concretely, Phase 1 data **does** contribute to: the at-cap frequencies behind p_T for the
two `security-02-clean` cells (section 9.3), and the semantic-failure count behind p_S. That
is the whole of its permitted influence.

Phase 1 data **does not** contribute to: H1, the Arm A/Arm B definitions, the case and lens
selection, the replicate counts, the ≥ 5/8 primary threshold, the ≥ 2/4 both-lenses rule, the
Guardrail 1 REJECT criterion, the Guardrail 2 firing rule, or the registered 0/8 baseline —
which remains the stored runs 43-44 evidence and is **not** enlarged by Phase 1's own Arm A
observations.

Three facts bound the exposure that remains:

1. **The dominant cell's value is unchanged by the inclusion.** For
   `security-02-clean × security`, a stored-only Jeffreys estimate (1 of 2 at cap) gives
   **0.50** — identical to the declared value derived from 3 of 6. Phase 1 supplies 2 of the
   3 at-cap events, but removing them does not move the number. The cell contributing 84% of
   E is therefore not where the leakage risk lives.
2. **The declared rule is stricter than a Phase-1-blind one.** Calibrating from stored runs
   43-44 alone gives E = 4.16 and a void threshold of **X ≥ 8**. The declared rule voids at
   **X ≥ 5**. Using Phase 1's data made the gate *harder* to pass, not easier — the opposite
   of what a rescue would look like.
3. **This rule touches no endpoint.** The section 9 contamination rule decides void /
   not-void only; it has no bearing on H1, on the primary metric, or on either guardrail.
   (The one endpoint change anywhere in Phase 1B is BENEFIT SHOWN condition (d) in
   section 8.1, which is a tightening and draws on no Phase 1 data.)

For completeness, and because concealing it would be worse: Phase 1's observed X = 3 would
**not** void under this rule — but neither would it void under the Phase-1-blind calibration
in (2), which tolerates up to 7. The "does not void" outcome is what any honest calibration
of this design yields, not an artifact of having seen Phase 1.

## 10. What a negative result looks like

1. **Mechanism wrong.** Arm B emits ≤ 4/8 on the target. Disabling thinking does not rescue
   `security-04-clean`, and the answer-budget hypothesis is dead for this model.
2. **Mechanism right, safety cost too high.** Arm B emits ≥ 5/8 but triggers REJECT on
   `quality-04-broken`. Answer capacity and detection quality are coupled on this judge, and
   the rule is disqualified.
3. **Mechanism right, calibration cost too high.** Arm B emits ≥ 5/8, no REJECT, but
   Guardrail 2 fires (b_L < a_L on a lens): the target is rescued while the detection rate for
   genuine blocking findings falls on the control. Recorded as INCONCLUSIVE with a registered
   adverse finding — explicitly **not** BENEFIT SHOWN (section 8.1).
4. **Calibration unevaluable.** Arm B emits ≥ 5/8, no REJECT, no rate decrease, but a control
   lens has fewer than two evaluable Arm A replicates. INCONCLUSIVE, **not** BENEFIT SHOWN,
   and no adverse finding is recorded — there was no adequate comparator (section 8.1).
5. **Integrity failure again.** X ≥ 5, or any Class X failure, or a persistence failure.
   Recorded as VOID, with the per-class breakdown that section 2.2's raw-text persistence now
   makes diagnosable.
6. **Batch truncated by budget.** PARTIAL/VOID under stop condition 4; no benefit claim, and
   any REJECT observed before the stop still stands.

## 11. Cost

Basis: **per-call spend measured on this exact 44-call design in Phase 1** (rates input
$2.00/MTok, output $10.00/MTok, reproducing every stored `actual_spend` exactly). This is a
measured basis for an identical design, not a figure carried from another corpus.

| | |
|---|---|
| **expected** (Phase 1 measured actual) | **$0.3891** |
| worst realistic (Arm A at cap, Arm B at observed per-cell max) | $0.5347 |
| absolute worst (all 44 calls at the 1600 cap) | $0.7656 |
| **hard ceiling** | **$0.65**, enforced by `BudgetController.planned_budget` |

**Why $0.65.** It clears worst-realistic by 21.6%, leaving room for roughly six additional
worst-case calls. It deliberately does **not** cover the absolute worst of $0.7656: that
requires all 24 Arm B calls to emit 1600 tokens of pure JSON with zero thinking, against a
Phase 1 Arm B maximum of 1333 and means of 149-1247. Setting the ceiling above a physically
implausible bound would defeat its purpose. Phase 1's ceiling of $0.55 is not reused because
it cleared worst-realistic by only 2.9%.

## 12. Stop conditions

1. **Safety.** One REJECT event (section 8): stop immediately.
2. **Baseline drift.** If either target Arm A call fails to reproduce the stored profile —
   `stop_reason = max_tokens` with zero characters of text — the stored 0/8 baseline no
   longer describes current behaviour. Record and stop; do not compare Arm B against a stale
   baseline.
3. **Class X failure.** Any occurrence, either arm: stop immediately, VOID (section 9.4).
4. **Budget — PARTIAL/VOID.** If `BudgetController` raises at $0.65 before all 44 calls have
   completed, stop immediately. The run is classified **PARTIAL/VOID** and **no benefit claim
   of any kind may be made from it** — not BENEFIT SHOWN, and not a partial or provisional
   variant of it. Do not re-plan, do not top up mid-batch, and do not resume a truncated
   batch into a fresh budget and treat the union as one run.

   The reason is that the registered endpoints are defined over the *complete* design: the
   primary metric is 8 target Arm B calls, Guardrail 1 needs both safety lenses in all 4
   replicates, Guardrail 2 needs all 4 control replicates per lens, and the Contamination Set
   is defined over its full 16 calls. A truncated batch leaves at least one of these
   undefined, and a decision rule evaluated on a partial denominator is not the rule that was
   registered. A REJECT event observed before the budget stop is still recorded and still
   stands as a safety finding — a truncated batch may never claim benefit, but it can still
   demonstrate harm.
5. **Contamination.** X ≥ 5 in the Contamination Set: VOID. Assessed when the batch
   completes; unlike 1-4 it does not gate execution, because X is only defined over the full
   set.
6. **Persistence failure — VOID.** If the harness fails to persist the complete record
   required by section 2.2 for any call, that call's measurement is unusable and the run is
   classified **VOID**. See section 2.2 for what is required and why this is pre-registered
   rather than repaired after the fact.

## 13. Frozen — must not change

`LENSES`, `RESPONSE_INSTRUCTION`, the rest of `judge.py`, `schema.py`, `rubric.py`,
`verdict.py`, `eval/dataset.py`, `eval/runner.py`, `verification/pipeline.py`,
`runtime/budget.py`, `config.DEFAULT_MODELS` (judge stays `claude-sonnet-5`),
`max_tokens = 1600`, and the benchmark itself. R-a and off-lens blocking are out of scope.

**No `src/engine` change is part of Phase 1B.** The harness is read-only against the engine.
Threading `thinking` through Provider → Gateway → `run_judge_gates` remains Phase 2 work
requiring its own approval and registration.

## 14. Post-hoc leakage audit

Performed against `experiment-design`'s anti-post-hoc rules before this document was
finalised.

| check | result |
|---|---|
| Was any decision rule loosened after seeing Phase 1's result? | **No.** The one decision-rule change is BENEFIT SHOWN condition (d), which is strictly a tightening (sections 1, 2, 8.1). |
| Was the primary threshold moved toward the observed outcome? | **No.** ≥ 5/8 is unchanged; explicitly not raised despite Phase 1's higher observed count. |
| Was the baseline enlarged using void data? | **No.** It stays the stored 0/8 from runs 43-44. |
| Was a metric added after seeing data and presented as the endpoint? | **No.** Failure classes (9.1) are an *integrity* instrument and decide nothing about H1. Guardrail 2 is not new — it was registered in Phase 1 and is only given an operational definition here. |
| Was the design re-sliced until something was significant? | **No.** Same cases, lenses, arms, reps, seed. |
| Was the control dropped because it caused the void? | **No.** Retained, and given *more* authority: it can now block a benefit claim (section 8.1). |
| Was the safety case altered after Arm A showed a thin margin in Phase 1? | **No.** Same case, same lenses, same reps, same REJECT rule. |
| Does void Phase 1 data influence anything? | **Yes, one area, disclosed:** the section 9.3 nuisance rates p_T and p_S, and nothing else (9.5). Bounded — the dominant cell's 0.50 is unchanged whether Phase 1 is included or not, and the resulting rule is *stricter* than a Phase-1-blind calibration (X ≥ 5 versus X ≥ 8). |
| Is the p_T derivation described accurately? | **Yes.** Section 9.3 separates the two `quality-04-broken` cells (headroom argument, physical) from the two `security-02-clean` cells (observed at-cap frequency, which includes Phase 1 events). The dominant p = 0.50 is **not** claimed to be cap-proximity-only. |
| Can a truncated or unauditable run produce a benefit claim? | **No.** A budget stop is PARTIAL/VOID and a persistence failure is VOID; neither may claim benefit (stop conditions 4 and 6). |
| Is one change bundled with another? | **No.** The intervention is unchanged; only the integrity instrument, harness logging, and one endpoint tightening moved. |

**Residual risk, stated plainly.** Phase 1B is a replication of a design whose one previous
execution is known to its author. Blinding is not achievable here. The protections are that
every benefit and safety endpoint is textually unchanged from a registration written before
any call existed, that the sole endpoint change is a tightening registered in advance, and
that the one place void data was used is disclosed, bounded, and demonstrably conservative.
