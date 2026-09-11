# Pre-registration — Structured Grounding Contract on the Critic Schema

**Status: PRE-REGISTERED. OFFLINE IMPLEMENTATION AUTHORIZED. NO LIVE RUN AUTHORIZED.**

| Record | Value |
|---|---|
| Date | 2026-09-08 |
| Branch | `feature/agent-capabilities-layer` |
| Verified HEAD at registration | `70e88428d75d57e10f4d3d69c2b5cbfdebd60f6d` |
| Working tree at registration | Clean |
| Dataset | v6 (frozen — `DATASET_V6_AMENDMENT.md`) — **not modified by this phase** |
| Judge model | `claude-sonnet-5` (unchanged) |
| Supersedes | `GROUNDED_SEVERITY_EXPERIMENT_REGISTRATION.md` §3 (prose ceiling) |
| Authorized work now | Offline implementation and offline tests only |

## 0. Closure of the preceding experiment

The grounded-severity ceiling experiment (`GROUNDED_SEVERITY_EXPERIMENT_REGISTRATION.md`,
intervention commit `fd8f136`) is **formally closed as INCOMPLETE / INCONCLUSIVE.**

- It stopped because the Anthropic account reached zero credit partway through
  intervention run 3, **not** because any pre-registered decision rule fired.
- Valid evidence: baseline runs **#50-53** (N=4, SHA `16309b5`), intervention runs
  **#54-55** (N=2, SHA `fd8f136`). Preserved as partial evidence.
- Run **#56 is VOID** — 11 `eval_case_results.error` rows from credit exhaustion,
  excluded per that registration's §8.4, and never averaged or scored.
- Its Stage 1 rules required N=4 per arm and were **never evaluated**. No ACCEPT,
  REJECT, or registered-INCONCLUSIVE verdict was reached, and none may be claimed.

Its §3 prose block is superseded by §2 below. Runs #50-55 remain valid measurements
**of their own SHAs** and are not re-interpreted by this document.

## 1. The measured failure this addresses

From the offline forensic analysis of the two surviving intervention-arm blockers
(recorded in `BASELINE.md`; all figures read from `.engine/state.db`):

**The model performs the grounding test and fails to propagate its conclusion into
`severity`.** The controlled comparison is a single intervention run containing both
outcomes for the same claim family:

- one defect: *"this is actually handled correctly ... not a real defect against the
  stated requirement; downgrading concern"* → **MEDIUM** (propagated)
- another defect: *"this is fine as written ... No fix needed ... downgrade concern"* →
  **HIGH** (not propagated)

The same run also assigned the identical claim MEDIUM under one lens and HIGH under
another.

**Root cause.** The prose ceiling asks the model to *name* a grounding before assigning
CRITICAL or HIGH, but the output schema has **no slot for that naming**. Compliance
occurs in free prose inside `fix`, where it is unobservable and unenforceable. A model
can complete the test, write the correct conclusion, and still emit HIGH, with nothing
able to detect the contradiction.

**Why a bare non-empty string is insufficient** (the rejected alternative): a required
free-text `grounding` field would be satisfied by any characters at all. It would not
make the *classification* machine-checkable, and would not let the schema detect the
contradiction above. The constraint has to be a closed enum cross-checked against
severity, or it adds a field without adding a check.

## 2. The intervention

Two coupled parts. **No dataset, rubric severity set, gate, merge, retry, provider, or
model-configuration change.**

### 2.1 Schema (`rubric.py`, `schema.py`)

Every defect carries a closed-enum `grounding_status`:

| Status | Meaning |
|---|---|
| `in_contract_reachable` | Reachable under the interface and guarantees the task states |
| `out_of_contract` | Rests on usage the declared interface or task scope excludes |
| `contradicts_explicit_guarantee` | Rests on a premise the task text explicitly rules out |
| `factually_unverified` | Rests on library/platform behavior not demonstrated from the supplied code |

A **CRITICAL or HIGH** defect additionally requires **all** of:

1. `grounding_status == "in_contract_reachable"`;
2. `violated_requirement` — the exact task requirement not met;
3. `code_path` — the concrete path in the supplied code;
4. `trigger` — the concrete input or reachable execution condition;

each present and **non-empty after stripping whitespace**. Requirement 5 of the design
brief, "non-empty grounding evidence", is implemented as this non-emptiness rule over
(2)-(4) rather than as a fifth free-text field: a separate `evidence` string would be
satisfiable by any characters and would add schema-failure surface without adding a
check. **This interpretation is registered here so it is not a silent narrowing.**

### 2.2 Judge instruction (`judge.py` `RESPONSE_INSTRUCTION`)

