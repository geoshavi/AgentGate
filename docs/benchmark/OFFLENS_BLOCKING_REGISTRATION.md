# Pre-registration — off-lens blocking authority

**Status: PRE-REGISTERED. No run has been executed under it. No production code changed.**

| | |
|---|---|
| Registered | 2026-09-02 |
| Branch | `feature/agent-capabilities-layer` |
| HEAD at registration | `c41e2654233b42c507e6d127702f62e09ea02646` |
| Benchmark | `engine-review-benchmark`, `benchmark_version = v2`, `dataset_version = v4` |
| Cases | 40 (20 clean / 20 broken) |

**Naming, to prevent a collision.** This is *Verifier Hardening Phase 4*. It is **not**
the "Phase 4 intervention" already recorded in `BASELINE.md` (runs 29-36, commit
`be990c7`, judge-prompt calibration appended to `RESPONSE_INSTRUCTION`). Different
experiment, different mechanism, different phase numbering scheme. Where this document
says "the earlier Phase 4" it means the `BASELINE.md` one.

Registration is committed before the first run because `BASELINE.md` records a hygiene
finding that the previous registration (`PHASE4_REGISTRATION.md`) was cited by a commit
message but never committed, and its text is not recoverable from this repository.

## 1. Origin

A live Debug Agent run (`dbg-79fdf444`) returned UNVERIFIED on a correct, PROVEN fix: the
`security` lens emitted a `CORRECTNESS`/`HIGH` defect re-asserting a bug the reviewed
snapshot no longer had. Forensics cleared the machinery — the recorded snapshot bytes
reproduce exactly from the post-fix files, there is no caching, and each lens call carries
no history. A separate offline probe (12 trials, 4 neutral-docstring fixtures) reproduced
the same signature on one fixture 3/3, with the lens explicitly stating the bug was fixed
and blocking anyway.

## 2. Candidate rule

### How off-lens is determined

```
LENS_DIMENSION = {"correctness": "CORRECTNESS",
                  "security":    "SECURITY",
                  "code-quality":"CODE-QUALITY"}

off_lens(d) := d.lens in LENS_DIMENSION and d.category != LENS_DIMENSION[d.lens]
```

A defect whose `lens` is absent or is `automated` — the ruff/mypy/pytest defects from
`automated_defects()` — is **never** off-lens and **always retains blocking authority**.

### R-a (primary)

A defect is blocking iff `severity in rubric.BLOCKING` **and** `not off_lens(d)`.

Off-lens defects remain in `merged["defects"]`; they are still recorded, sanitised,
reported and rendered exactly as today. They lose blocking authority only.

### R-b (secondary, scored free, drives no decision)

The rule as originally phrased: an off-lens defect blocks only if the lens owning its
claimed category independently produced a blocker.

**R-b is dominated by R-a.** `blockers(R-a) ⊆ blockers(R-b)`, so R-a carries at least the
false_pass risk of R-b, and clearing R-a clears R-b. R-a is also the simpler
implementation — one predicate, no cross-lens lookup. R-b is scored only to answer the
report-labelling question and never contributes to ACCEPT/REJECT.

### Two structural claims, registered as claims

1. **Monotonicity.** R-a only removes blockers, so a verdict can move only
   `UNVERIFIED -> OK`, never the reverse. `false_unverified` can therefore only decrease
   and `false_pass` can only increase. **The experiment reduces to: does any broken case
   flip?**
2. **No noise floor on the contrast.** Both arms are scored from the *same* stored model
   outputs, so the A/B difference within a run has zero sampling error. The measured
   sigma (0.92 cases, v3-pooled) governs run-to-run variation in which defects appear,
   not the within-run contrast. Repeats test generalisation, not noise.

## 3. Measurement method

The rule is merge/gate-only, so one set of paid judge calls scores both arms. **No paid
call is duplicated for the A/B contrast, and the rule is NOT implemented to run the
experiment.**

