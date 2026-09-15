# Registration B — Optional Evidence Capture in the Judge Prompt

**Status: REGISTERED, FROZEN. No run has been executed against it.**

Pre-registered per `.claude/skills/experiment-design`. Every decision rule below was
written before any measurement of this intervention existed. Nothing here may be edited
after the first run; a rule that turns out to be badly chosen is recorded as a lesson for
the next experiment, not retrofitted onto this one.

This document does not modify any historical registration.
`GROUNDED_SEVERITY_EXPERIMENT_REGISTRATION.md`, `STRUCTURED_GROUNDING_REGISTRATION.md` and
the rest stand exactly as written.

---

## 0. What this experiment is, in one sentence

Ask the judge for three **optional** evidence annotations per defect, record them through
the verdict-neutral shadow adjudication path, and measure whether a judge will supply
machine-checkable evidence at all — **without** letting any of it touch a verdict.

**Hypothesis (falsifiable).** Appending optional evidence-capture wording to
`RESPONSE_INSTRUCTION` raises the share of blocking defects that reach a
non-`fail-closed-unresolved` admissibility rule from approximately 0% (the control prompt
asks for no evidence, so nothing is adjudicable) to at least 40%, without producing a false
pass, without reducing reported defect counts, and without shifting blocking severity mass.

**What a negative result looks like.** The intervention arm's adjudication-resolution rate
(E2, §11) stays below 40% — the judge either ignores the optional fields or fills them with
values that do not survive `extract_evidence`. That is a complete, publishable result and
closes the experiment as INCONCLUSIVE-futility. It is recorded with the same weight as a
positive one.

---

## 1. Frozen configuration

| item | value |
|---|---|
| branch | `feature/agent-capabilities-layer` |
| base SHA (control) | `41584085dc098ed9a9e97772389cf9354136cfb3` |
| measured path at registration | **identical to `4158408`** — the commit carrying this document changes only `cli.py`, tests and `docs/`, none of which is on the measured-path list |
| dataset version | **v6** (`dataset.py:34 DATASET_VERSION = "v6"`), 40 cases |
| provider | `anthropic` |
| judge model | **`claude-sonnet-5`** (`config.py DEFAULT_MODELS["anthropic"]["judge"]`) |
| judge `max_tokens` | 1600 (`judge.py:198`) |
| `MAX_JUDGE_RETRIES` | 1, budget-exhaustion only (`judge.py:122`) |
| control `judge.py` blob | `2a2a17f16611d4586d122d6e65710f9bd520910f` |
| control `RESPONSE_INSTRUCTION` sha256 | `e5dd7f825008a752c19d4dc77fbec65ed74be9dbfc36c29c2bc9691c9924dd4f` (1439 chars) |
| adjudicator version | `adjudication/1` |

### 1.1 The control prompt is itself an unvalidated configuration

`judge.py` blob `2a2a17f1` at HEAD is **byte-identical to `fd8f136`** — the grounded-severity
prose ceiling, formally **CLOSED as INCOMPLETE / INCONCLUSIVE** (BASELINE.md,
"Grounded-severity ceiling"). The control arm is therefore not a neutral pre-experiment
configuration; it is a second unvalidated one. This is a statement about the code, not a
measurement, and it is recorded here so no reader mistakes the control arm for a validated
reference.

### 1.2 There is no measured baseline at this configuration

Five measured-path files differ between `16309b5` (the last arm with completed runs, 50-53)
and HEAD: `runner.py`, `judge.py`, `pipeline.py`, `rubric.py`, `verdict.py`. Four still
differ from `fd8f136` (runs 54, 55): `runner.py`, `pipeline.py`, `rubric.py`, `verdict.py`.

**The configuration cluster at HEAD holds zero completed runs.** No run in BASELINE.md is a
valid baseline for it. Per `experiment-design`, when no measured rate exists at the current
configuration, **measuring it is the first experiment** — that is what Phase 0 (§8) is for,
and it is why every guardrail below compares against a **concurrently measured control arm**
rather than a historical figure.