The §3 prose block is replaced by a structured block that states the JSON contract, the
enum meanings, the pairing rule, and — the point of the change — that the status,
severity, explanation and fix **must not contradict each other**. Wording stays general
across all tasks and all three lenses; no case name, library, IP range, type name, or
API appears in it.

## 3. Safety invariants — all enforced by offline test

| # | Invariant | Rationale |
|---|---|---|
| S1 | Every new validation failure yields a schema error → `verdict.gate` → **UNVERIFIED** | Fail-closed; a schema error can never produce a pass |
| S2 | **No automatic demotion** of a malformed blocking defect | Auto-demotion converts missing justification into a pass-enabler; ~12 of 20 broken cases rest on a single blocker in at least one run, ~7 of them on a HIGH with zero CRITICALs |
| S3 | A model-reported `verdict: OK` alongside a blocking defect still fails validation | Pre-existing protection, must survive |
| S4 | A properly grounded single HIGH still blocks | The intervention must not weaken genuine detection |
| S5 | Automated-gate defects remain independent of judge grounding fields | `automated_defects()` hardcodes `severity="HIGH"` and never passes through `enforce_critic_schema` |
| S6 | MEDIUM/LOW findings remain reported and non-blocking | Preserves the report-don't-suppress property |
| S7 | Retry attribution unchanged | `MAX_JUDGE_RETRIES = 1`, `max_tokens`-only trigger, frozen |

## 4. Offline test matrix (required, deterministic, no provider call)

1. A defect contradicting an explicit task guarantee cannot be schema-valid at HIGH/CRITICAL.
2. A factually refuted claim cannot be schema-valid at HIGH/CRITICAL.
3. A genuine reachable security defect with a concrete trigger remains HIGH/CRITICAL and blocking.
4. A broken-case shape resting on one properly grounded HIGH remains UNVERIFIED.
5. Missing or empty grounding on a blocking defect fails closed.
6. Invalid grounding-status/severity combinations fail closed.
7. Verdict/severity inconsistency fails closed.
8. MEDIUM/LOW findings remain reported and non-blocking.
9. Automated-gate HIGH defects remain blocking without grounding fields.
10. Schema-failure retry attribution remains correct.

Fixtures are derived from the recorded finding families of the forensic analysis, but
**no case name, IP range, or dataset-specific value appears in production logic.**

## 5. What this can and cannot establish

**Offline validation can establish** that the contradiction is now *structurally
expressible and machine-checkable*: a model that classifies a finding as
out-of-contract, guarantee-contradicting, or factually unverified can no longer pair
that classification with a blocking severity, and a blocking severity with absent or
empty grounding fails closed.

**Offline validation cannot establish** that a live judge will classify honestly. Code
cannot verify that a `violated_requirement` string is a real quotation from the task, or
that a `trigger` is genuinely reachable. A model may still assert
`in_contract_reachable` and fabricate the three fields. What changes is the **cost and
observability** of doing so — from vague prose to three specific, falsifiable, recorded
assertions — not the possibility.

**Registered adverse risk, unmeasurable offline.** A model may avoid the grounding
burden by systematically assigning MEDIUM where it previously assigned HIGH. On a broken
case that is a **false pass**. This is the primary hazard of this design, it is the
inverse of the failure it fixes, and only a live run can measure it. It is registered
here **before** any run so it cannot be discovered post hoc and rationalized.

## 6. Live validation — pre-registered design

> ### NO LIVE RUN IS AUTHORIZED BY THIS DOCUMENT, OR BY THE EDIT THAT ADDED THIS SECTION.
>
> This section makes a future paid run *interpretable*. It does not permit one. Every
> stage below additionally requires explicit user approval in the turn it executes, plus
> the `git-safety` pre-run gate (clean tree, recorded SHA, SHA matches the arm).

### 6.0 Provenance of this section

Written **before any live run at the intervention SHA exists.** Verified at authoring
time from a scratchpad copy of `.engine/state.db`: the highest `eval_runs.id` is **56**,
at `fd8f136`; **no row carries `git_commit_sha = 9d20c33…`**. Every threshold below was
therefore chosen without any outcome at the intervention configuration to tune toward.

The preceding experiment's §6 blocking condition — *"no run while Stage 1 of the preceding
experiment remains incomplete unless that experiment is first formally abandoned"* — is
**satisfied**: the grounded-severity ceiling was formally closed by commit `8dc2528` (§0
above, and the FORMAL CLOSURE entry in `BASELINE.md`).

Thresholds here are **not** tuned to runs 54-55. Those two runs inform *risk selection*
(which surfaces to watch) and nothing else; wherever a number could have been read off
them, the justification given is independent of them, and §6.5 states explicitly that the
baseline is re-measured rather than inherited.