1. Run stock `engine bench` at the registered HEAD. Nothing in `src/` is modified.
2. `engine bench` already stores each defect's `lens`, `category` and `severity` in
   `eval_case_defects`.
3. Score offline against a scratchpad copy of `.engine/state.db`:
   - **Arm A** — current `verdict.gate`, which is also the run's own recorded verdict.
   - **Arm B** — R-a applied to the identical defect rows.

### Per-run integrity gate

A run failing any of these is void and is not scored:

- zero `eval_case_results.error` rows
- 120/120 `eval_case_lens_results.call_status = ok`
- all `eval_case_automated_gates.passed = 1`
- **reconstruction exact**: recomputing Arm A verdicts from stored defects reproduces
  `actual_verdict` for all 40 cases, 0 mismatches

The reconstruction check is the load-bearing one — it is what makes offline Arm B scoring
trustworthy. It was validated across 1,200 cases / 30 runs (runs 13-42) at 0 mismatches.
Runs before 13 are excluded from any such analysis: run 2 predates defect-level
observability and runs 10/12 predate schema-failure recording.

## 4. Metrics

Reported per run and pooled, for both arms:

- total accuracy (`correct_verdicts / 40`)
- `false_pass`
- `false_unverified`
- clean vs broken outcomes (20/20 split)
- every per-case verdict change, by `eval_case_id`

### Guardrails

- **All 20 broken cases** — the safety set, checked every run for the flip condition.
- **`security-03-clean`** — tracked by name, every run, under both arms. `BASELINE.md`
  records it as the unregistered adverse finding of the earlier Phase 4 (100% -> 37.5%,
  the largest per-case movement that experiment produced) and recommends it as a
  pre-registered guardrail for any future intervention touching severity calibration.
  Expected to improve or hold; any degradation is reported as an adverse finding.
- **Schema-error cases** — verdicts must be identical under A and B. Asserted as an
  integrity check rather than assumed.

Schema errors and failed automated gates continue to fail closed to UNVERIFIED, ahead of
any defect logic. R-a touches only the blocking-defect test.

## 5. Decision criteria

- **REJECT (hard, zero tolerance).** Any broken case (`expected_verdict = UNVERIFIED`)
  that blocks under A and returns OK under B, in any run. One occurrence rejects the rule.
- **ACCEPT.** Across all 8 runs: zero broken-case flips AND at least one clean-case fix.
- **INCONCLUSIVE.** Zero flips and zero fixes — the rule is a no-op on this dataset.

Written before the first run and not to be edited afterward. If a criterion proves badly
chosen, that is a lesson for the next registration, not a retrofit onto this one.

## 6. Sample size and stages

| stage | runs | lens calls | est. cost |
|---|---|---|---|
| 1 — gate | 1 | 120 | ~$0.14 |
| 2 — extension | 7 | 840 | ~$0.98 |
| total | 8 | 960 | ~$1.12 |

Hard experiment ceiling **$2.00**; abort and report partial if exceeded.
`BENCHMARK_PLANNED_BUDGET` ($3.00/run) remains the in-process backstop. Cost basis: run 42
(v4) cost $0.1302; v3 mean $0.1287.

Stage 1 passing authorises **stage 2 only** — never implementation, which is a separate
phase with its own approval. At n=8 this also establishes **v4's first dispersion
estimate**; v4 currently holds one run (42) and has no sigma of its own.

**Registered extension rule.** Runs 2-8 are authorised by stage 1 passing its integrity
gate and flip criterion, and by nothing else. No run is added because a result was
"almost" significant.

## 7. Prior evidence — prior only, not confirmation

Historical counterfactual over runs 13-42 (reconstruction exact, 1,200 cases). This is
retrodiction on stored data and is explicitly **not** the confirmation result.

Off-lens emission is routine, not exceptional:

| lens | off-lens defects | off-lens share of its blocking defects |
|---|---|---|
| `correctness` | 81 / 1,264 (6.4%) | 7.4% |
| `security` | 362 / 1,168 (31.0%) | 36.2% |
| `code-quality` | 448 / 1,661 (27.0%) | 49.6% |