---

## 2. Independent variable

**Exactly one:** optional evidence-capture wording added to `RESPONSE_INSTRUCTION` in
`src/engine/verification/judge.py`.

Nothing else changes between arms. Both arms run with `--shadow-adjudicate`, at the same
dataset version, the same judge model, the same token cap, from the same branch.

---

## 3. Optional evidence fields

Exactly three. **All optional, forever.** A defect carrying none of them is unadjudicated,
not malformed, and keeps its blocking authority in full.

| field | meaning | adjudicable today? |
|---|---|---|
| `grounded_in_clause` | a span of the task text copied verbatim that the finding rests on | **no** — captured and persisted, but no `Fact` consumes it |
| `minimal_trigger` | smallest concrete argument demonstrating the defect, as `name=<python literal>` | yes — `_adjudicate_trigger` |
| `grounding_route` | one value from the canonical enum below | yes — `_from_facts` |

### 3.1 `grounded_in_clause` is record-only, by design and at present

Verified in source: `extract_evidence` (`adjudication.py:124`) captures it and
`asdict(Evidence)` persists it to `evidence_json`, but `_adjudicate_guarantee` reads
`excluded_by_clause`, **not** `grounded_in_clause`, and `_from_facts` never references it.
It therefore has zero decision power in this experiment and contributes to E1 (capture) but
never to E2 (resolution). This is recorded now so that a later reader does not assume it was
doing work it was not.

### 3.2 Canonical `grounding_route` enum — use exactly these four

```
explicit_requirement
permitted_input
stated_purpose
none/unclear
```

These are `rubric.py:26 GROUNDING_ROUTES` verbatim. **`rubric.py` is not modified by this
experiment.**

Two values are **excluded**, decided before any run:

- **`runtime_premise` — excluded on substance.** A judge labelling its own claim
  `runtime_premise` asserts `premise_depends_on_runtime_behaviour`, which §4 reserves for the
  independent adjudicator. It is also absent from `GROUNDING_ROUTES`, so `extract_evidence`
  would discard it silently.
- **`none_or_unclear` — excluded as a spelling mismatch** with the canonical `none/unclear`.

**Measured consequence of getting this wrong:** an out-of-enum route is set to `None` by
`extract_evidence` and the raw string is recorded nowhere, making "judge omitted the route"
indistinguishable from "judge emitted an unrecognised route." Confirmed offline against
`runtime_premise` and `none_or_unclear`. The prompt must emit only the four canonical values.

### 3.3 Two existing evidence keys are deliberately NOT requested

`rubric.py ADJUDICATION_EVIDENCE_KEYS` contains five keys. The judge is asked for three. The
two withheld are exactly the two that can strip blocking authority through a premise the
judge itself would author:

| key | consumed at | effect if verified/contradicted |
|---|---|---|
| `excluded_by_clause` | `adjudication.py:294` → `premise_excluded_by_guarantee` | `admissible_to_block = False` |
| `runtime_probe` | `adjudication.py:280` → `violation_present_in_submitted_code` | `admissible_to_block = False` |

Requesting `excluded_by_clause` would be asking the judge to argue its own finding away.
Neither may be added to the prompt under this registration.

`minimal_trigger` **can** remove blocking authority (`declared-interface`), and is scoped in
the prompt to an **argument binding** — never `return=...`, which would route into
`_adjudicate_return` / `violation_present_in_submitted_code`, a §4 adjudicator-owned fact.
Under shadow mode this power is inert; it becomes live only if an authoritative phase is ever
separately registered.

---

## 4. Adjudicator-owned facts — the judge may not decide these

The judge **asserts**; the adjudicator **decides**. The judge must never be asked whether:

- `trigger_in_contract`
- `premise_excluded_by_guarantee`
- `premise_depends_on_runtime_behaviour`
- `violation_present_in_submitted_code`
- `self_contradiction`
- the adjudication status
- `admissible_to_block`
- whether the finding should block, count toward pass/fail, or is admissible