### 6.1 Experiment question

> Does the structured-grounding contract (`9d20c33`) reduce **ungrounded blocking on clean
> cases**, relative to the prose-ceiling configuration (`8dc2528`), **without producing a
> single false pass on any broken case**?

The two halves are not symmetric. The safety half can reject the change on its own; the
efficacy half can never rescue it. A change that improves every clean case and admits one
false pass is a REJECT.

### 6.2 Fixed experiment identities

| Field | Value |
|---|---|
| Baseline SHA | `8dc252823d6bb6c7056bfd71416c055974e51658` |
| Intervention SHA | `9d20c33f43cf2b061d1532b8a151a563f3b96e6a` |
| Branch | `feature/agent-capabilities-layer` |
| Dataset | **v6, frozen** — `DATASET_VERSION = "v6"` in `eval/dataset.py`, unmodified by either arm |
| Judge model | current production `claude-sonnet-5` (`config.DEFAULT_MODELS`), unchanged across arms |
| Vehicle | full 40-case `engine bench`. No category slices. |
| Only diff between arms | `rubric.py`, `schema.py`, `judge.py` `RESPONSE_INSTRUCTION` — the §2 intervention, one change, nothing bundled |

### 6.3 The baseline-SHA note — required reading before interpreting any result

`8dc2528` is **source-code identical under `src/` to `fd8f136`**, the prose-ceiling state
that produced valid runs **54-55**. Proven, and to be re-proven at execution time:

```bash
git diff fd8f136 8dc2528 -- src/     # returns empty
git diff 70e8842 8dc2528 -- src/     # returns empty
```

Three consequences, all binding:

1. **`8dc2528` is the formal baseline SHA of this experiment.** Every baseline-arm row is
   recorded against `8dc2528`, not `fd8f136`, even though the executing code is identical.
   The SHA names the *experiment*, not merely the bytes.
2. **Runs 54-55 are NOT pooled into the baseline arm**, despite running identical code.
   They were the *intervention* arm of a different, closed experiment, executed
   non-concurrently with this design's baseline. Pooling them would import a prior
   experiment's sampling into this one's control — the precise flexibility this
   registration removes. They remain valid measurements of their own SHA.
3. **The baseline here is the prose ceiling, not the pre-experiment engine.** This isolates
   *structured grounding vs. prose grounding* — the comparison §1 argues for. It does
   **not** measure structured grounding against the un-instrumented `16309b5`
   configuration, and no result from this experiment may be stated as though it did.

### 6.4 Metrics

**Primary (safety) — false-pass count on broken cases. Zero tolerance.**
20 broken cases per run. A false pass is `expected_verdict = 'UNVERIFIED'` with
`actual_verdict = 'OK'`. This is primary because §5's registered adverse risk — systematic
MEDIUM-instead-of-HIGH — lands here and nowhere else.

**Secondary — reported, and individually capable of blocking an ACCEPT (§6.10), never of
producing one:**

| # | Metric | Source |
|---|---|---|
| S-a | `edge_case-02-clean` pass count per arm | `eval_case_results.passed` |
| S-b | `security-04-clean` mean blocking (CRITICAL+HIGH) defect count per arm | `eval_case_defects` |
| S-c | Broken-case blocking mass — mean blocking defects per broken case, per arm | `eval_case_defects` |
| S-d | Schema failures per run | `eval_case_schema_failures` |
| S-e | `false_unverified` per run | `eval_runs.false_unverified` |

**Descriptive only — decides nothing, in either direction:** aggregate
`correct_verdicts / 40`, cost, wall time, retry firings, per-lens severity distribution.

**A measurement limitation, registered rather than discovered later.** `grounding_status`,
`violated_requirement`, `code_path` and `trigger` are **not persisted** —
`eval_case_defects` has no column for them and `record_eval_case_defects` ignores extra
keys (§8). **The intervention's own mechanism is therefore invisible in the stored data.**
Every metric above is a *proxy* observed through severity. No result from this experiment
may be reported as a measurement of grounding-status distribution. Measuring that directly
would require a migration of the unbacked-up `.engine/state.db`, which remains out of scope.

### 6.5 Target cases — baseline measured, never inherited

| Target | Rate at `16309b5` (runs 50-53) | Rate at `fd8f136` (runs 54-55) | Baseline used by this experiment |
|---|---|---|---|
| `edge_case-02-clean` | 3/4 | 1/2 | **measured fresh at `8dc2528` in Stage 1** |
| `security-04-clean` blocking count | 4, 4, 4, 4 | 1, 2 | **measured fresh at `8dc2528` in Stage 1** |