Dominant pairs: `security -> CORRECTNESS` (359), `code-quality -> CORRECTNESS` (357).

Decisiveness, across 961 blocked cases (runs 2-42): an off-lens blocking defect was
present in 438 but was the **sole** blocker in only 6 (0.6%) — and all 6 were on clean
cases. **In the recorded history an off-lens defect has never been the only lens catching
a real defect on broken code.**

Safety margin on the 539 blocked broken cases (runs 13-42):

| on-lens blockers backing the case | cases |
|---|---|
| **0 — would flip** | **0** |
| 1 | 295 (54.7%), of which 279 also carry an off-lens blocker |
| 2 | 164 |
| >=3 | 80 |

Historical candidate-induced false_pass rate: **0/539**. But 55% of blocked broken cases
rest on a *single* on-lens blocker while the security lens goes off-lens 31% of the time,
so safety depends on the on-lens lens firing at all. The margin is real but thin — which
is why fresh measurement is required and why the flip criterion is zero-tolerance.

Under this rule the 6 historical changes are all clean-case fixes, 5 of them
`security-03-clean` in runs 29-35 — identifying the mechanism behind the earlier Phase 4's
flagged adverse finding.

## 8. Frozen — must not change during the experiment

Lens prompts (`LENSES`), `RESPONSE_INSTRUCTION`, `judge.py`, schema parsing
(`schema.py`), `rubric.py` severity definitions, `verdict.py`, `eval/dataset.py`,
benchmark fixtures, and model config (`claude-sonnet-5`, `max_tokens = 1600`,
`BENCHMARK_MAX_TOKENS = 400_000`).

Because Arm B is scored offline, **none of these is touched to run the experiment**. The
paid run is a stock `engine bench`.

## 9. Honest limits

- The benchmark's benefit rate is ~0.2 changed verdicts per run, so 8 runs expects ~1.7
  fixes. **This experiment's job is safety clearance**, not demonstrating benefit.
- The benefit lives on the Debug Agent path, where sole-blocker exposure measured 25%
  (12-trial probe) against 0.6% here — because on a correct fix the on-lens lenses
  correctly stay silent, leaving an off-lens finding unaccompanied. That is a separate
  measurement and is not this one.
- Retrodiction covers benchmark cases: single-defect authored snippets where the correct
  lens reliably fires. 1,200 cases is a bound, not a proof; a real repository could hold a
  defect the "wrong" lens spots first.
- v4 currently has n=1, so no v4 dispersion estimate exists yet. Any sigma applied before
  stage 2 completes is carried over from the v3 `c0515eb`/`be990c7` clusters and must be
  labelled as such.

---

# Amendment 1 — 2026-09-02

Registered after the first stage-1 attempt aborted and **before any A/B contrast was
observed.** That ordering is what makes this amendment legitimate: run 43 produced no
scoreable result, so nothing here is a decision rule retrofitted to an outcome.

**Sections 2, 3, 4 and 5 are unchanged** — the candidate rule, the paired method, the
metrics and guardrails, and the ACCEPT/REJECT criteria all stand exactly as registered.
This amendment corrects factual premises only: sections 6 and 7.

## A1.1 — Void run: eval_run 43

The stage-1 attempt was killed by a 10-minute harness timeout partway through.

| | |
|---|---|
| `eval_runs.id` | 43 |
| `git_commit_sha` | `e002b6b25cad0d8128ec258a89651feaf82e3aa2` |
| cases written | 35 of 40 |
| lens calls | 108 of 120 |
| spend | $0.5133 |
| `total_cases` recorded | **0** — the aggregate update never ran |
| `runs.id` 52 | left at `status = 'running'` |

**Run 43 is VOID and must never be scored or averaged.** It fails the section 3 integrity
gate (incomplete case set, no final aggregate). Its row is retained rather than deleted
because `.engine/state.db` is append-only and unbacked-up; it is documented here instead.