**Severity remains independent of evidence availability.** The prompt must state that
severity is assigned from defect impact alone and must never be raised or lowered because an
annotation was present, absent, easy, or hard to produce.

---

## 5. Prompt placement — RATIFIED

The evidence block goes **BEFORE** the existing grounded-severity ceiling. The ceiling
remains the **final text** in `RESPONSE_INSTRUCTION`.

Rationale: `judge.py:45-51` records that the ceiling's placement is "the end of the string,
as registered, so placement is not a second variable." Appending after it would displace the
strongest severity guard from the most-recent position and introduce exactly the second
variable that note exists to prevent. Placement is fixed here and is not an experimental
variable.

---

## 6. Shadow-only first phase

Every run under this registration uses `engine bench --shadow-adjudicate`.

`run_verification(shadow_adjudicate=True)` writes adjudication records to
`merged["shadow_adjudications"]`, a key `verdict.gate` never reads. `admissibility.annotate`
is not called and `merged["defects"]` is not touched, so nothing the adjudicator concludes
can reach `verdict._has_blocking`. Pinned by `tests/test_shadow_adjudication.py`.
`adjudicate=True` and `shadow_adjudicate=True` together raise `ValueError`, and the CLI
exposes no authoritative flag at all.

### 6.1 Shadow mode does NOT make this experiment safe

**This is the most important sentence in this document.** Shadow mode makes the
**adjudication layer** verdict-neutral. It does nothing whatsoever about the **prompt**.
`verdict._has_blocking` reads `d["severity"]` directly on every path, shadow or not. A prompt
change that moves one HIGH to MEDIUM produces a false pass with `--shadow-adjudicate` exactly
as it did at run 57 without it.

The intervention therefore carries **full false-pass risk on its first live run**, which is
why §12's STOP rules are absolute and why Phase 1 is N=1.

---

## 7. Target cases

Baseline rates below are **historical context at other configurations**, not baselines for
this one (§1.2). Phase 0 measures the real control figures concurrently.

| case | why it is a target | historical context |
|---|---|---|
| `quality-04-broken` | **primary drift sentinel.** The false pass in run 57 (structured grounding) *and* in run 52 (grounded-severity baseline arm) — a known background risk at more than one configuration | false_pass in 52 and 57; run 57 record was `correctness/MEDIUM`, `code-quality/MEDIUM`, `code-quality/LOW` — zero blocking defects |
| `edge_case-02-clean` | primary target of both prior prompt experiments | 3/4 OK in the fresh baseline arm 50-53; 1/2 in 54-55; OK in run 57 (n=1, no efficacy claim) |
| `security-04-clean` | redundant blocking mass — needs every finding demoted to flip, so it measures partial drift the verdict hides | blocking count 4/4/4/4 in the baseline arm; 1 in run 54, 2 in run 55 |
| `security-03-clean` | **negative control.** Its failure mode is an `automated`/mypy gate, and `automated_defects()` hardcodes `severity = "HIGH"` independent of `LENSES` / `RESPONSE_INSTRUCTION` | prompt text structurally cannot reach this path; any movement here is coding-agent variance, never a prompt effect |

---

## 8. Phases

No phase begins without the previous one passing every rule in §12.

| phase | arms | N per arm | prompt | purpose | approx cost |
|---|---|---|---|---|---|
| **0 — control / instrumentation** | control only | 4 | **control (unchanged)** | establish the cluster's first measured baseline; confirm shadow persistence works live; measure the evidence-availability floor (expected ~0%) | ~$2.92 |
| **1 — L0 smoke** | intervention only | 1 | intervention | first live measurement of the prompt; safety gate only | ~$0.90 |
| **2 — Stage 1** | control + intervention | 4 | both | first comparative measurement | ~$6.60 |
| **3 — Stage 2** | control + intervention | 8 | both | only if Stage 1 clears §13 | ~$13.20 |