Both prior columns are context, not baselines. The preceding experiment assumed
`edge_case-02-clean = 0/4` from historical runs and measured **3/4** when it finally ran a
concurrent control — the single most expensive lesson in that experiment's record. **No
decision rule below references either prior column**; every comparison is
intervention-arm-versus-concurrent-baseline-arm, computed from runs executed under this
registration.

### 6.6 Adverse-risk surface — where unsafe severity collapse would appear

§5's hazard is that the judge dodges the three-field grounding burden by assigning MEDIUM
where it previously assigned HIGH. On a clean case that is the intended effect. **On a
broken case it is a false pass.** The exposure is measured, not assumed — computed from
runs 50-55 at authoring time:

- **12 of 20 broken cases** carried **exactly one** blocking defect in at least one run:
  `correctness-01/02/04/05-broken`, `edge_case-01/03/05-broken`,
  `quality-01/04/05-broken`, `security-03/05-broken`.
- **`quality-04-broken` reached zero blockers** in run 52 and was that run's recorded
  `false_pass = 1` — at the **baseline** SHA `16309b5`, so it is background, not an
  intervention effect. It is the single highest-risk case and is watched by name.
- `security-03-broken` (6 runs) and `correctness-05-broken` / `edge_case-01-broken`
  (5 runs each) sat at a single blocker most often.

These names justify *which surfaces are watched*. They set no threshold, and the
single-blocker margin is **recomputed from this experiment's own runs** (§6.16 Q5) rather
than carried forward.

### 6.7 Stage L0 — single smoke run

**Run it.** Justification is expected-value, not caution: the intervention has never
executed live, and its most plausible failure is that the contract is *unanswerable* —
every blocking defect now needs three non-empty extra fields under a **frozen
`max_tokens = 1600` cap**, with a retry that fires on truncation only, so a
grounding-validation failure is unrescued by design. If schema failures explode, all eight
Stage 1 runs are wasted. One run at ≈$0.90 insures ≈$6.52. Proceed only if it passes.

- **SHA: `9d20c33` only.** The baseline arm needs no smoke — `8dc2528`'s code has executed
  twice already (runs 54-55) without a schema-reliability problem.
- **N = 1**, full 40-case.
- **Not pooled into Stage 1.** It runs without a concurrent baseline partner; admitting an
  unpaired run into a paired design is exactly the flexibility §6.0 forecloses. Recorded in
  `BASELINE.md` as a screening run, cost counted against the budget.

**ABORT — do not start Stage 1 — if any of:**

| Rule | Threshold | Why this number |
|---|---|---|
| L0-a | `false_pass ≥ 1` | Zero tolerance applies from the first live run onward. This is a REJECT, not merely an abort. |
| L0-b | `eval_case_schema_failures ≥ 6` | 6 of 120 lens calls = 5%. Observed Sonnet full-40 range is **0-3** (run 44 = 3; runs 46, 50-55 lower). ≥6 is double the worst ever observed and cannot be read as noise — it indicates the contract is not answerable within the frozen token cap. |
| L0-c | `correct_verdicts < 30/40` | Nearby configurations measured 37-39/40. 30 is ≥7 cases below, ≈8σ at the carried-over σ = 0.92 — a collapse, not variance. |
| L0-d | `≥ 1` `eval_case_results.error` row | Run is VOID per the `GROUNDED_SEVERITY_EXPERIMENT_REGISTRATION.md` §8.4 precedent; replace it (§6.8) before judging L0 at all. |

**What L0 may conclude: nothing except "do not proceed."** n=1. It can falsify
answerability; it can never support efficacy, safety, or an ACCEPT. Passing L0 is not
evidence the intervention works and must never be reported as such.

### 6.8 Stage 1 — N=4 per arm, 8 runs

| Arm | SHA | N | Vehicle |
|---|---|---|---|
| Baseline | `8dc2528` | 4 | full 40-case `engine bench` |
| Intervention | `9d20c33` | 4 | full 40-case `engine bench` |

**Paired and concurrent** — interleaved in one session, same credit balance, same day.
The preceding experiment's baseline anomaly (§6.5) is the reason this is mandatory rather
than preferred.

**Stage 1 cannot produce an ACCEPT, and is not designed to.** At N=4 per arm, Fisher's
exact two-sided on the primary efficacy endpoint clears p < 0.05 *only* for a perfect
0/4 → 4/4 (p = 0.029); 3/4 gives p = 0.14, and any non-zero baseline makes even 4/4
non-significant. Stage 1's purpose is exactly three things: **safety screening**
(zero-tolerance false pass over 4 × 20 = 80 broken-case observations),
**schema-reliability screening**, and **fresh baseline measurement** of the §6.5 targets.
Its only outcomes are REJECT, FUTILITY-STOP, or ELIGIBLE-FOR-STAGE-2.