**Read the `total_cases = 0` with care.** This is the same shape as run 1, the denominator
trap described in the schema reference: a row whose numerator was never populated is not a
0/40 result.

## A1.2 — Corrected cost basis (supersedes section 6)

Section 6 estimated ~$0.14/run from run 42's recorded $0.1302. **That basis was wrong**: it
did not account for the judge model differing between run 42 and HEAD.

| | judge model | calls | spend | avg output tokens | avg latency |
|---|---|---|---|---|---|
| runs 37-42 | `claude-haiku-4-5-20251001` | 120 | ~$0.12 | 123-134 | ~1.6 s |
| run 43 | `claude-sonnet-5` | 108 | $0.5133 | 355 (cap 1600, reached) | 5.2 s |

Measured at HEAD: **~$0.57 per run, ~10.3 minutes per run** — roughly 4.4x the cost and 3x
the wall time. Sonnet 5 prices at 2x Haiku and emits ~2.8x the output tokens because it
thinks adaptively, the behaviour `judge.py`'s Phase 9C/9E comments already document.

The 8-run plan therefore costs **~$4.56**, not ~$1.12, exceeding the registered $2.00
ceiling. **The stage plan and the $2.00 ceiling in section 6 are SUSPENDED** pending the
open decision in A1.4. No further paid run is authorised under this registration until
that decision is recorded here.

## A1.3 — Comparability break (qualifies section 7)

Commit **`83a4000` "Experiment: upgrade judge to Sonnet 5"** changed
`DEFAULT_MODELS["anthropic"]["judge"]` from `claude-haiku-4-5-20251001` to
`claude-sonnet-5`. Every recorded benchmark run, 1 through 42, used Haiku. Run 43 was the
first attempt at Sonnet.

The judge model is part of the measured configuration, so:

- **v4 holds zero completed runs at the current configuration.** Run 42 is not a baseline
  for HEAD. This is the *second* independent reason — the first, found earlier, is the
  89-line `judge.py` Phase 9C/9E delta between `c2ec1e4` and HEAD.
- **Section 7's prior evidence is Haiku-derived.** The off-lens emission rates (security
  31.0%, code-quality 27.0%, correctness 6.4%), the 6/961 sole-blocker figure, and the
  0/539 flip record all describe *Haiku's* behaviour. Sonnet's rates may differ
  materially, and run 43's much larger output volume is direct evidence its defect
  behaviour is not Haiku's.

**What survives the model change unaffected**, because none of it depends on model
behaviour: the monotonicity claim (section 2, result 1), the R-a/R-b dominance claim
(section 2, result 2), and the offline reconstruction method (section 3), whose validation
was a property of the stored-data arithmetic rather than of any model.

## A1.4 — Open decision, deliberately not made here

Which judge model this experiment runs on is now a real fork and is left to the operator:

- **Sonnet 5** — tests the configuration the branch actually uses, at ~$4.56 for 8 runs,
  compared against zero historical runs.
- **Haiku 4.5** — comparable with runs 13-42 at ~$1.00 for 8 runs, but tests a
  configuration the branch appears to have moved away from deliberately.

Whichever is chosen must be recorded as a further amendment **before** the run, and the
prior evidence in section 7 may only be cited as a prior for the Haiku configuration.

## A1.5 — Governance finding

`src/engine/config.py`'s `DEFAULT_MODELS[...]["judge"]` selects the model every judge lens
runs on. It is as decisive for the measured configuration as `judge.py`'s prompts, yet it
is **not** in the `git-safety` measured-path list. It could therefore be changed without
the explicit approval that list exists to require, and doing so started a new
configuration cluster with no run recorded and no note in `BASELINE.md`.

Recommendation, for a separate decision: add `src/engine/config.py` (or at minimum
`DEFAULT_MODELS`) to the measured-path list, and record run 43 plus the Haiku-to-Sonnet
switch in `BASELINE.md`, so a later reader does not mistake the model change for noise or
read run 43's empty row as a result.