**Phase 0 runs the control prompt.** The prompt intervention is **not implemented** at
registration time. Implementing it is a separate, separately approved commit touching
`judge.py` — a measured-path file — and starts a new configuration cluster.

### 8.1 Sample size

σ ≈ **0.92 cases**, pooled from the `c0515eb` (runs 20-28) and `be990c7` (runs 29-36)
identical-configuration clusters. **σ is carried over** past `77d36c3` and past every
measured-path change since, including this branch's; it is the best available figure and is
not a measurement at this configuration.

At σ = 0.92, aggregate accuracy, two-sample, α=0.05, 80% power: N=4 detects ~1.8 cases, N=8
detects ~1.3 cases. The **primary** metric is per-case, a proportion test unaffected by σ: at
N=4 only an all-or-nothing 4/4 movement can register (p=0.029); **at N=8, ≥5/8 is the
threshold** (p=0.026) and 4/8 does not clear it (p=0.077). This is why Stage 2 is N=8 and why
Stage 1 alone can never ACCEPT.

---

## 9. Frozen variables

Not modified by any phase of this experiment:

```
src/engine/eval/dataset.py
src/engine/verification/rubric.py          (incl. GROUNDING_ROUTES, DEFECT_KEYS)
src/engine/verification/schema.py
src/engine/verification/verdict.py
src/engine/verification/adjudication.py
src/engine/verification/admissibility.py
src/engine/verification/probes.py
src/engine/verification/pipeline.py
src/engine/eval/runner.py
src/engine/runtime/gateway.py
src/engine/runtime/budget.py
src/engine/config.py                       (DEFAULT_MODELS)
```

`DEFECT_KEYS` is **not widened**. The optional fields rely on `enforce_critic_schema` already
tolerating extra defect-level keys (`schema.py:20` checks only for *missing* required keys;
stray-key rejection at `schema.py:53` is top-level only). Verified offline across 13 output
shapes — all VALID, zero retries, core fields intact.

The only file the intervention may touch is `src/engine/verification/judge.py`, and within it
only `RESPONSE_INSTRUCTION`. `LENSES` is frozen.

---

## 10. Safety controls

1. Shadow-only. `adjudicate=True` is never enabled under this registration.
2. `git-safety` pre-run gate before every run: clean tree, recorded SHA, SHA matches this plan.
3. Every run recorded in BASELINE.md with its reproducibility fields, valid or void.
4. Any run with ≥1 `eval_case_results.error` row is **VOID** and excluded (run 56 precedent).
5. `.engine/state.db` is append-only, written solely by `engine bench`. Analysis reads a
   scratchpad copy.
6. No post-hoc threshold changes (§14).

---

## 11. Metrics

### Efficacy (this experiment's actual question)

- **E1 — evidence-capture rate.** Share of all defects carrying ≥1 of the three fields
  surviving `extract_evidence`. Includes `grounded_in_clause`.
- **E2 — adjudication-resolution rate (PRIMARY).** Share of **blocking** (CRITICAL/HIGH)
  defects whose shadow record's `rule` is **not** `fail-closed-unresolved`. Excludes
  `grounded_in_clause`, which cannot resolve anything (§3.1).
- **E3 — route distribution.** Counts per `grounding_route`, including `NULL` (omitted or
  out-of-enum, which are indistinguishable — §3.2).

### Safety (these decide, and they outrank efficacy)

- **S1 — `false_pass`.** Zero tolerance. STOP rule, §12.1.
- **S2 — schema failures per run.** Abort threshold 6, §12.2.
- **S3 — per-lens severity distribution**, captured for **both** arms, §12.3.
- **S4 — `quality-04-broken` blocking count**, §12.4.
- **S5 — sole-blocker loss**, §12.5.
- **S6 — total defect count per case** (defect-suppression guard), §12.6.

### Secondary (reported, never decisive)

Aggregate accuracy (`correct_verdicts / 40`), `false_unverified` across the 20 clean cases,
cost, wall time.

### Evidence-availability threshold (futility floor)