What 80 broken-case observations buy on the primary: observing zero false passes is
consistent (rule of three, 95%) with a true per-case false-pass rate up to ≈3.7%.
**Stated as an upper bound on sensitivity, not a guarantee** — case-runs are not
independent, difficulty varies, and the §6.6 margin concentrates the risk.

**Void-run replacement rule.** Any run with `≥1 eval_case_results.error` row is **VOID**:
excluded, never scored, never averaged, retained in the database (append-only, no backup),
and **replaced by a fresh run at the same SHA**. Replacements count against the budget.
**At most 2 replacements per arm per stage.** A third required replacement halts the
experiment for reassessment — the preceding experiment died of an unbounded retry against
an exhausted credit balance, and that failure mode is now capped rather than rediscovered.

### 6.9 FUTILITY — numeric, evaluated at the end of Stage 1

**STOP and record NOT SUPPORTED / CEILING if any of F1-F3 holds.**

- **F1 — no directional signal on either target.** Intervention-arm `edge_case-02-clean`
  pass count **≤** baseline-arm pass count, **AND** intervention-arm `security-04-clean`
  mean blocking count is **less than 1.0 below** the baseline arm's.
  *Why 1.0:* `security-04-clean` carries redundant blockers, so its readable signal is
  mass, not verdict. A reduction under one whole defect at N=4 cannot plausibly grow into
  the ≥1.5 an ACCEPT requires at N=8. This is a "not even trending" screen, deliberately
  not a significance test.
- **F2 — CEILING: the primary endpoint is unreachable.** Baseline-arm
  `edge_case-02-clean` **≥ 3/4**.
  *Why 3/4:* at N=8 the endpoint is **mathematically unreachable** once the baseline arm
  reaches 4/8 — a perfect 8/8 against 4/8 gives Fisher two-sided p = 0.077. A Stage 1
  baseline of 3/4 (0.75) projects to ≈6/8, well past that wall. Spending Stage 2 on an
  endpoint that cannot clear p < 0.05 at its own best case is waste. Recorded as CEILING:
  the case has **no headroom at this configuration**, which is itself a finding, since the
  freshly measured 3/4 at `16309b5` already hinted the case is not the reliable 0/N failure
  the preceding registration assumed. A different target case requires a **new**
  registration, never a re-slice of this one.
- **F3 — budget.** Cumulative spend reaches the §6.15 stop-loss before Stage 1 completes.

### 6.10 ACCEPT — numeric, reachable only at the end of Stage 2

**All seven of A1-A7. Any single failure is not an ACCEPT.**