**E2 ≥ 40% in the intervention arm**, measured over blocking defects pooled across the arm.

Rationale, fixed in advance: `fail-closed-unresolved` is the default outcome and preserves
blocking authority. An adjudication layer that resolves fewer than 40% of blockers cannot
change enough to justify an authoritative phase, so continuing would spend money on a layer
that is almost always inert. Below this floor the experiment closes **INCONCLUSIVE-futility**
(§13.3) regardless of how clean the safety metrics look.

---

## 12. STOP rules — absolute, and they cannot be waived

Every rule here is evaluated **before** any efficacy metric. Each fires on its own. The
mandatory attribution analysis that follows a STOP **cannot reverse it**; that asymmetry is
accepted now, in advance, precisely so it cannot be argued away once a rule fires — the same
asymmetry that made the run-57 REJECT stick.

### 12.1 False pass — `false_pass >= 1` ⇒ immediate REJECT / STOP

Any new false pass in **any** arm, in **any** phase, ends the experiment immediately. The
prompt is reverted. Zero tolerance, no per-case exception, including for `quality-04-broken`
even though it is a known background risk at other configurations (runs 52, 57).

### 12.2 Schema failures — abort threshold = 6 per run

A run with **≥6** schema failures aborts the phase. Run 57 recorded 4 against this same
threshold. Rationale: the block adds ~1000 characters to a 1439-character instruction against
a 1600-token cap, and truncation fails closed to UNVERIFIED — so S2 is the metric most likely
to move first. Attribution is recorded on every abort: novel evidence-field rejections must be
separated from the pre-existing `verdict`/`defects` consistency check.

### 12.3 Severity drift — per-lens severity distribution, both arms

Captured for control and intervention. A **material shift of blocking mass** (CRITICAL/HIGH)
into MEDIUM/LOW in the intervention arm is a **REJECT signal**, evaluated per-lens and in
aggregate. This is run 57's exact mechanism (a blocking finding relocated to MEDIUM rather
than suppressed) and shadow mode does not protect against it (§6.1).

### 12.4 `quality-04-broken` drift guardrail

- Its blocking (CRITICAL/HIGH) defect count **must not fall from ≥1 in control to 0 in
  intervention** in any paired run. Falling to zero ⇒ **immediate REJECT**.
- A **material HIGH/CRITICAL → MEDIUM/LOW mass shift** on this case is a **REJECT signal**
  even when the verdict does not move.

### 12.5 Sole-blocker loss ⇒ immediate REJECT

Any case whose verdict rests on a single blocking defect in control, and which loses that
defect's blocking severity in intervention, ends the experiment. Approximately 12 of the 20
broken cases rest on a single blocking defect at some point and ~7 on a lone HIGH; that is the
margin a demotion mechanism aims straight at.

### 12.6 Defect suppression

A material fall in total reported defects per case (S6) in the intervention arm is a **REJECT
signal**. Reporting must be unaffected: the prompt says so explicitly, and this rule measures
whether it held.

### 12.7 Cost stop-loss

See §15.

---

## 13. ACCEPT / REJECT / INCONCLUSIVE

### 13.1 ACCEPT (Stage 2 only; Stage 1 can never ACCEPT)

All of:

- **A1** — zero false passes in every valid run of every phase (§12.1)
- **A2** — no rule in §12.2-§12.6 fired in any valid run
- **A3** — E2 ≥ 40% in the intervention arm (§11)
- **A4** — E2 in the intervention arm exceeds the control arm by a margin larger than the
  control arm's own observed spread
- **A5** — at N=8, the per-case primary metric clears **≥5/8** on at least one target case, or
  E2 separation is unambiguous with every §12 guardrail clean
- **A6** — aggregate accuracy not materially worse; reported as secondary, never decisive
- **A7** — `security-03-clean` (negative control) shows no prompt-attributable movement

ACCEPT authorises **continued shadow capture only**. It does **not** authorise
`adjudicate=True`; an authoritative phase requires its own separate registration.

### 13.2 REJECT

Any STOP rule in §12 fires, in any phase, in any valid run.

### 13.3 INCONCLUSIVE

- **INCONCLUSIVE-futility** — E2 < 40% (§11) with safety metrics clean. The judge will not
  supply adjudicable evidence when merely invited to. A complete, recorded result.
- **INCONCLUSIVE-per-registration** — N per arm not reached for a reason internal to the design.
- **INCOMPLETE** — stopped for an external reason (API credit, infrastructure). Explicitly
  **not** a registered verdict and may not be cited as one. Run 56 and the grounded-severity
  Stage 1 are the precedents.

---

## 14. Anti-post-hoc rules

- Decision rules are written above, before results exist, and are **never edited afterward**.
- **No post-hoc threshold changes.** The 40% floor, the 6-failure abort, the zero-tolerance
  false-pass rule and the N per arm are fixed now.
- No metric added after seeing data and presented as the endpoint.
- No re-slicing until something is significant. Inconclusive is recorded as inconclusive.
- A negative result is recorded with the same weight as a positive one.
- **One change per experiment.** No dataset change, no schema change and no severity-rule
  change may be bundled with any phase.
- Extension rules must be pre-registered to be legitimate. None is pre-registered here:
  **there is no "run a few more" option** under this registration.

---

## 15. Cost ceiling

Basis: v6 runs at `claude-sonnet-5` measured $0.51-0.56 (runs 50-53, control prompt lineage),
$0.72-0.73 (runs 54-55, same `judge.py` blob as HEAD), $0.91 (run 57, a larger prompt than
this one proposes). Wall time ~10-11.5 min per 40-case run.

| phase | runs | est. cost |
|---|---|---|
| 0 | 4 | ~$2.92 |
| 1 | 1 | ~$0.90 |
| 2 | 8 | ~$6.60 |
| 3 | 16 | ~$13.20 |
| **total** | **29** | **~$23.62** |

**Hard stop-loss: $30.00 cumulative.** Reaching it halts the experiment regardless of phase or
result, recorded as INCOMPLETE. Each phase is separately approved before it runs; approval of
one phase never carries to the next.

---

## 16. Exact next-phase requirements

Before **any** live run under this registration:

1. **Approval per turn** for the specific run, per `git-safety`. Analysis never implies
   permission to execute.
2. **Pre-run gate passed:** `git status --porcelain` empty, `git rev-parse HEAD` recorded, SHA
   matches this plan. `get_git_commit_sha()` records HEAD, not the working tree — a dirty tree
   permanently misattributes a run.
3. **Phase 0 first.** It runs the **control** prompt and needs no `judge.py` change.

Before Phase 1 additionally:

4. **The prompt intervention implemented in its own separate commit**, touching only
   `RESPONSE_INSTRUCTION` in `judge.py`, placed before the grounded-severity ceiling (§5),
   emitting only the four canonical routes (§3.2), requesting only the three fields (§3), and
   asking nothing from §4.
5. **The intervention SHA recorded here** once it exists, and the new `RESPONSE_INSTRUCTION`
   sha256 recorded alongside the control hash in §1.
6. **Phase 0's measured control figures recorded in BASELINE.md** before any intervention run,
   so the comparison has a real baseline at this configuration rather than an assumed one
   (§1.2 — the grounded-severity registration's assumed 0/4 baseline measured 3/4 when run
   fresh; that precedent is why this step is mandatory).

Analysis of a phase's results never authorises the next phase. Each is a separate decision.

---

## 17. Provenance

- Registered: 2026-09-11
- Base SHA: `41584085dc098ed9a9e97772389cf9354136cfb3`
- Offline review that produced this design: schema/parse compatibility verified across 13
  synthetic output shapes; evidence propagation traced judge → merge → shadow → sidecar;
  `grounded_in_clause` confirmed record-only; `runtime_premise` / `none_or_unclear` confirmed
  discarded by `extract_evidence`. No model call, no benchmark run, no spend.
- Runs executed against this registration at time of writing: **none.**