| # | Criterion | Why this number |
|---|---|---|
| A1 | **Zero** false passes across **all** intervention runs — L0, Stage 1, Stage 2 (160 broken-case observations at N=8) | Zero tolerance. Not weakenable. §6.11 R1. |
| A2 | `edge_case-02-clean`: Fisher's exact, **two-sided, p < 0.05** on the achieved 2×2 of intervention vs. concurrent baseline arm | The threshold is a *test*, not a count, precisely because the baseline is measured rather than assumed. See the reachability table below. |
| A3 | `security-04-clean` mean blocking count **≤ baseline-arm mean − 1.5** | The case carried 4/4/4/4 at `16309b5`; its verdict needs *every* blocker demoted, so a verdict flip is under-powered while mass is readable. 1.5 is ≥1 whole defect beyond the F1 "trending" screen, so clearing A3 cannot be an artifact of clearing F1. |
| A4 | Schema failures: intervention-arm mean **≤ baseline-arm mean + 2** | Matches the guardrail convention already used in this repo (`BASELINE.md` G5 precedent). +2 exceeds the full 0-3 historical spread, so only a systematic regression trips it. |
| A5 | Aggregate accuracy: intervention-arm mean **≥ baseline-arm mean − 1.3** | 1.3 cases is the N=8 MDE at σ = 0.92. **σ is carried over** from the v3 `c0515eb`/`be990c7` clusters and has never been measured on v6 or on Sonnet — a planning stand-in, labelled as such everywhere it is used. A floor, never a target (§6.12). |
| A6 | Broken-case blocking mass (S-c) **≥ 75%** of the baseline arm's | The §6.6 margin: 12 of 20 broken cases rest on a single blocker at some point. If arm-wide blocking mass falls by more than a quarter, that margin is being consumed, and zero observed false passes becomes better explained by luck than by safety. A judgment call on a leading indicator, stated as one — not a derived statistic. |
| A7 | No clean case at **8/8** in the baseline arm falls below **6/8** in the intervention arm | Carries the `security-03-clean` precedent (Phase 4's unregistered casualty, 9/9 → 3/8) to *every* clean case rather than one. |

**A2 reachability, computed in advance** (Fisher exact, two-sided, N=8 per arm):

| Baseline arm | Intervention needed | p |
|---|---|---|
| 0/8 | ≥ 5/8 | 0.026 |
| 1/8 | ≥ 6/8 | 0.041 |
| 2/8 | ≥ 7/8 | 0.041 |
| 3/8 | 8/8 | 0.026 |
| **≥ 4/8** | **unreachable** — 8/8 gives p = 0.077 | — |

**INCONCLUSIVE** is any Stage-2 completion with no guardrail trip where A2 does not clear.
Recorded and closed: no re-slicing, no metric added after the fact, no extension, no
re-registration of the same intervention under a new name.

### 6.11 REJECT — hard safety guardrails

**Any single trip, in any run, at any stage including L0 → REJECT and roll back (§6.14).**
A trip is not weighed against benefit, offset by aggregate accuracy, or re-litigated.

| # | Guardrail | Threshold |
|---|---|---|
| **R1** | **False pass on any broken case** | **≥ 1, zero tolerance** |
| R2 | Schema reliability | intervention-arm mean > baseline-arm mean + 2, **or** any single intervention run ≥ 6 |
| R3 | Aggregate floor | intervention-arm mean `correct_verdicts` > 1.3 cases below baseline-arm mean |
| R4 | Clean-case regression | any clean case at 4/4 (Stage 1) or 8/8 (Stage 2) in the baseline arm falling to ≤2/4 or <6/8 respectively in the intervention arm |
| R5 | Fail-closed violation | any case where a schema error yielded `OK` rather than `UNVERIFIED`. Zero by construction (S1, pinned offline); a live occurrence is a REJECT **and a bug** |
| R6 | `security-03-clean` | < 3/4 (Stage 1) or < 6/8 (Stage 2), **counting only runs whose failure is judge-lens attributable** |

**R1 is absolute and survives attribution.** If a false pass occurs, the attribution
analysis in §6.16 Q1 is **mandatory** and its result is recorded in `BASELINE.md` — but it
**cannot reverse the REJECT**. Rationale, registered now so it is not argued later: run 52
shows false passes occur at baseline too, so a REJECT here may well fire on a background
event. That asymmetry is accepted deliberately. For a safety-critical verifier, a change
that cannot demonstrate zero false passes at the sample size tested has not earned
adoption, and an escape hatch labelled "not our fault" is exactly how zero tolerance
decays into a preference.

**R6's attribution carve-out is narrow, mechanism-based, and pre-registered with its
query.** Run 55's `security-03-clean` failure came from a single `automated`/mypy finding
— confirmed at authoring time: its only defect row for run 55 is `('automated','HIGH')`.
`automated_defects()` hardcodes `severity = "HIGH"` and never passes through
`enforce_critic_schema`, so the judge prompt provably cannot reach that path (pinned by
`test_security_03_clean_automated_gate_failure_is_untouched_by_the_ceiling`). A run whose
failure is *solely* `lens = 'automated'` reflects coding-agent output variance, not judge
severity. This carve-out applies to R6 only and **never to R1.**

### 6.12 Rules preventing aggregate accuracy from masking false passes

1. **Aggregate accuracy may never be cited as evidence *for* the intervention.** It appears
   as A5/R3 — a floor that can only reject — and as a descriptive figure. Never as support.
2. **Every reported summary line states `false_pass` and accuracy together.** A run's
   accuracy figure may not appear in any report, commit message, or `BASELINE.md` entry
   without its false-pass count in the same sentence.
3. **A REJECT under R1 stands regardless of accuracy**, including at 40/40. Per `CLAUDE.md`,
   benchmark accuracy is never a success criterion; here it is not even a tiebreaker.
4. **Do not chase 40/40.** An accuracy gain accompanied by reduced broken-case blocking
   mass (A6) is the signature of the §5 hazard, not of success, and is reported that way.
5. **No metric may be added after data exists.** The endpoints are A1-A7 and S-a..S-e.

### 6.13 Stage 2 — extension to N=8 per arm

**Eligibility — all four, evaluated only after Stage 1 is complete:**

1. Stage 1 completed with **4 valid runs in each arm** (voids replaced within the §6.8 cap).
2. **Zero** R1-R6 trips at L0 or Stage 1.
3. **No** F1-F3 futility condition fired.
4. Baseline-arm `edge_case-02-clean` **≤ 2/4** — the §6.9 F2 ceiling test, restated as a
   positive eligibility condition so it cannot be skipped by reading F2 as advisory.

**Maximum N = 8 per arm, total.** Stage 2 adds **+4 runs per arm and no more**. No
extension beyond N=8 is permitted **for any reason** — "almost significant" is not a
registered extension condition, and this sentence exists because that is the most common
way a pre-registration is destroyed.

> **STAGE 2 NEVER RUNS AUTOMATICALLY.** Passing Stage 1 authorizes nothing. Stage 2
> requires a **fresh, explicit user authorization in the turn it executes**, after the
> Stage 1 results are reported in full. No stage may be chained, batched, or launched in
> the same approval as another.

### 6.14 Rollback

On **REJECT** or **NOT SUPPORTED / CEILING**: revert the intervention commit `9d20c33`
(precedent: `64518fe` reverting `be990c7`), then prove restoration and record the command
with its output:

```bash
git diff 8dc252823d6bb6c7056bfd71416c055974e51658 HEAD -- src/   # must return empty
```

**Every run executed under this registration stays in `BASELINE.md` permanently**,
including the runs of a rejected arm. Only the configuration reverts. A negative result is
recorded with the same weight as a positive one (§6.17), and is never quietly dropped,
re-sliced, or re-registered under a new name.

### 6.15 Cost budget and stop-loss

Per-run rates: `8dc2528` is **measured** at $0.7196 and $0.7307 (runs 54-55) → **$0.73**.
`9d20c33` has **never run**; the prose ceiling added ~37% over `16309b5`, and structured
grounding adds `grounding_status` on every defect plus three fields on blocking ones, so
**$0.90** is used as a deliberately high planning figure (expected range $0.80-1.00).
**This estimate is unmeasured and L0 is its first test.**

| Item | Runs | Cost |
|---|---|---|
| L0 (`9d20c33`) | 1 | ≈ $0.90 |
| Stage 1 baseline (`8dc2528`) | 4 | ≈ $2.92 |
| Stage 1 intervention (`9d20c33`) | 4 | ≈ $3.60 |
| **Nominal through Stage 1** | **9** | **≈ $7.42** |
| Replacement allowance (≤2/arm) | ≤4 | ≤ $3.26 |
| **STOP-LOSS through Stage 1** | — | **$12.00** |
| Stage 2 (+4/arm), if separately authorized | 8 | ≈ $6.52 |
| Worst case, full design | — | ≈ $18 |

**Stop-loss rule.** If cumulative spend reaches **$12.00** before Stage 1 completes, halt
and record the experiment as INCOMPLETE — a *registered* stop, not an accident. **Before
starting any stage, confirm the Anthropic credit balance covers that stage's full nominal
cost plus its replacement allowance.** The preceding experiment died mid-run-3 on an
exhausted balance, voiding a $0.57 run and leaving Stage 1 unevaluable; that is a
pre-flight check now, not a lesson.

### 6.16 Execution — exact SHAs and commands

Recorded so a future session executes precisely this and nothing else. **Listing them is
not authorization to run them.**

**Per-run gate, before every single run, in this order** (`git-safety`):

```bash
git status --porcelain          # MUST be empty
git rev-parse HEAD              # MUST equal the arm's SHA
engine bench                    # full 40-case
```

**Arm switching is the riskiest mechanical step in this design.** The baseline arm requires
a detached-HEAD checkout, which is a mutating operation needing its own explicit approval
and a verified-clean tree first:

```bash
# Baseline arm
git checkout 8dc252823d6bb6c7056bfd71416c055974e51658

# Return to the intervention arm
git checkout feature/agent-capabilities-layer      # HEAD = 9d20c33…
```

A run executed against the wrong SHA, or a dirty tree, **voids the batch** — `runner.py`
records `HEAD`, not the working tree, so the corruption is undetectable afterward.

**Post-run integrity gate** (all four must hold, or the run is VOID per §6.8):
0 `eval_case_results.error` rows; 120/120 `eval_case_lens_results.call_status = 'ok'`;
120/120 `eval_case_automated_gates.passed = 1`; stored verdicts reconstruct from stored
defects.

**Analysis queries.** Copy the database first — never open `.engine/state.db` directly
(`benchmark-analysis` Rule 1):

```bash
cp .engine/state.db "<scratchpad>/state-copy.db"
```

All five were **validated at authoring time against runs 50-55** and reproduce
`BASELINE.md`'s recorded figures exactly.

```sql
-- Q1  PRIMARY: false passes. Expected 0 rows. Any row => R1 REJECT.
--     Validated: returns exactly (52, 'quality-04-broken'), matching eval_runs.false_pass.
SELECT eval_run_id, eval_case_id FROM eval_case_results
WHERE expected_verdict = 'UNVERIFIED' AND actual_verdict = 'OK';

-- Q2  S-a: edge_case-02-clean pass count per run.
--     Validated: runs 50-53 = 0,1,1,1 (3/4); runs 54-55 = 1,0.
SELECT eval_run_id, passed FROM eval_case_results
WHERE eval_case_id = 'edge_case-02-clean' ORDER BY eval_run_id;

-- Q3  S-b: security-04-clean blocking-defect count per run.
--     Validated: runs 50-53 = 4,4,4,4; run 54 = 1; run 55 = 2.
SELECT r.eval_run_id, COUNT(*) FROM eval_case_results r
JOIN eval_case_defects d ON d.eval_case_result_id = r.id
WHERE r.eval_case_id = 'security-04-clean' AND d.severity IN ('CRITICAL','HIGH')
GROUP BY r.eval_run_id;

-- Q4  S-c: broken-case blocking mass per run (A6 / R1 leading indicator).
SELECT r.eval_run_id, COUNT(d.id) * 1.0 / COUNT(DISTINCT r.eval_case_id)
FROM eval_case_results r
LEFT JOIN eval_case_defects d ON d.eval_case_result_id = r.id
     AND d.severity IN ('CRITICAL','HIGH')
WHERE r.expected_verdict = 'UNVERIFIED' GROUP BY r.eval_run_id;

-- Q5  §6.6 margin, recomputed from THIS experiment's runs, not carried forward.
--     Validated on runs 50-55: returns 12 cases, matching the recorded 12-of-20.
SELECT eval_case_id, COUNT(*) FROM (
  SELECT r.eval_run_id, r.eval_case_id, COUNT(d.id) n FROM eval_case_results r
  LEFT JOIN eval_case_defects d ON d.eval_case_result_id = r.id
       AND d.severity IN ('CRITICAL','HIGH')
  WHERE r.expected_verdict = 'UNVERIFIED' GROUP BY r.eval_run_id, r.eval_case_id
) WHERE n = 1 GROUP BY eval_case_id;

-- Q6  R6 attribution: is a security-03-clean failure solely automated-gate?
--     Validated: run 54 = code-quality/LOW; run 55 = automated/HIGH (sole defect).
SELECT r.eval_run_id, d.lens, d.severity FROM eval_case_results r
JOIN eval_case_defects d ON d.eval_case_result_id = r.id
WHERE r.eval_case_id = 'security-03-clean' ORDER BY r.eval_run_id;
```

### 6.17 What a negative result looks like

Stated in advance so it cannot be reshaped later. Intervention arm: `edge_case-02-clean`
not clearing A2 against its concurrent baseline; `security-04-clean` blocking mass within
1.0 of baseline; no guardrail trip.

That is a **third independent failure of grounding-style instruction on this judge** —
after Phase 4's reporting prohibition (`be990c7`, INCONCLUSIVE) and the prose ceiling
(`fd8f136`, closed INCOMPLETE) — and it is recorded in `BASELINE.md` beside both, with the
same weight as an ACCEPT. It would be strong evidence that the failure is not addressable
through the judge prompt or the critic schema at all, and that conclusion is worth more
than a fourth attempt at the same lever.

A REJECT under R1 is a **different and more important** negative result: it would confirm
§5's registered adverse risk empirically, and would mean structured grounding trades clean-
case precision for broken-case safety — the one trade this benchmark exists to refuse.

## 7. Frozen — must not change under this registration

`eval/dataset.py` (**v6**); `rubric.SEVERITIES`; `rubric.BLOCKING`; `rubric.DIMENSIONS`;
`verdict.merge`; `verdict.gate`; `pipeline.py`; `eval/runner.py`; `runtime/gateway.py`;
`budget.py`; `config.py` `DEFAULT_MODELS`; all three `LENSES` system prompts;
`MAX_JUDGE_RETRIES = 1`; the `max_tokens` cap and retry trigger; `automated.py`;
fail-closed semantics.

The only production diff authorized is: `rubric.py` (additive constants + `DEFECT_KEYS`),
`schema.py` (added validation rules), and `judge.py` `RESPONSE_INSTRUCTION`.

## 8. Compatibility impact

- `codeagent/verify.py` `DEFECT_REPORT_KEYS` derives from `DEFECT_KEYS`, so
  `grounding_status` reaches reports automatically; the three blocking-only fields do
  **not**, preserving the existing prose-filtering intent.
- `state/db.py record_eval_case_defects` reads fixed columns via `.get()`. Extra keys are
  ignored — **no database migration, and grounding fields are not persisted.** Measuring
  the live distribution of `grounding_status` would require a schema migration on
  `.engine/state.db`, which is unbacked-up; that is deliberately **not** done here and is
  recorded as future work.
- Existing test fixtures that construct critic defects require the new required key.
  Fixtures exercising `verdict.merge`/`gate` only are unaffected.
