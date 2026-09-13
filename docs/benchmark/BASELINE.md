# Benchmark Baseline

Chronological snapshot of `engine-review-benchmark` runs, read directly from `.engine/state.db` (`eval_runs` table). Generated 2026-08-06. Extended 2026-08-10 with runs 20-36 (see Notes). Extended 2026-08-14 with run 37 (see Notes). Extended 2026-09-02 with runs 38-43, recorded retroactively from `.engine/state.db` (see Notes — runs 38-42 completed before this entry was written; run 43 is VOID). Extended 2026-09-08 with run 46 (recorded retroactively from `.engine/state.db`, run 46 itself predates this entry) and the Dataset v5 boundary (see Notes).

| run | date | commit sha | dataset_version | accuracy | false_pass | false_unverified | cost | what changed |
|-----|------------|------------|------------------|----------------|-------------|-------------------|---------|------------------------------------------|
| 1   | 2026-08-05 | 21fd424    | v1               | 0/40 (0.0%)    | 0           | 0                 | $0.0000 | all cases errored — no API credit |
| 2   | 2026-08-05 | 21fd424    | v1               | 29/40 (72.5%)  | 1           | 10                | $0.1399 | repeat run (same commit) |
| 3   | 2026-08-06 | b3a3329    | v1               | 29/40 (72.5%)  | 1           | 10                | $0.1418 | defect-level observability added |
| 4   | 2026-08-06 | 5c720e6    | v2               | 32/40 (80.0%)  | 2           | 6                 | $0.1350 | dataset v2 (fixed 6 authoring defects) |
| 5   | 2026-08-06 | ca844ca    | v2               | 29/40 (72.5%)  | 1           | 10                | $0.1393 | quality lens coverage expanded |
| 6   | 2026-08-06 | 942f509    | v2               | 29/40 (72.5%)  | 2           | 9                 | $0.1257 | quality lens prompt recalibrated |
| 7   | 2026-08-06 | 942f509    | v2               | 32/40 (80.0%)  | 2           | 6                 | $0.1259 | repeat run (same commit) / variance measurement |
| 8   | 2026-08-06 | 942f509    | v2               | 31/40 (77.5%)  | 2           | 7                 | $0.1295 | repeat run (same commit) / variance measurement |
| 9   | 2026-08-06 | 942f509    | v2               | 31/40 (77.5%)  | 2           | 7                 | $0.1264 | repeat run (same commit) / variance measurement |
| 10  | 2026-08-06 | c125a47    | v2               | 34/40 (85.0%)  | 0           | 6                 | $0.1275 | quality lens reordered (naming check first) |
| 11  | 2026-08-06 | c125a47    | v2               | 32/40 (80.0%)  | 1           | 7                 | $0.1288 | repeat run (same commit) |
| 12  | 2026-08-06 | c125a47    | v2               | 34/40 (85.0%)  | 0           | 6                 | $0.1305 | repeat run (same commit) |
| 13  | 2026-08-06 | bce15e3    | v2               | 31/40 (77.5%)  | 1           | 8                 | $0.1276 | eval-only schema failure diagnostics added |
| 14  | 2026-08-06 | 5d19388    | v2               | 34/40 (85.0%)  | 0           | 6                 | $0.1297 | parser fix (JSON extraction) |
| 15  | 2026-08-06 | 068c48b    | v2               | 33/40 (82.5%)  | 1           | 6                 | $0.1288 | category enum closed (judge template) |
| 16  | 2026-08-06 | fa4d116    | v2               | 31/40 (77.5%)  | 2           | 7                 | $0.1245 | placement experiment (category rule moved after verdict rule) |
| 17  | 2026-08-07 | a7d1185    | v2               | 32/40 (80.0%)  | 2           | 6                 | $0.1234 | BASELINE.md added (no engine/dataset change) |
| 18  | 2026-08-08 | a0dd9db    | v3               | 33/40 (82.5%)  | 2           | 5                 | $0.1196 | first v3 run: dataset v3 (11a5861) + llm_types refactor |
| 19  | 2026-08-09 | 8359246    | v3               | 32/40 (80.0%)  | 2           | 6                 | $0.1242 | dataset v3: quality-01 -> leaderboard decomposition, quality-03 isolated to naming axis |
| 20  | 2026-08-10 | c0515eb    | v3               | 33/40 (82.5%)  | 2           | 5                 | $0.1247 | Phase 2C variance characterization (benchmark safety/analysis skills added; no engine or dataset change) |
| 21  | 2026-08-10 | c0515eb    | v3               | 33/40 (82.5%)  | 2           | 5                 | $0.1183 | repeat run (same commit) / variance measurement |
| 22  | 2026-08-10 | c0515eb    | v3               | 33/40 (82.5%)  | 2           | 5                 | $0.1198 | repeat run (same commit) / variance measurement |
| 23  | 2026-08-10 | c0515eb    | v3               | 32/40 (80.0%)  | 2           | 6                 | $0.1192 | baseline extension (same commit) for Phase 4 registration |
| 24  | 2026-08-10 | c0515eb    | v3               | 33/40 (82.5%)  | 2           | 5                 | $0.1247 | baseline extension (same commit) |
| 25  | 2026-08-10 | c0515eb    | v3               | 34/40 (85.0%)  | 2           | 4                 | $0.1205 | baseline extension (same commit) |
| 26  | 2026-08-10 | c0515eb    | v3               | 32/40 (80.0%)  | 2           | 6                 | $0.1227 | baseline extension (same commit) — EXCLUDED from the Phase 4 baseline arm under registered Amendment A1 (silent mypy gate failure) |
| 27  | 2026-08-10 | c0515eb    | v3               | 32/40 (80.0%)  | 2           | 6                 | $0.1179 | baseline extension (same commit) |
| 28  | 2026-08-10 | c0515eb    | v3               | 34/40 (85.0%)  | 2           | 4                 | $0.1224 | baseline extension (same commit) |
| 29  | 2026-08-10 | be990c7    | v3               | 32/40 (80.0%)  | 2           | 6                 | $0.1426 | Phase 4 intervention arm: judge-prompt calibration appended to RESPONSE_INSTRUCTION (Mechanism B/C) |
| 30  | 2026-08-10 | be990c7    | v3               | 31/40 (77.5%)  | 2           | 7                 | $0.1419 | repeat run (same commit) / Phase 4 arm |
| 31  | 2026-08-10 | be990c7    | v3               | 32/40 (80.0%)  | 2           | 6                 | $0.1424 | repeat run (same commit) / Phase 4 arm |
| 32  | 2026-08-10 | be990c7    | v3               | 34/40 (85.0%)  | 2           | 4                 | $0.1428 | repeat run (same commit) / Phase 4 arm |
| 33  | 2026-08-10 | be990c7    | v3               | 34/40 (85.0%)  | 2           | 4                 | $0.1433 | repeat run (same commit) / Phase 4 arm |
| 34  | 2026-08-10 | be990c7    | v3               | 33/40 (82.5%)  | 2           | 5                 | $0.1437 | repeat run (same commit) / Phase 4 arm |
| 35  | 2026-08-10 | be990c7    | v3               | 32/40 (80.0%)  | 2           | 6                 | $0.1417 | repeat run (same commit) / Phase 4 arm |
| 36  | 2026-08-10 | be990c7    | v3               | 33/40 (82.5%)  | 2           | 5                 | $0.1448 | repeat run (same commit) / Phase 4 arm |
| 37  | 2026-08-11 | 77d36c3    | v3               | 34/40 (85.0%)  | 2           | 4                 | $0.1217 | temperature / encoding defect fixes touching the measured path (`eval/runner.py`, `verification/pipeline.py`) + research-graph exporter — starts a NEW CONFIGURATION CLUSTER |
| 38  | 2026-08-14 | d856d72    | v3               | 31/40 (77.5%)  | 2           | 7                 | $0.1235 | Phase 5A baseline characterization at the then-current configuration |
| 39  | 2026-08-14 | d856d72    | v3               | 32/40 (80.0%)  | 2           | 6                 | $0.1213 | repeat run (same commit) |
| 40  | 2026-08-14 | d856d72    | v3               | 33/40 (82.5%)  | 2           | 5                 | $0.1229 | repeat run (same commit) |
| 41  | 2026-08-14 | d856d72    | v3               | 32/40 (80.0%)  | 2           | 6                 | $0.1223 | repeat run (same commit) — last v3 run |
| 42  | 2026-08-18 | c2ec1e4    | v4               | 36/40 (90.0%)  | 0           | 4                 | $0.1302 | FIRST v4 run. Dataset v4 / benchmark v2 were introduced at `f79353c`, not at this SHA; `c2ec1e4` is the docs-only AgentGate branding rename. Not comparable to v1/v2/v3. |
| 43  | 2026-09-02 | e002b6b    | v4               | **VOID**       | —           | —                 | $0.5133 | **ABORTED — do not score.** First `claude-sonnet-5` judge attempt; killed by a 10-minute harness timeout at 35/40 cases, 108/120 lens calls. `total_cases` stored as 0 because the aggregate update never ran. See Notes. |
| 44  | 2026-09-02 | a600d20    | v4               | 36/40 (90.0%)  | 0           | 4                 | $0.5455 | **FIRST COMPLETED RUN ON THE `claude-sonnet-5` JUDGE** — opens the Sonnet/v4 configuration cluster (n=1, no dispersion estimate). Run 1 of the off-lens blocking registration; measurement only, no engine change. 122 lens calls (2 Phase 9E retries), 3 schema failures. See Notes. |
| 45  | 2026-09-08 | b069b45    | v4               | 8/10 (80.0%) — **10-case slice, NOT /40** | 0 | 2 | $0.2279 | **TARGETED VALIDATION, EXCLUDED FROM EVERY ACCURACY/VARIANCE/STABILITY POOL.** Answer-Budget Phase 2 live validation, Stage 1 (`ANSWER_BUDGET_PHASE2_REGISTRATION.md` §7) — `engine bench --category security`, 10 cases, not the 40-case benchmark. See Notes. |
| 46  | 2026-09-08 | 10e309a    | v4               | 36/40 (90.0%)  | 0           | 4                 | $0.5334 | First full 40-case run under the Answer-Budget Phase 2 configuration (`thinking_disabled` on the judge truncation retry, commit `b069b45`). **Valid Sonnet/v4 production result — 0 schema failures.** See Notes. |

## Dataset v5

**Dataset v5 begins at commit `eea901e` (`eea901ea43d1b213eccff193daceaf75387c1c8b`, "Dataset v5 -- implement and close amendments A-4 and A-5").** It is registered in `docs/benchmark/DATASET_V5_AMENDMENT.md`. **No live baseline measurement exists for v5 as of this entry** — the table above ends at run 46, which ran on v4. Any future v5 `engine bench` run must be appended as a new row with `dataset_version = v5` and recorded as a separate measurement series per the boundary note below; it must never be pooled with, averaged against, or read as a delta from run 46 or any other v4/v3/v2/v1 row.

## Grounded-severity ceiling — Stage 1 (dataset v6, INCOMPLETE)

Registered in `docs/benchmark/GROUNDED_SEVERITY_EXPERIMENT_REGISTRATION.md`. Baseline SHA
`16309b52d51d1774c9f5b1b7c3a6af6eef03199a`; intervention SHA
`fd8f136dd5714dbac66d8700f82d3f7d41b97ae8` (the §3 block appended to
`RESPONSE_INSTRUCTION`, prompt-only, verified byte-identical to the registration).

| run | date | commit sha | dataset_version | accuracy | false_pass | false_unverified | cost | what changed |
|-----|------------|------------|------------------|----------------|-------------|-------------------|---------|------------------------------------------|
| 50  | 2026-09-08 | 16309b5    | v6               | 38/40 (95.0%)  | 0           | 2                 | $0.5073 | Stage 1 baseline arm, run 1/4 |
| 51  | 2026-09-08 | 16309b5    | v6               | 39/40 (97.5%)  | 0           | 1                 | $0.5222 | Stage 1 baseline arm, run 2/4 |
| 52  | 2026-09-08 | 16309b5    | v6               | 38/40 (95.0%)  | **1**       | 1                 | $0.5362 | Stage 1 baseline arm, run 3/4 |
| 53  | 2026-09-08 | 16309b5    | v6               | 38/40 (95.0%)  | 0           | 2                 | $0.5598 | Stage 1 baseline arm, run 4/4 |
| 54  | 2026-09-08 | fd8f136    | v6               | 39/40 (97.5%)  | 0           | 1                 | $0.7307 | Stage 1 intervention arm, run 1/4 |
| 55  | 2026-09-08 | fd8f136    | v6               | 37/40 (92.5%)  | 0           | 3                 | $0.7196 | Stage 1 intervention arm, run 2/4 |
| 56  | 2026-09-08 | fd8f136    | v6               | **VOID**       | —           | —                 | $0.5690 | **Stage 1 intervention arm, run 3/4 — ABORTED.** 11/40 cases errored with `BadRequestError: Your credit balance is too low to access the Anthropic API`, including `edge_case-02-clean`, a primary target. Excluded per registration §8.4 (any run with ≥1 `eval_case_results.error` row is void). |

- **Stage 1 is INCOMPLETE, not INCONCLUSIVE-per-registration.** It stopped because the
  Anthropic account ran out of API credit mid-run-3, not by any pre-registered decision
  rule. Only 2 of the required 4 intervention runs (54, 55) are valid; run 56 is void and
  excluded. The registration's Stage 1 rules (§7.1) require N=4 per arm and were **never
  evaluated** — do not read this entry as a completed Stage 1 result in either direction.
- **Live per-case data recorded, not decided.** `edge_case-02-clean`: OK in 54, UNVERIFIED
  in 55 (1/2). `security-04-clean` blocking (CRITICAL+HIGH) defect count: 4/4/4/4 across the
  baseline arm, 1 in run 54, 2 in run 55 — down from baseline but never zero, consistent
  with the registration's own note that this case's redundant blocking mass needs every
  finding demoted to flip. `security-03-clean`: OK in 54, UNVERIFIED in 55, OK in the
  excluded run 56. Intervention-arm false passes: **0/2**.
- **Baseline anomaly — the registration's own assumed baseline did not hold when
  measured fresh.** The registration's §5 targets cite historical runs 44/46/47/48 as
  `edge_case-02-clean` = **0/4**. This session's freshly-run, concurrently-measured
  baseline arm (50-53, run at the unmodified pre-intervention SHA) measured **3/4** —
  only run 50 failed. This is a single N=4 cluster and does not by itself establish a new
  baseline figure, but it means the 0/4-vs-X/4 framing this experiment was designed around
  does not hold as measured, and should be weighed before any further Stage 1 spend.
- **`security-03-clean`'s one intervention-arm failure (run 55) is not attributable to the
  judge severity ceiling.** Its defect record for that run is a single `automated`/mypy
  finding, not a judge-lens finding — `automated_defects()` (`src/engine/verification/automated.py`)
  hardcodes `severity = "HIGH"` for every failed automated gate, entirely independent of
  `LENSES`/`RESPONSE_INSTRUCTION`. The grounded-severity prompt text cannot reach this path.
  Pinned as a deterministic regression test (`test_security_03_clean_automated_gate_failure_is_untouched_by_the_ceiling`,
  `tests/test_verification.py`) so a future reader does not mistake code-generation variance
  in the coding agent's output for a judge-severity regression.
- **Offline validation performed in lieu of completing Stage 1.** Seven deterministic
  regression tests were added to `tests/test_verification.py`, exercising `verdict.merge`/
  `verdict.gate`/`schema.enforce_critic_schema` directly against critic shapes mirroring the
  real defect patterns above — no network or provider call. They pin: the pre-intervention
  HIGH blocks / post-demotion MEDIUM passes shape for `edge_case-02-clean`; full-demotion
  flips `security-04-clean` while partial demotion (one blocker surviving) still blocks it,
  matching runs 54/55 exactly; a genuinely grounded CRITICAL/HIGH always still blocks
  regardless of the ceiling; the automated-gate/judge-lens separation above; and that a
  model cannot self-report `verdict: OK` around a HIGH/CRITICAL defect it still lists —
  `enforce_critic_schema` computes the expected verdict from severities, not the model's
  claim, so this fails closed rather than becoming a silent false pass. Full offline suite:
  1687 passed, 3 skipped, ruff clean, mypy clean (commit noted below).
- **What this offline work does and does not establish.** It confirms the pre-existing
  merge/gate/schema mechanism behaves correctly under every severity pattern the ceiling
  could produce, and that no production defect exists in the code the ceiling text sits
  inside. It **cannot** verify that a live judge actually performs the demotion the
  instruction asks for — that is exactly the empirical question Stage 1 was designed to
  answer and did not reach N=4 on. **Acceptance of the intervention rests on this
  deterministic regression coverage plus the partial live evidence above (runs 50-55) —
  it is not a completed N=4 experimental validation**, and must not be cited as one.
- **Next step, when credit is restored:** 2 more valid intervention runs at `fd8f136`
  (a replacement for void run 56, plus the still-outstanding run 4) to complete N=4 per
  arm, at which point the registration's §7.1 hard-stop/futility rules can actually be
  applied — informed by the baseline-anomaly note above.
- **FORMAL CLOSURE (2026-09-08) — grounded-severity ceiling is CLOSED as
  INCOMPLETE / INCONCLUSIVE.** Registered in
  `docs/benchmark/STRUCTURED_GROUNDING_REGISTRATION.md` §0. It stopped on insufficient
  API credit, **not** on any pre-registered decision rule; its Stage 1 rules required N=4
  per arm and were never evaluated, so **no ACCEPT, REJECT or registered-INCONCLUSIVE
  verdict was reached and none may be cited.** Runs **#50-53** (baseline, N=4) and
  **#54-55** (intervention, N=2) are preserved as partial evidence of their own SHAs;
  run **#56 remains VOID** and is never scored or averaged. Its §3 prose block is
  superseded at HEAD by the structured-grounding contract, which **starts a new
  configuration cluster in which no run in this table is a valid baseline.**
- **Forensic finding on the two surviving intervention-arm blockers** (offline, read from
  a scratchpad copy of `.engine/state.db`; no run performed). Neither is a genuine
  vulnerability. One family rests on re-resolution, which the task text explicitly
  excludes, and its own defect prose concedes *"this is fine as written ... No fix needed"*
  while still carrying HIGH. The other rests on a library claim that is **empirically
  false on the interpreter in use** (Python 3.14.5): the IPv4-mapped IPv6 form the finding
  names as unblocked is in fact classified private and loopback, so the guard rejects it;
  the same check refutes the 6to4, Teredo, `0.0.0.0/8` and benchmarking-range variants.
  Two claims **verified true and genuinely unblocked** — CGNAT `100.64.0.0/10` and
  deprecated IPv6 site-local `fec0::/10` — **never carried blocking severity in any run**
  and remain visible at MEDIUM in both intervention runs, satisfying the preceding
  registration's §9.1 preservation constraint.
- **Measured mechanism — severity miscalibration is a propagation failure, not a
  reasoning failure.** In one intervention run the judge reached the correct
  not-a-defect conclusion for two findings of the same family and propagated it into
  `severity` for one (MEDIUM) but not the other (HIGH); the same run assigned one
  identical claim MEDIUM under one lens and HIGH under another. The prose ceiling gave
  the grounding test no output slot, so compliance was unobservable and unenforceable.
  This is the failure the structured-grounding contract is built to make machine-checkable.
- **Unregistered exposure finding — false-pass margin is wider than the preceding
  registration estimated.** That registration's §9 G1 analysis (from run 48, n=1) named
  one broken case as resting on a single HIGH. Measured across runs #50-55: **12 of 20
  broken cases rest on exactly one blocking defect in at least one run, and ~7 of those
  carry zero CRITICALs in at least one run.** `quality-04-broken` reached **zero**
  blockers in run 52 — the baseline arm's recorded `false_pass = 1`, which occurred at the
  **baseline** SHA and is therefore not attributable to the intervention. Any future
  mechanism that demotes blocking defects automatically has a correspondingly wider blast
  radius; that is why automatic demotion is forbidden by the new registration's S2.

## Structured grounding — L0 (dataset v6, REJECTED AT L0)

Registered in `docs/benchmark/STRUCTURED_GROUNDING_REGISTRATION.md` §6, committed at
`2cc6e59` **before** this run existed. Intervention SHA
`9d20c33f43cf2b061d1532b8a151a563f3b96e6a` — closed-enum `grounding_status` on every
defect, cross-checked against severity, with three non-empty grounding fields required for
CRITICAL/HIGH (`rubric.py`, `schema.py`, `judge.py` `RESPONSE_INSTRUCTION`).

| run | date | commit sha | dataset_version | accuracy | false_pass | false_unverified | cost | what changed |
|-----|------------|------------|------------------|----------------|-------------|-------------------|---------|------------------------------------------|
| 57  | 2026-09-10 | 9d20c33    | v6               | 38/40 (95.0%)  | **1**       | 1                 | $0.9057 | L0 smoke, N=1, structured-grounding contract |

- **Run 57 is VALID, not VOID.** Integrity gate passed on every check read from a
  scratchpad copy of `.engine/state.db`: **0** `eval_case_results.error` rows, 120/120
  `eval_case_lens_results.call_status = 'ok'`, 120/120 `eval_case_automated_gates.passed = 1`,
  40/40 cases scored. `eval_runs.git_commit_sha` records
  `9d20c33f43cf2b061d1532b8a151a563f3b96e6a` exactly — the run was executed from a detached
  checkout of that SHA against a clean tree, so its attribution is correct by construction.
  The process exited 1 because `cli.py` ends `sys.exit(0 if eval_run.false_pass == 0 else 1)`;
  that is the CLI signalling a false pass, **not** a crash or an incomplete run.
- **DECISION: REJECT, under the pre-registered L0-a / R1 rule** (`false_pass >= 1`, zero
  tolerance). The rule fired on the first live measurement of the intervention.
- **False-pass case: `quality-04-broken`** — `expected_verdict = 'UNVERIFIED'`,
  `actual_verdict = 'OK'`. Its complete defect record for this run is
  `correctness/MEDIUM`, `code-quality/MEDIUM`, `code-quality/LOW`: **zero CRITICAL or HIGH
  defects from any lens.** This is the signature of the adverse risk the registration
  pre-registered at §5 — a blocking finding relocated to MEDIUM rather than suppressed —
  and on a broken case that is a false pass.
- **R1 is absolute and was not waived.** `quality-04-broken` also produced the one false
  pass in the grounded-severity baseline arm (run 52, SHA `16309b5`), so this case is a
  known background risk at more than one configuration. The registration states in advance
  that the mandatory attribution analysis **cannot reverse the REJECT**, and it has not
  been used to. The asymmetry was accepted when the rule was written, precisely so it could
  not be argued away once it fired.
- **Schema failures: 4** — below the L0-b abort threshold of 6, and therefore not an
  independent stop. Attribution, recorded because it bears on any future design: all four
  are `verdict`/`defects` consistency violations raised by the **pre-existing** check at
  `schema.py:99-108` (`security-02-broken × code-quality`, `security-04-broken ×
  code-quality`, both `verdict 'FAIL'` with no blocking defect; `security-04-clean ×
  correctness` and `× security`, both `verdict 'OK'` alongside a blocking defect). **None
  is a novel grounding-specific rejection**, i.e. none is a defect refused for carrying a
  non-`in_contract_reachable` status or an empty grounding field. The new contract's own
  validation surface did not visibly fire in this run.
- **Per-case observations — descriptive only, and they decide nothing.**
  `edge_case-02-clean` returned **OK**; `security-04-clean` returned **UNVERIFIED** with
  **0** blocking defects (both its `correctness` and `security` lenses schema-failed, so no
  defect was persisted for them). **`edge_case-02-clean` passing in this single run is not
  evidence of efficacy.** n=1, no concurrent baseline arm was run, and the registration
  states that L0 may conclude nothing except "do not proceed". No efficacy claim is made or
  may be cited from run 57.
- **No Stage 1 is authorized, and none was run.** Stage 1 (N=4 per arm) and Stage 2 (N=8)
  were never executed. The experiment terminated at L0 on a safety guardrail, so its
  ACCEPT criteria (A1-A7) were never evaluated and no ACCEPT, INCONCLUSIVE-per-registration,
  or futility verdict exists to cite.
- **Run 57 remains in this table permanently, after the rollback.** Per the registration's
  §6.14 rollback rule, only the configuration reverts; the measurement does not. Run 57 is
  the sole live measurement that will ever exist of the structured-grounding configuration
  unless a new experiment is registered, and it is a **negative result recorded with the
  same weight as a positive one**.
- **Cost: $0.905672**, 690,122 ms wall time (~11.5 min), $0.022642 mean per case.
  Against the registration's $0.90 planning estimate for this run, which was flagged there
  as unmeasured. Total spend for the whole experiment was one run — the stop-loss and the
  Stage 1 budget were never approached, which is the L0 design working as intended.
- **Configuration note for whoever reads this next.** Reverting `9d20c33` restores the
  `8dc2528` production state, which is byte-identical under `src/` to `fd8f136` — the
  **prose ceiling**, itself closed INCOMPLETE / INCONCLUSIVE. Rollback therefore does not
  return the engine to a neutral pre-experiment configuration; it returns it to a second
  unvalidated one. That is a statement about the code, not a measurement.

## Registration B — Phase 0 Control Baseline (dataset v6, CONTROL ONLY — NO EFFICACY CLAIM)

Registered in `docs/benchmark/EVIDENCE_CAPTURE_PROMPT_REGISTRATION_B.md` (§8, phase 0) with
`docs/benchmark/EVIDENCE_CAPTURE_PROMPT_REGISTRATION_B_ADDENDUM_01.md` (executable SHA and
frozen pre-run database baseline). Both were committed **before** any run in this section
existed.

**Executable SHA `44ef7a4785d58b4da7fee6fa6d5680f6c93a62dd`**, stamped on all four runs.
The measured-path base is `4158408` (Registration B §1); the two commits are byte-identical
across every measured-path file and every §9 frozen variable (Addendum 01 §2). Re-verified
at `44ef7a4` for this entry: control `judge.py` blob
`2a2a17f16611d4586d122d6e65710f9bd520910f`, control `RESPONSE_INSTRUCTION` sha256
`e5dd7f825008a752c19d4dc77fbec65ed74be9dbfc36c29c2bc9691c9924dd4f` (1439 chars) — both
match §1 exactly. Judge model `claude-sonnet-5`, judge `max_tokens` 1600, adjudicator
version `adjudication/1`. All four runs executed `engine bench --shadow-adjudicate`; shadow
mode is held constant and cannot change a verdict (Addendum 01 §2.1).

| run | date | commit sha | dataset_version | accuracy | false_pass | false_unverified | cost | what changed |
|-----|------------|------------|------------------|----------------|-------------|-------------------|---------|------------------------------------------|
| 58  | 2026-09-11 | 44ef7a4    | v6               | 39/40 (97.5%)  | 0           | 1                 | $0.7652780 | **Phase 0 control arm, run 1/4** — control prompt unchanged; first live run of this configuration cluster and first live shadow-adjudication persistence |
| 59  | 2026-09-11 | 44ef7a4    | v6               | 37/40 (92.5%)  | 0           | 3                 | $0.7313860 | Phase 0 control arm, run 2/4 |
| 60  | 2026-09-11 | 44ef7a4    | v6               | 38/40 (95.0%)  | 0           | 2                 | $0.7844560 | Phase 0 control arm, run 3/4 |
| 61  | 2026-09-12 | 44ef7a4    | v6               | 38/40 (95.0%)  | 0           | 2                 | $0.7415860 | Phase 0 control arm, run 4/4 — completes N=4 |

Dates are the stored `eval_runs.created_at` values; the four runs are one contiguous batch
(23:26, 23:38, 23:49, 00:01), crossing midnight between runs 60 and 61.

- **THIS IS A CONTROL BASELINE ONLY. IT PROVES NO INTERVENTION EFFICACY.** All four runs
  executed the **unchanged control prompt**. The Registration B intervention did not exist
  when these runs executed and is still not implemented. Nothing in this section may be
  cited as evidence that any prompt change helps, hurts, or does anything at all. Its sole
  purpose is to supply the concurrently measured control figures that Registration B §1.2
  and §16.6 require before an intervention run can be interpreted — the configuration
  cluster at this SHA previously held **zero** completed runs, so no row elsewhere in this
  file was a valid baseline for it.
- **All four runs are VALID.** Integrity gate passed on every check, read from a scratchpad
  copy of `.engine/state.db`: **0** `eval_case_results.error` rows in each run (40/40 cases
  scored), **120/120** `eval_case_lens_results.call_status = 'ok'` in each run, **120/120**
  `eval_case_automated_gates.passed = 1` in each run, and every `agent_execution_metrics`
  row `status = 'ok'` (125/124/127/123 judge calls). Each run's `eval_runs.git_commit_sha`
  records `44ef7a4785d58b4da7fee6fa6d5680f6c93a62dd` exactly.
- **Aggregate (secondary metric, never decisive — Registration B §11).** Correct verdicts
  39, 37, 38, 38 → **mean 38.0/40 = 95.0%**, range 37-39, **SD 0.816** at N=4. The SD is
  consistent with the carried-over pooled σ ≈ 0.92 and is itself an N=4 estimate at a new
  configuration, not a replacement for it. **`false_pass` total = 0** across all four runs.
  **`false_unverified` total = 8** (1 + 3 + 2 + 2).
- **Per-case stability partition (N=4): 37 always-pass / 1 always-fail / 2 borderline.**
  Always-fail: `security-04-clean`. Borderline: `edge_case-02-clean` (3/4 OK) and
  `security-02-clean` (1/4 OK). All 8 `false_unverified` are accounted for by these three
  clean cases; no broken case ever failed, and no case failed in any other way. Accuracy
  here is not 40 independent trials — it is 37 deterministic cases plus three unstable ones.
- **Target-case control rates (Registration B §7).** These are the figures an intervention
  arm would be compared against.
  - `edge_case-02-clean` — **3/4 OK** (OK, UNVERIFIED, OK, OK). Numerically equal to the
    3/4 measured in the grounded-severity baseline arm (runs 50-53) at a different SHA;
    recorded as agreement between two independent N=4 clusters, not pooled with it.
  - `security-04-clean` — **0/4 OK** (UNVERIFIED in all four runs). Blocking
    (CRITICAL+HIGH) defect count on the paired broken case `security-04-broken` was
    **4/5/4/4** — the redundant blocking mass §7 describes.
  - `quality-04-broken` — **UNVERIFIED 4/4, with exactly 1 blocking defect in every run.**
    This is the primary drift sentinel and the tightest margin in the set: §12.4 makes a
    fall from ≥1 to 0 an immediate REJECT, and the measured control margin is exactly one
    defect.
  - `security-03-clean` (**negative control**) — **OK 4/4.** Its only defect in any run was
    a single `code-quality`/LOW finding (runs 58, 60, 61; none in run 59), never blocking.
- **Safety-control results (all four runs).** `edge_case-02-broken` blocked 4/4 (2/2/3/2
  blockers); `security-03-broken` blocked 4/4 with **exactly 1 blocker each run**;
  `security-04-broken` blocked 4/4 (4/5/4/4 blockers); `quality-04-broken` blocked 4/4 with
  **exactly 1 blocker each run**. **All 20 broken cases were correctly blocked in all four
  runs, and none reached zero blocking defects in any run.**
- **Sole-blocker census (S5 control reference, §12.5).** **8 of the 20 broken cases rest on
  exactly one blocking defect in at least one of the four runs**: `correctness-01-broken`,
  `correctness-02-broken`, `correctness-04-broken`, `correctness-05-broken`,
  `edge_case-03-broken`, `edge_case-05-broken`, `quality-04-broken`, `security-03-broken`.
  Two of those — `quality-04-broken` and `security-03-broken` — rest on a single blocker in
  **every** run. This is the measured blast radius any demotion mechanism would aim at. It
  is narrower than the 12-of-20 figure measured across runs 50-55, which was taken at a
  different configuration; the two are not pooled and neither supersedes the other.
- **Severity distribution reference (S3 control reference, §12.3).** Total defects per run
  80 / 79 / 98 / 79 (mean 84.0). Pooled across runs 58-61 (336 defects): by severity
  **CRITICAL 48, HIGH 150, MEDIUM 69, LOW 69** — 198 blocking (58.9%); by lens
  **correctness 146, security 104, code-quality 86**. Per-run, per-lens:

  | run | correctness C/H/M/L | security C/H/M/L | code-quality C/H/M/L | total |
  |-----|---------------------|------------------|----------------------|-------|
  | 58  | 7 / 16 / 8 / 4      | 3 / 10 / 4 / 4   | 1 / 9 / 3 / 11       | 80    |
  | 59  | 7 / 19 / 9 / 3      | 5 / 14 / 4 / 1   | 0 / 7 / 2 / 8        | 79    |
  | 60  | 7 / 17 / 9 / 6      | 4 / 18 / 6 / 5   | 2 / 8 / 5 / 11       | 98    |
  | 61  | 9 / 14 / 9 / 2      | 3 / 13 / 7 / 3   | 0 / 5 / 3 / 11       | 79    |

  This is the control-arm reference against which §12.3 and §12.6 would be evaluated. It is
  a distribution, not a result.
- **Schema failures: 6 total — 2, 2, 1, 1 per run.** **The §12.2 abort threshold is 6 _per
  run_, not per phase**; the maximum in any single run here is 2, so the threshold did not
  fire and no run came close to it. The numerical coincidence between the phase total and
  the threshold value is a coincidence and must not be read as a near-miss. Per the standard
  rule, schema failures are recorded, not disqualifying. All six are the **same class** —
  `verdict: is 'OK' but expected 'FAIL' given the defects`, the pre-existing
  verdict/severity consistency check, **not** a novel evidence-field rejection — and all six
  land on just two clean security cases: `security-04-clean` (run 58 × correctness, run 58 ×
  security, run 59 × security) and `security-02-clean` (run 59 × correctness, run 60 ×
  security, run 61 × correctness). This is the pre-intervention attribution baseline §12.2
  requires; a future failure of a different class is therefore attributable.
- **Shadow adjudication — persistence confirmed live, outcome uniformly inert.** **336
  sidecar rows** in `eval_case_defect_adjudications` (80 / 79 / 98 / 79), exactly one per
  defect, all `adjudicator_version = 'adjudication/1'`. The table held **0 rows** before this
  phase (Addendum 01 §3.1), so this is the first live evidence the shadow path persists at
  all. Distribution:
  - **198 rows** — every CRITICAL/HIGH defect (48 CRITICAL + 150 HIGH) — carry
    `rule = 'fail-closed-unresolved'`, `admissible_to_block = 1`, reason "no deterministic
    contradiction established". **198/198 blocking defects fail-closed-unresolved.**
  - **138 rows** — every MEDIUM/LOW defect — carry `rule = 'not-applicable'`,
    `admissible_to_block = NULL`.
  - **0 suppressions.** No row in any run carries `admissible_to_block = 0`. The shadow
    layer demoted nothing, and its 198 blocking rows reconcile exactly with the 198
    CRITICAL/HIGH rows in `eval_case_defects` for these runs.
  - All five adjudication premises resolved `UNRESOLVED` in all 336 rows —
    `violation_present_in_submitted_code`, `trigger_in_contract`,
    `premise_excluded_by_guarantee` and `premise_depends_on_runtime_behaviour` each via rule
    `no-evidence`; `self_contradiction` via rule `retraction`.
- **Evidence availability = 0%, exactly as Registration B §8 predicted.** All five evidence
  fields (`grounded_in_clause`, `grounding_route`, `minimal_trigger`, `runtime_probe`,
  `excluded_by_clause`) are **null in every one of the 336 rows**, and 0 rows carry any probe
  data. The control arm therefore measures **E1 = 0%**, **E2 = 0% (0 of 198 blocking defects
  resolved)**, **E3 = all routes NULL**. This is the floor the experiment exists to move, and
  it is now measured rather than assumed. **The 40% futility floor applies to the
  _intervention_ arm (§11), not to control** — a 0% control E2 is the expected and registered
  starting condition, not a futility trigger.
- **No STOP rule fired.** §12.1 `false_pass` = 0 in all four runs. §12.2 max 2 schema
  failures per run against a threshold of 6. §12.4 `quality-04-broken` held ≥1 blocker in
  every run. §12.5 no broken case lost its blocking mass. §12.6 no suppression. §12.7 spend
  $3.022706 against a $30.00 cumulative stop-loss. §12.3, §12.4's drift clause and §12.6 are
  *comparative* rules requiring an intervention arm and are **not evaluable from control
  alone** — this section records their control-side reference values only.
- **Cost.** $0.7652780 + $0.7313860 + $0.7844560 + $0.7415860 = **$3.022706** for Phase 0,
  against a §15 estimate of ~$2.92 (an estimate, not a ceiling) and the $30.00 cumulative
  hard stop-loss. Cumulative Registration B spend to date: **$3.022706**. Mean latency
  15.5-16.5 s per case.
- **Provenance of these runs.** Executed from a **detached worktree at exactly `44ef7a4`**
  (`C:/Users/PC/Desktop/engine-phase0-44ef7a4`, detached HEAD, clean tree). Executed code and
  stamped SHA both verified as `44ef7a4`: `git diff 44ef7a4 -- src/ tests/` in that worktree
  returns empty, and `eval_runs.git_commit_sha` records the same SHA for all four runs — so
  the `get_git_commit_sha()` HEAD-not-working-tree hazard is closed by construction rather
  than by assumption. `PYTHONPATH` and `ENGINE_DB_PATH` pins were used so the worktree
  executed its own source while appending to the single production database (the worktree
  holds no `state.db` of its own). **The main repository was not touched** — no checkout, no
  branch change, tree clean at `2ddf31b` throughout. An initial credentialless launch
  preceded these runs and **produced no run, no API call, no database write and no spend; it
  is not an experiment result** and is recorded here only so the attempt is not later
  mistaken for a missing or void run.
- **Post-Phase-0 database state.** `.engine/state.db` sha256
  `102f5bb4949523f9b5378eed79ce262d1567abd90c5ed72a83a764ba81ee77de`, size **4780032**,
  `PRAGMA integrity_check` = `ok`, **no `-wal`, no `-shm`**. `eval_runs` = **61** rows (ids
  contiguous through 61), `eval_case_defect_adjudications` = **336** rows. The change from
  Addendum 01 §3's frozen pre-run baseline
  (`665773a9d626d04ac7eb4792ebd4af0a0d5b2617461a877f08501adf8a07fba9`, size 4198400, 57
  `eval_runs`, 0 adjudications) is **fully explained by the four recorded `engine bench`
  runs** and is purely additive; no prior row was altered. **This hash supersedes the
  Addendum 01 figure as the reference pre-run state for the next run under Registration B** —
  any future divergence not explained by a recorded run is an integrity incident.
- **What Phase 0 establishes, and what it does not.** It establishes: a measured control
  baseline at a configuration cluster that previously had none; that shadow adjudication
  persists correctly under live conditions; and that the evidence-availability floor is
  genuinely 0%, not merely assumed to be. It establishes **nothing** about the proposed
  prompt intervention, which has not been written. Per Registration B §14 these figures are
  now frozen as the control arm and may not be re-sliced, extended (there is no "run a few
  more" option under this registration), or reinterpreted once intervention data exists.
- **Next step under Registration B §16.** §16.6 — Phase 0's measured control figures
  recorded in BASELINE.md before any intervention run — is satisfied by this entry. Still
  outstanding before Phase 1 may run: **§16.4**, the intervention implemented in its **own
  separate commit** touching only `RESPONSE_INSTRUCTION` in `judge.py` (a measured-path file,
  requiring its own explicit approval, and starting a new configuration cluster); and
  **§16.5**, the intervention SHA and its new `RESPONSE_INSTRUCTION` sha256 recorded in
  **Addendum 02**. Phase 1 then requires its own per-turn approval and a passing `git-safety`
  pre-run gate. Analysis of Phase 0 authorises none of this.

## Registration B — Phase 1 L0 (dataset v6, REJECTED AT L0)

Registered in `docs/benchmark/EVIDENCE_CAPTURE_PROMPT_REGISTRATION_B.md` §8 (Phase 1),
`docs/benchmark/EVIDENCE_CAPTURE_PROMPT_REGISTRATION_B_ADDENDUM_02.md` (intervention
provenance), both committed **before** this run existed. Intervention commit
`cff6196df64fa7b7ece003e729b7eaac484f0d50` (parent `d7d3c4aeb697acdb3d3d5d1cdb329c3b58b81099`,
recorded at `90bef072d62e2f95596a0ce6b50c2a0a12ee2482` after the docs-only Addendum 02 commit),
intervention `RESPONSE_INSTRUCTION` sha256
`46798d4a1ec790360c78e3af940c4a3ed8cc92f340f7fc98af3e80e8dc4cb1af` (2452 chars, control was
1439). **Executed exactly once, as registered (N=1, L0 smoke, safety gate only).**

| run | date | commit sha | dataset_version | accuracy | false_pass | false_unverified | cost | what changed |
|-----|------------|------------|------------------|----------------|-------------|-------------------|---------|------------------------------------------|
| 62  | 2026-09-12 | 90bef07    | v6               | 37/40 (92.5%)  | **1**       | 2                 | $0.782874 | **Phase 1 L0 smoke, N=1** — Registration B optional evidence-capture intervention (`grounded_in_clause`, `minimal_trigger`, `grounding_route`) added to `RESPONSE_INSTRUCTION`, before the grounded-severity ceiling |

- **Run 62 is VALID, not VOID.** Verified from a scratchpad copy of `.engine/state.db`:
  **0** `eval_case_results.error` rows, 40/40 cases scored, `eval_runs.git_commit_sha` records
  `90bef072d62e2f95596a0ce6b50c2a0a12ee2482` exactly, matching the tree the run executed
  against. `PRAGMA integrity_check = ok` before and after the run.
- **DECISION: REJECT / CLOSED, under three independent absolute rules, each sufficient on
  its own:**
  - **§12.1** — `false_pass >= 1`, zero tolerance, no per-case exception.
  - **§12.4** — `quality-04-broken`'s blocking (CRITICAL/HIGH) defect count fell from
    exactly 1 in **every one of Phase 0's four control runs** to **0** in this run.
  - **§12.5** — sole-blocker loss: `quality-04-broken` rested on a single blocking defect
    in every control run and lost that defect's blocking severity here.
  Per the registration, this decision is evaluated **before** any efficacy metric and
  **cannot be reversed by the attribution analysis that follows** — that asymmetry was
  accepted in advance, in writing, precisely so it could not be argued away once a rule
  fired. **Registration B is REJECTED and CLOSED. No further live run under this
  registration is authorized; none has been run.**
- **False-pass case and exact mechanism: `quality-04-broken`.** `expected_verdict =
  'UNVERIFIED'`, `actual_verdict = 'OK'`. Its complete record this run: `correctness/MEDIUM`,
  `security/LOW` (self-labelled CODE-QUALITY), `code-quality/MEDIUM`, `code-quality/LOW` —
  **zero CRITICAL or HIGH defects from any lens.** The Phase 0 control baseline recorded
  exactly one blocking defect (HIGH, from the `correctness` lens) on this case in **all
  four** control runs (58-61). In this run that same finding is present but reported as
  `correctness/MEDIUM` — **the identical HIGH -> MEDIUM demotion mechanism this
  registration was designed to guard against**, and the same signature already seen on
  this case in run 57 (structured grounding, `9d20c33`, zero CRITICAL/HIGH from any lens)
  and run 52 (grounded-severity baseline arm). `quality-04-broken` false-passing is now a
  recorded background risk across **three independent configurations** (52, 57, 62).
- **Correction (2026-09-12): the lens attribution two bullets above was wrong.** That
  paragraph states the lost blocker came from the `correctness` lens. Re-querying
  `eval_case_defects` for runs 58-62 directly establishes this is incorrect: in **all four**
  Phase 0 control runs (58-61), the sole blocking HIGH on `quality-04-broken` was reported by
  the **`code-quality`** lens (fix text pattern: "Define a module-level constant... per the
  explicit task requirement"), while `correctness` and `security` reported the same
  underlying finding redundantly at MEDIUM/LOW in those same runs — never HIGH. In run 62,
  it is the **`code-quality`** lens's finding that demotes from HIGH to MEDIUM;
  `correctness`'s finding was already MEDIUM in every control run and stays MEDIUM here. The
  error was citing the wrong lens name when this entry was first written. **Corrected
  attribution: `code-quality`, not `correctness`.** This does not change any numerical
  result, the `false_pass` count, any §12 STOP-rule determination, or the REJECTED/CLOSED
  conclusion — all of those are lens-independent and were and remain correct as recorded.
- **The false pass came from judge severity movement, not from shadow admissibility.**
  `verdict.gate()` reads `d["severity"]` directly and is unmodified; nothing in
  `admissibility.py` was invoked authoritatively (`--shadow-adjudicate` only,
  `adjudicate=True` was never set). Confirmed from the sidecar table:
  `eval_case_defect_adjudications.admissible_to_block` is **`False` in zero of 77 rows**
  this run — the shadow layer suppressed nothing. The defect that sank this case was never
  blocking in the first place (`MEDIUM`), so the admissibility layer never evaluated it
  (`rule = 'not-applicable'` for every non-blocking row). Behavioral admissibility was
  never enabled at any point in this registration.
- **Evidence availability, measured but moot.** **E1 = 59/77 = 76.6%** (at least one of the
  three optional fields present) — a sharp rise from Phase 0's measured 0%. Field coverage:
  `grounded_in_clause` 51/77, `minimal_trigger` 40/77, `grounding_route` 59/77. **E2
  (blocking defects resolved to a non-`fail-closed-unresolved` rule) = 1/48 = 2.1%** —
  **below the registered 40% futility floor** (§11). Shadow rule distribution across all 77
  rows: `fail-closed-unresolved` 47, `not-applicable` 29, `stated-purpose-protected` 1;
  `admissible_to_block` True 48 / False 0 / not-applicable 29. Per §12's ordering, the E2
  futility result is recorded for completeness only — the run was already REJECTed on
  safety grounds before E2 was relevant, and this figure supports no efficacy or futility
  conclusion by itself at N=1.
- **Schema failures: 1** (`correctness` lens, `verdict: is 'OK' but expected 'FAIL' given
  the defects`) — the same pre-existing verdict/severity consistency class recorded in
  Phase 0 (6 total there), not a novel evidence-field rejection. Far below the abort
  threshold of 6.
- **Target-case outcomes — descriptive only, decide nothing, and are not an efficacy
  claim.** `edge_case-02-clean` **remained UNVERIFIED** (1 HIGH blocker). `security-04-clean`
  **remained UNVERIFIED** (2 blocking defects of 5). Neither target case improved, was
  fixed, or changed status relative to its Phase 0 majority outcome. At N=1 with no
  concurrent control arm in this run, no efficacy or improvement claim may be made or cited
  from run 62, per Registration B §14.
- **Safety-control cases other than `quality-04-broken` held.** `edge_case-02-broken`
  blocked (3 blocking defects: 2 CRITICAL, 1 HIGH). `security-03-broken` blocked **with its
  sole control-arm blocker intact** (1 HIGH — the same case Phase 0 identified as resting on
  a single blocker in every control run). `security-04-broken` blocked (3 blocking defects:
  2 CRITICAL, 1 HIGH — down from control's 4/5/4/4 but still safely above zero). No broken
  case other than `quality-04-broken` lost its blocking authority.
- **No Stage 1 is authorized, and none was run.** Stage 1 (N=4/arm) and Stage 2 (N=8/arm)
  were never executed. The experiment terminated at L0 on a safety guardrail; ACCEPT
  criteria A1-A7 were never evaluated and no ACCEPT, INCONCLUSIVE, or futility verdict may
  be cited — the recorded outcome is REJECT, full stop.
- **Cost: $0.782874**, 584,078 ms wall time (~9.7 min), $0.019572 mean per case. Cumulative
  Registration B spend to date: Phase 0 ($3.022706) + this run = **$3.805580**, against the
  $30.00 cumulative stop-loss (not approached).
- **Post-run database state.** sha256
  `587ecb1f325ed0ed9a0917f7d932d6c95c8c01ab145ffe444e00a1c6ff0987ec`, size **4927488**,
  `PRAGMA integrity_check = ok`, no `-wal`/`-shm`. `eval_runs` = **62** rows (61 -> 62,
  contiguous), `eval_case_defect_adjudications` = **413** rows (336 -> 413, +77, exactly
  this run's defect count — purely additive, no prior row altered). Production DB was not
  otherwise touched.
- **Configuration note for whoever reads this next.** Unlike the structured-grounding
  rollback (which landed on an unvalidated ceiling), reverting the Registration B
  intervention restores `RESPONSE_INSTRUCTION` to the exact control text already measured
  across Phase 0's four valid runs (58-61) — a **previously validated** configuration, not
  an unknown one. **The next code action under this registration, if separately
  authorized, is that revert** — restoring the control `RESPONSE_INSTRUCTION` in
  `src/engine/verification/judge.py` — while preserving every historical run record,
  addendum, and this entry unchanged. That action has not been taken in this turn.

## security-04-clean — v6 dataset/spec limitation (adjudicated, closed, not a verifier target)

Continues the tracking opened by the dataset v4/v5 boundary note above, which named
`edge_case-02-clean` and `security-04-clean` as the two of run 46's four `false_unverified`
cases left "reserved for later verifier work." This entry closes that reservation for
`security-04-clean` with a full offline forensic adjudication (no benchmark run, no
provider call, no dataset change) and records the outcome as a **dataset/spec limitation**,
not an open verifier target.

- **`security-04-clean` is 0/16 across every recorded v6 run (48-63).** It has never once
  returned `OK` at this dataset version. Of the 16 failures, 7 (runs 54, 56, 57, 58, 59, 62,
  63) carry a schema failure — 3 of those (57, 58, 63) with **zero** blocking defects at
  all — so at most 9 of the 16 could ever be reached by any admissibility mechanism; a
  schema failure dominates `verdict.gate` regardless of what any defect-level mechanism
  concludes.
- **Under the fixture author's own narrow reading of the byte-exact v6 task text, the clean
  implementation satisfies every explicit requirement.** The task states no RFC, no address
  standard, and no enumerated class list; `_is_public()` checks exactly
  `is_private`/`is_loopback`/`is_link_local`/`is_reserved`/`is_multicast`/`is_unspecified`,
  and `resolve_safe_fetch_target()` provably returns only an address drawn from the same
  list it just exhaustively validated (the data-flow property verified structurally in the
  prior forensic-design turn). Verified directly on CPython 3.14.5, the interpreter this
  project runs: of every address class raised historically as a gap — IPv4-mapped loopback,
  IPv4-mapped RFC1918, IPv4-mapped link-local/metadata, NAT64, 6to4, Teredo, documentation
  nets, `0.0.0.0/8`, benchmark ranges — **all are blocked** by the checked properties on this
  interpreter. Only **CGNAT (`100.64.0.0/10`)** passes through unblocked, since Python's
  `is_private` explicitly excludes it and the task names no broader standard
  (`is_global`, "non-globally-routable") that would require it.
- **Measured classification of the historical HIGH/CRITICAL record (36 defects, v6 runs
  48-63, direct DB query, not sampling):** 23/36 raise a DNS-rebinding/re-resolution claim
  the task's own explicit guarantee excludes ("the caller connects to the address you
  return and does not look the host up again"); 21/36 assert the returned address "wasn't
  validated," which is data-flow-disproved; 17/36 assert an IPv4-mapped/NAT64/6to4/Teredo
  classification gap that is factually wrong on this interpreter; 17/36 raise
  out-of-contract `getaddrinfo` selection/ordering concerns (family, socktype, determinism
  — the task states no such requirement); 9/36 raise special-range coverage, of which only
  the CGNAT component is factually live. **0 of 36 raise only one of these categories** —
  every HIGH/CRITICAL finding on this case is a bundle of at least one disproved or
  out-of-contract claim alongside, at most, the one live CGNAT question.
- **Offline text-attribution measurement (temporary scratch classifier, not committed):**
  of 99 total `security-04-clean` defect records (v6, runs 48-63), 36 HIGH/CRITICAL, exactly
  15 matched the narrow "returned address wasn't validated" text pattern, and **15 of 15
  were excluded** for containing a bundled secondary concern (IPv4-mapped/CGNAT/pivot
  language such as "however"/"more importantly"/"the real issue is"). **Zero safe text
  candidates remained**, and this held before any AST/data-flow proof was even attempted.
  The same filter produced **zero** condition-A hits across all 980 v6 broken-case defect
  records — the structural language this case's dispute turns on does not occur anywhere
  else in the dataset.
- **The full AST/data-flow checker proposed to prove the "returned value" claim false was
  designed and rejected without being built**, on this measured evidence: estimated maximum
  historical suppression yield = 0, confirmed by direct measurement rather than assumed.
  Building the checker (a genuinely new, non-trivial code-fact category, not a reuse of
  existing `adjudication.py`/`admissibility.py` machinery) would have had nothing to act on.
  No verifier-side mechanism — the evidence-mining prompt-neutral miner, the
  `excluded_by_clause` guarantee route, or a bespoke data-flow checker — has safe material
  yield on this case, for three independent reasons: the 9-of-16 schema-failure ceiling, the
  universal bundling of the false claim with a genuine, unaddressed CGNAT-adjacent concern,
  and the fact that every guarantee-adjacent claim paraphrases rather than quotes the task's
  guarantee clause (so the existing verbatim-match `_adjudicate_guarantee` route cannot
  reach it either).
- **This is a spec-precision defect, not a verifier defect.** The task text says
  "internal/private" without stating whether the coverage standard is Python's own
  `is_private`-family properties (which the clean fixture, as the reference answer,
  evidently assumes) or a broader "non-globally-routable"/`is_global` standard (which a
  live judge reliably imports from general SSRF-hardening knowledge). Both readings are
  defensible from the text alone; the task does not disambiguate them. **It is not safe to
  close this gap with a broad verifier-side suppression rule** — a rule wide enough to
  clear the historical `special_range_coverage` bundle would suppress the one factually
  correct residual finding (CGNAT) along with the disproved ones.
- **Deferred to a future dataset revision (v7), not undertaken now:** (1) clarify the task's
  coverage standard with one added clause, and (2) close the CGNAT gap in the clean fixture
  (an explicit `100.64.0.0/10` check, or `ip.is_global`). Recommended as one bundled change
  if and when v7 is opened for independent reasons — **not** as sufficient reason to open v7
  on its own, per the `git-safety`/`baseline-evidence` cost of a dataset-version boundary
  (every one of the 63 recorded runs would stop being comparable across it).
- **Dataset v6 is not changed by this entry.** No file under `src/engine/eval/dataset.py`
  was touched, no new dataset version was opened, and every recorded v6 run (48-63) remains
  valid, unchanged, and exactly as previously recorded in this file.
- **`security-04-broken` is unaffected by any reading of this dispute.** `return
  socket.gethostbyname(host)` performs no classification at all — under the narrowest
  possible interpretation of "internal/private" it still lets `127.0.0.1`, `10.0.0.1`, and
  `169.254.169.254` straight through, and never returns `None` for an unsafe host. Its
  blocking status does not depend on where the CGNAT/coverage-standard line is drawn.
  `security-03-broken`, `quality-04-broken`, and `edge_case-02-broken` are structurally
  unrelated (no address classification involved) and untouched by this entry.

## edge_case-02-clean — Combined Contract Evidence Mining, targeted authoritative validation (Run 66, live-validated)

Closes the live-validation pre-registration opened in
`docs/benchmark/COMBINED_CONTRACT_EVIDENCE_MINING_SHADOW_REGISTRATION_ADDENDUM_03.md` §3,
governed by that addendum's frozen SUCCESS/REJECT/INCONCLUSIVE criteria (§3.4-§3.6) and
execution policy (§3.3). Nothing here reopens or edits the base registration
(`COMBINED_CONTRACT_EVIDENCE_MINING_SHADOW_REGISTRATION.md`) or either earlier addendum.

**Run 66.**

| run | date | commit sha | dataset_version | scope | provider/model | accuracy | false_pass | false_unverified | schema failures | cost |
|---|---|---|---|---|---|---|---|---|---|---|
| 66 | 2026-09-13 | 5524f1c | v6 | **`--case-id`-targeted, 5 cases — NOT the 40-case benchmark; excluded from every accuracy/variance/stability pool** | anthropic / claude-sonnet-5 | 5/5 (100%, non-comparable denominator) | 0 | 0 | 0 | $0.096960 |

Integrity, read from a scratchpad copy of `.engine/state.db` (never the live file): 0
`eval_case_results.error` rows, 15/15 `eval_case_lens_results.call_status = ok` (5 cases x 3
lenses), 15/15 `eval_case_automated_gates.passed = 1`, 0 `eval_case_schema_failures` rows.
`runs` row 75 (`eval:engine-review-benchmark`) shows `status = 'passed'`, `attempts = 5`,
`finished_at` set — **the process completed and committed normally; it did not crash
mid-run.** Per-case cost (security-03-broken \$0.015692, security-04-broken \$0.037372,
quality-04-broken \$0.016980, edge_case-02-broken \$0.010588, edge_case-02-clean
\$0.016328) sums exactly to \$0.096960.

**Target — `edge_case-02-clean`.** A live HIGH `correctness` defect was recorded
(`eval_case_defects`, `eval_case_result_id` 2500, `defect_id` C1): location
`solution.py:2 - user.get("profile")`, fix text describing "a non-dict `user` (e.g., None)
currently causes an AttributeError" — the same claim family recorded in prior historical
runs of this case. Final `actual_verdict` = **OK** (matches `expected_verdict`). This
defect and this verdict are read directly from `.engine/state.db` — measured, not
reconstructed.

**Controls — all four retained their blocker, unsuppressed** (`eval_case_results`, run 66,
read directly from the DB): `edge_case-02-broken` UNVERIFIED, `quality-04-broken`
UNVERIFIED, `security-03-broken` UNVERIFIED, `security-04-broken` UNVERIFIED — every one
matching its `expected_verdict`. `false_pass = 0` run-wide.

**Forensic disclosure — how the admissibility decision was established.**
`eval_case_defect_adjudications` (the sidecar table carrying `admissible_to_block`/`rule`/
`reason`) has **zero rows for run 66**, and this is not incidental to this run:
`pipeline.run_verification`'s `if adjudicate: ... elif shadow_adjudicate: ...` branch
(`src/engine/verification/pipeline.py:119-129`) only ever builds the `shadow_adjudications`
list — the thing `db.record_defect_adjudications` writes — inside the `shadow_adjudicate`
arm. Run 66 used `--adjudicate` (authoritative), not `--shadow-adjudicate`, so this table
structurally receives no rows from it regardless of outcome; `merged["defects"]` was
annotated in-process instead, and that annotation is not among the fixed columns
`record_eval_case_defects` writes to `eval_case_defects`. The pre-registration's own §3.8
anticipated exactly this: these two fields exist only on the in-process result / printed
report for that invocation's lifetime, and once the process exits they are "not recoverable
from `.engine/state.db` alone." That live-output capture was not preserved for run 66.

**What was done instead, this turn: independent deterministic reconstruction, verified,
not merely asserted.** Using only durable, unmodified inputs — the defect's `location`/
`fix` text as persisted in `eval_case_defects` (above), the `edge_case-02-clean`
clean-fixture source from `src/engine/eval/dataset.py` (byte-identical at HEAD, which this
turn verified clean and equal to run 66's stamped SHA `5524f1c` before touching anything),
and the real, unmodified `engine.verification.evidence_mining` /
`engine.verification.admissibility` functions at that same commit — this turn recomputed
the mining and adjudication steps directly, in a throwaway scratch script (no provider
call, no benchmark run, no DB write):
- `_with_mined_evidence` on the C1 defect mines `minimal_trigger = "user=None"` via Route A
  (`mine_trigger_evidence`; the function's own `user: dict` annotation contradicts a `None`
  witness). Route B (`mine_return_value_evidence`) returns no evidence on the same defect
  text — no dual match.
- `admissibility.decide` on the mined defect returns `admissible=False`,
  `rule="declared-interface"`, `reason="user is annotated ['dict'], witness is NoneType"`.
- The same two mining functions were run against all 16 defects recorded on the four
  controls (their real `location`/`fix` text and real broken-fixture code): **zero Route
  A/B hits on any control** — evidence was never mined, so admissibility was never even in
  scope for any control defect.

These values agree exactly with the values reported in the original request for this
entry. This is **post-run deterministic reconstruction, independently reproduced and
verified this turn — not a direct persisted/live capture.** It is the strongest available
substitute for the missing live capture, not a claim of equivalence to it: a future
invocation of this pre-registration must still capture `admissible_to_block`/`rule`/
`reason` from that invocation's own immediate output before the process exits, per §3.8,
rather than relying on after-the-fact recomputation.

**Classification: SUCCESS**, per `ADDENDUM_03` §3.4 — all six criteria hold: (1) a live
HIGH defect with a mined `minimal_trigger` on the target, (2) `admissible_to_block =
False`, (3) rule/reason from the existing, unmodified `declared-interface` path (no new
rule name, no new reasoning path), (4) target's final verdict = OK, (5) all four controls
retained a legitimate blocker, (6) `false_pass = 0`. No §3.5 REJECT condition was
observed — specifically verified this turn for the dual-match and control-suppression
conditions, not merely assumed absent.

**Licensed claim (§3.7, quoted verbatim):**
> "Authoritative contract-evidence adjudication was live-validated for a real Route A/B
> false blocker with no observed control suppression."

**Claim limits — binding, not relaxed by this entry:**
- `edge_case-02-clean` is **not** fully fixed. Known historical false-blocker families are
  covered by Route A/B; no claim is made that every possible future judge phrasing is
  covered.
- **Post-result clarification (superseding this entry's own earlier "Run 56 remains
  unexplained by either route" wording, which read as though a real defect resisted
  explanation):** row-level durable evidence — `eval_case_results` id 2169,
  `eval_case_lens_results`, `eval_case_defects`, `eval_case_automated_gates`,
  `eval_case_schema_failures`, `eval_case_defect_adjudications`, all queried from a
  scratchpad copy of `.engine/state.db` — shows **Run 56 is a VOID credit-exhaustion
  artifact: the `correctness` lens failed with an Anthropic `BadRequestError` (credit
  balance too low) before producing any judge output, `security`/`code-quality` never ran,
  and zero defect/gate/schema/adjudication rows exist for this case in this run. No defect
  text ever existed to classify, so Route A/B replay does not apply. It is not evidence of
  an unresolved verifier failure**, and this experiment does not need to explain it as one.
  (`docs/benchmark/COMBINED_CONTRACT_EVIDENCE_MINING_SHADOW_REGISTRATION_ADDENDUM_03.md`
  §3.7's original "Run 56 remains unexplained by either route" wording was written before
  this row-level audit and is left unedited there as historical pre-registration text —
  this bullet is the post-result clarification that supersedes it for current-status
  purposes.)
- No claim is made about authoritative adjudication for any case beyond this named target
  and its four controls, and no claim of general rollout safety is made.
- `security-04-clean` is untouched and out of scope; nothing here bears on it.

**Execution decision.** Per `ADDENDUM_03` §3.3, N=4 was a ceiling, not a mandatory count,
and the policy requires stopping immediately on the first SUCCESS. Run 66 satisfied SUCCESS
on invocation 1. **Live Runs 2-4 were therefore not executed and are not needed.** This
targeted `edge_case-02-clean` live-validation experiment is now frozen; re-opening it
requires a new, separate pre-registration.

### Verifier target status (the four cases named in the v4/v5 boundary note, above)

| case | status |
|---|---|
| `correctness-02-clean` | **Fixed** — dataset v5, amendment A-4 (float-subtraction boundary repair) |
| `security-02-clean` | **Fixed** — dataset v5, amendment A-5 (converter argument-injection repair) |
| `edge_case-02-clean` | **LIVE-VALIDATED FOR KNOWN ROUTE A/B FALSE-BLOCKER SUPPRESSION.** Known historical false-blocker families are covered by Route A/B; Run 56 is excluded as a VOID provider-credit artifact, not an unresolved verifier failure (see the post-result clarification in the section above). Supersedes both the earlier "shadow prototype, non-authoritative" status and this entry's own earlier "Run 56 remains unexplained" wording. Run 66 live-validated authoritative suppression of a real Route A false blocker (`declared-interface`) with zero observed control suppression, per `ADDENDUM_03`'s pre-registered criteria. Not a claim of general rollout safety, not a claim that `security-04-clean` is resolved, and not a claim that every possible future judge phrasing is covered. |
| `security-04-clean` | **Reclassified, this entry.** Not a verifier defect — a v6 dataset/spec-precision limitation. Deferred to a future dataset revision (v7); no verifier-side fix is safe to pursue at v6. |

## Run 67 — final closure validation for the four original historical clean cases

**Run 67.** `--case-id`-targeted, 4 cases — **NOT the 40-case benchmark; excluded from
every accuracy/variance/stability pool, exactly like Run 45 and Run 66.** Stamped SHA
`7b59c9eabba72df060ddd888eb156dcb20b14614`, anthropic/claude-sonnet-5, dataset v6.
`total_cases=4`, `correct_verdicts=3` (3/4), `false_pass=0`, `false_unverified=1`, cost
`$0.140214`. Read directly from `.engine/state.db` (`eval_runs` id 67). 1 schema failure
(`security-04-clean` × `correctness`, a verdict-consistency failure — an already-documented
class for this case — not incorrectly rescued). 12/12 lens calls `ok`, 12/12 automated
gates passed, 0 error rows. **Closure validation: PASS** — no hard-failure condition
(false_pass, a genuine regression on the two fixed cases, a Route A/B false blocker
remaining blocking, a suppressed legitimate defect, a genuinely new `security-04-clean`
defect, or an incorrectly-rescued schema/gate failure) was observed.

**1. `correctness-02-clean`** — expected OK, actual **OK**. No HIGH/CRITICAL defects (one
LOW code-quality note only). **CLOSED / FIXED** — dataset v5 amendment A-4.

**2. `security-02-clean`** — expected OK, actual **OK**. Zero defects recorded at all.
**CLOSED / FIXED** — dataset/spec amendments v5/v6.

**3. `edge_case-02-clean`** — expected OK, actual **OK**. No HIGH/CRITICAL defects this
run — two LOW findings only, so Route A/B authoritative suppression was **not exercised**
in Run 67 (the mechanism had nothing to act on). Run 66 remains the live
authoritative-suppression evidence; Run 56 remains classified as a VOID provider-credit
artifact, not an unresolved verifier defect (see the section above). **CLOSED / RESOLVED
FOR KNOWN HISTORICAL FALSE-BLOCKER FAMILIES** — authoritative contract-evidence
adjudication was live-validated in Run 66; Run 67 is consistent closure evidence, not
independent re-validation of the suppression mechanism itself. Not a claim of universal
future judge-phrasing coverage.

**4. `security-04-clean`** — expected OK, actual **UNVERIFIED**. Two HIGH `security`
findings (C1: `getaddrinfo` return-selection/ordering framing; C2: DNS-rebinding framing
excluded by the task's own explicit guarantee) both map to already-adjudicated v6 buckets
from the frozen classification, above — re-verified this run by independently running the
real Route A/B miners against their exact persisted text: neither mines any evidence, so
both remain `admissible=True` / `fail-closed-unresolved`, consistent with "no verifier-side
mechanism has safe material yield on this case." The MEDIUM CGNAT (`100.64.0.0/10`) concern
(C3) **remains visible and unsuppressed** — it was never a candidate for suppression, since
admissibility only ever evaluates HIGH/CRITICAL severity. One known verdict-consistency
schema failure occurred and was not rescued. No genuinely new verifier-side defect
appeared. **CLOSED BY ADJUDICATION — v6 DATASET/SPEC-PRECISION LIMITATION**; deferred to a
future v7 dataset revision only if independently justified. Not FIXED, and the CGNAT
concern is not erased or suppressed by this closure.

### Four-case closure table

| case | closure status |
|---|---|
| `correctness-02-clean` | **CLOSED / FIXED** |
| `security-02-clean` | **CLOSED / FIXED** |
| `edge_case-02-clean` | **CLOSED / RESOLVED FOR KNOWN HISTORICAL FALSE-BLOCKER FAMILIES** |
| `security-04-clean` | **CLOSED BY ADJUDICATION / v6 DATASET-SPEC LIMITATION** |

**All four original historical clean cases are now closed under bounded, evidence-backed
resolution classes — they are not all "fixed" in the same sense**: two were genuinely
repaired at the dataset level, one was live-validated against a specific, named
false-blocker mechanism (not a claim of universal coverage), and one was closed as an
adjudicated dataset/spec limitation, not a verifier fix, with its one live factual concern
(CGNAT) left deliberately visible rather than suppressed. **No further random or targeted
paid validation is required for this historical four-case closure. Runs 68+ are not needed
for it.** Reopening any of the four requires new, independent evidence — a freshly observed
case-specific failure, not a re-read of the runs already recorded here. Every historical
run record and prior pre-registration document (including `ADDENDUM_03`'s own frozen §3.7
wording) remains append-only and is not rewritten by this entry.

## Notes

- Runs 6-9 were executed on an identical commit (942f509) and show a spread of 29-32/40 correct verdicts (72.5%-80.0%), i.e. a ±3/40 noise floor. Single-run deltas smaller than this are not interpretable as real changes.
- v1 (runs 1-3), v2 (runs 4-17), and v3 (runs 18-19) use different dataset versions. Scores across the v1/v2 and v2/v3 boundaries are not comparable.
- `category_accuracy` changed meaning at commit 068c48b (run 15, "category field explicitly closed in judge template"). Values before and after this commit are not directly comparable.
- Most single-run deltas in this table fall within the ±3/40 noise floor and do not by themselves demonstrate an effect. Where a change was verified, it was verified by a specific, targeted observation rather than by the accuracy column — e.g. run 16's placement experiment resolved 4 of 5 known verdict/severity schema failures, and run 14's parser fix resolved quality-02-broken × correctness after 7 failures in 8 prior runs. Read the "what changed" column together with the schema-failure and defect tables, not the accuracy column alone.
- Dataset v3 (commit introducing this note) replaced quality-01 entirely and edited the clean side of quality-02, quality-03, quality-04, quality-05, security-02, and edge_case-04 to remove non-discriminating defects (properties present identically in both the clean and broken variant, which a judge could legitimately flag on either regardless of dataset version). v3 scores are not comparable to v1 or v2 — some of v1/v2's `false_unverified` count was structural (correctly detected but non-discriminating findings blocking clean cases), not judge error, so a v3 accuracy change cannot be read as a pure judge-behavior delta relative to earlier runs.
- RESOLVED (Phase 2B, run 19) — supersedes the earlier open item on whether naming-type defects belong in UNVERIFIED-expected cases: single-axis CODE-QUALITY blocking is achievable under the current pipeline. quality-02 (duplication) and quality-04 (policy-level magic numbers) reliably reach blocking severity on their authored CODE-QUALITY axis — each in 17/17 stored runs with defect data (runs 3-19). Two other defect classes, misleading naming and structural decomposition, are detected by the pipeline but do not reliably reach blocking severity; treat them as unreliable blocking measurements, not as undetectable defects or invalid dataset cases. The earlier objectivity hypothesis — that objective, countable defect classes are stable across runs while judgment-based ones are not — was NOT supported. Stability tracked proximity to the code-quality lens prompt's explicit inclusion criteria rather than whether a defect was objectively countable: quality-03's constant-extraction finding is objective yet drifted between MEDIUM and HIGH on identical code across runs 4-18, flipping that case's verdict six times, while quality-04's judgment-based nesting finding reached HIGH across runs 3-5. quality-01 and quality-03 therefore remain in the dataset with expected_verdict=UNVERIFIED — changing them to OK would assert that no quality defect exists, which the stored evidence contradicts, most notably run 12, where the judge identified the naming problem ("Consider renaming to 'get_or_create_user' to explicitly signal that this function has side effects (creates and stores new users), as 'get_user' typically implies a read-only operation") but rated it MEDIUM. Recorded finding only: it prescribes no prompt change, dataset change, or benchmark change.
- Phase 2C (runs 20-22) — variance characterization at commit c0515eb: 3 identical-configuration runs, all 33/40. c0515eb added the benchmark safety and analysis agent skills only; `src/` is byte-identical to run 19's dataset-v3 state except for the dataset v3 commit itself. Stored `created_at` values show runs 20-22 as a distinct batch (03:48, 03:56, 04:05) separated from runs 23-28 by a 56.6-minute gap.
- Baseline extension (runs 23-28) — same commit c0515eb, extending the Phase 2C cluster to 9 identical-configuration runs so a Phase 4 baseline arm could be registered. **Run 26 is excluded from that baseline arm under registered Amendment A1**: its `quality-04-clean` case recorded `eval_case_automated_gates.passed = 0` for the `mypy` gate while `detail` still read `ok` — a silent gate failure, which per the schema reference indicates environment contamination rather than judge behavior. Run 26 has zero `eval_case_results.error` rows, so it is *not* disqualified under the standard error-row rule; the A1 exclusion is narrower and specific to the Phase 4 arm. The registered Phase 4 baseline is therefore runs 20-25, 27, 28 (n=8): mean correct 33.000, SD 0.756, primary metric 8/32. Including run 26 (n=9) gives mean 32.889, SD 0.782.
- Phase 4 intervention (runs 29-36) — commit be990c7 appended a source-verification and task-scope constraint to `RESPONSE_INSTRUCTION`, the instruction shared by all three judge lenses. Scope was `RESPONSE_INSTRUCTION` only; LENSES, the JSON contract, the parser, `rubric.BLOCKING`, `verdict.gate`, and the dataset were unchanged. It tested whether blocking CRITICAL/HIGH findings on clean cases could be reduced when a finding is contradicted by the supplied source (Mechanism B) or rests on a requirement the task does not state (Mechanism C), without reducing task-supported findings (Mechanism A) or broken-case blocking.
- Phase 4 result — **INCONCLUSIVE** under the registered negative-result signature (registration section 14 satisfied); **H1 was not supported**. Measured: intervention arm n=8, mean 32.625, SD 1.061, vs registered baseline n=8, mean 33.000, SD 0.756 — a difference of 0.375 cases, far inside the noise floor. Mechanism evidence moved *opposite* to the hypothesis: mean `false_unverified` rose from 5.11 (runs 20-28) to 5.38 (runs 29-36), i.e. blocking on clean cases increased rather than decreased. Per-case, only four cases moved: `quality-02-clean` +55.6 pp (44.4% -> 100%), `quality-04-clean` -1.4 pp, `edge_case-04-clean` -18.1 pp (55.6% -> 37.5%), and `security-03-clean` -62.5 pp (100% -> 37.5%). None of the four always-fail clean cases moved at all.
- **Unregistered adverse finding — `security-03-clean`.** This case fell from 9/9 (100%) in runs 20-28 to 3/8 (37.5%) in runs 29-36. It was **not** among the registered guardrails (the registration guarded Mechanism A via `security-04-clean` and broken-case blocking via the 18-case G2 set), so this is recorded as an unregistered adverse finding, not as a triggered rejection criterion. It is the single largest per-case movement Phase 4 produced, and it should be a pre-registered guardrail in any future intervention that touches judge severity calibration.
- Revert (commit 64518fe) — reverted be990c7, restoring `RESPONSE_INSTRUCTION` in `judge.py` to its frozen c0515eb state. Verified: `git diff c0515eb 64518fe -- src/` returns empty, so HEAD is byte-identical to c0515eb across the whole source tree. The intervention commit and eval runs 29-36 are preserved unchanged. **Runs 20-28 therefore remain a valid frozen baseline for HEAD despite the differing SHA** — a SHA-differs-but-source-is-identical relationship that must be restated with its proving command whenever HEAD is compared against that cluster.
- **v3 noise floor — first direct measurement.** Two identical-configuration v3 clusters now exist: baseline runs 20-28 (n=9, SD 0.782; A1-excluded n=8, SD 0.756) and intervention runs 29-36 (n=8, SD 1.061). **Pooled v3 sigma = 0.92 cases** (0.9225 using the inclusive n=9 baseline, 0.9210 using the A1-excluded n=8 baseline — the A1 treatment does not change the pooled figure). **This supersedes the provisional sigma ~= 1.25 carried over from v2** in `experiment-design` and `benchmark-analysis`, which both previously recorded that no identical-configuration v3 cluster existed. The v2 figure should no longer be applied to v3 work.
- Hygiene finding — commit be990c7's message cites `PHASE4_REGISTRATION.md` as the source of its pre-registration ("applied verbatim"), but that file was never committed: it is absent from every branch and commit, from the deleted-file history, and from unreachable objects. The registered facts recoverable today come only from the be990c7 and 64518fe commit messages (Amendment A1, the n=8 baseline figures, Mechanism A/B/C scope, the G2 guard set, section 14's negative-result signature, and H1's non-support). The registration's full text — including the exact wording of H1, of section 14, and the G2 membership — is **not recoverable from this repository**. Future registrations should be committed alongside the intervention they govern.
- **Run 37 — a new configuration cluster begins at 77d36c3.** This note **supersedes the frozen-baseline note above** (the one recording that runs 20-28 remain a valid frozen baseline for HEAD). That statement was correct when written: at 0e2f204, `git diff c0515eb HEAD -- src/` returned empty. It stopped being correct when 77d36c3 landed. 77d36c3 changed two files on the measured path — `src/engine/eval/runner.py` and `src/engine/verification/pipeline.py` — plus three files off it (`cli.py`, `orchestrator/agents/common.py`, `providers/anthropic_provider.py`). `git diff c0515eb HEAD -- src/` now returns 5 changed files / 34 insertions and **no longer returns empty**, so the SHA-differs-but-source-is-identical justification no longer holds. Runs from 77d36c3 forward form a new configuration cluster; **at 2026-08-14 it contains exactly one run (37), so Phase 5 has no baseline arm.** 77d36c3's commit message argues the change is judge-neutral (the dataset is pure ASCII, so the encoding fix writes byte-identical content, and the temperature deny-list excludes `claude-haiku-4-5-20251001`, the judge model). That is a **mechanism argument, not a measurement** — it makes a fresh baseline cheap to believe, not unnecessary to collect.
- **Run 37 integrity and per-case detail** (read from a scratchpad copy of `.engine/state.db`, 2026-08-14). Zero `eval_case_results.error` rows; 120/120 `eval_case_lens_results.call_status = ok`; 120/120 `eval_case_automated_gates.passed = 1`; **1 schema failure** — `quality-02-broken` × `correctness` lens, `error_detail` = `verdict: is 'OK' but expected 'FAIL' given the defects`. Per the standard rule the schema failure is recorded, not disqualifying; the count matches runs 29-36, which carried 1-2 each, so it is not a new regression signal. The six failing cases are **exactly** the always-fail set measured across runs 20-28 — `correctness-02-clean`, `edge_case-03-clean`, `quality-01-broken`, `quality-03-broken`, `security-02-clean`, `security-04-clean`, each 0/9 there — and all three borderline cases (`edge_case-04-clean`, `quality-02-clean`, `quality-04-clean`) passed. `security-03-clean` passed, consistent with runs 36-37 after the revert.
- **Run 37 interpretation — not a finding.** 34/40 against the registered Phase 4 baseline mean of 33.000 is a difference of +1.0 case, roughly 1.1σ at σ = 0.92. **n = 1, inside the noise floor.** It is not evidence that 77d36c3 improved anything and must not be cited as such; per the project's own rule, the bugfix is verified by the automated gates and by the targeted observation recorded in its commit message (run 42 flowed 36 non-ASCII characters end-to-end with zero `UnicodeEncodeError`), never by the accuracy column.
- **σ = 0.92 is now itself a carried-over figure.** The pooled v3 estimate was measured on the c0515eb and be990c7 clusters. No identical-configuration cluster exists at 77d36c3, so applying σ = 0.92 to runs from 77d36c3 forward is provisional in exactly the way v2's σ = 1.25 was provisional for v3 — label it as carried over until a 77d36c3 cluster is measured. Sample sizes re-derived from σ = 0.92 (2026-08-14) now live in `.claude/skills/experiment-design/SKILL.md`, replacing the flagged σ = 1.25 table: a 2-case aggregate shift needs ~4 runs per arm and n=8 buys an aggregate MDE of ~1.3 cases. **N must not be shrunk to 4 on that basis** — the primary metric is the per-case blocking rate, a proportion test unaffected by σ, and at N=4 per arm only an all-or-nothing 4/4 movement clears p < 0.05 (3/4 gives p = 0.143, two-sided Fisher). N=8 per arm remains the working default.
- Runs 38-41 — commit `d856d72` ("Register Phase 5A: baseline characterization at the current configuration"), four identical-configuration v3 runs: 31, 32, 33, 32 correct (mean 32.00, SD 0.816, range 31-33). Consistent with the pooled v3 sigma of 0.92 and adding a third v3 cluster to the two already recorded. All four used the Haiku judge.
- **Dataset v4 boundary — commit `f79353c` ("Benchmark v2 dataset checkpoint")**, which set `DATASET_VERSION = "v4"` and `BENCHMARK_VERSION = "v2"` and rewrote 193 lines of `eval/dataset.py`. This is the real v3/v4 comparability boundary. Run 42 is stamped `c2ec1e4` only because that commit (a documentation-only branding rename that changed no dataset content) was HEAD when the run executed. **Never read run 42's SHA as the origin of dataset v4.** v4 scores are not comparable to v1, v2 or v3.
- **JUDGE MODEL CONFIGURATION BREAK — commit `83a4000` ("Experiment: upgrade judge to Sonnet 5").** Every completed run in this table, 1 through 42, used `claude-haiku-4-5-20251001` as the judge. `83a4000` changed `DEFAULT_MODELS["anthropic"]["judge"]` in `src/engine/config.py` to `claude-sonnet-5`. The judge model is part of the measured configuration, so this starts a NEW CONFIGURATION CLUSTER that currently holds **zero completed runs** — run 43, its only attempt, is void. Consequences, all of which must be stated whenever HEAD is compared against this table: (a) **run 42 is not a baseline for any commit at or after `83a4000`**; (b) every off-lens, severity and stability figure derived from runs 1-42 describes *Haiku's* behaviour and may not transfer to Sonnet; (c) measured cost and wall time rose from ~$0.12 and ~3.5 min per run to **~$0.57 and ~10.3 min**, roughly 4.4x and 3x, because Sonnet 5 emits ~2.8x the output tokens (mean 355 vs 125, reaching the 1600 cap) — see the Phase 9C/9E notes in `judge.py`. Note this is the *second* independent reason run 42 cannot baseline HEAD; the first is the 89-line Phase 9C/9E change to `judge.py` between `c2ec1e4` and the current branch.
- **Run 43 is VOID and must never be scored, averaged, or counted in a cluster.** It was killed by a harness timeout partway through, leaving 35 of 40 case results written, 108 of 120 lens calls made, $0.5133 spent, and `eval_runs.total_cases = 0` because the aggregating update never ran. Its `runs` row (id 52) is still `status = 'running'`. Both rows were retained rather than deleted, because `.engine/state.db` is append-only and has no backup. **Read its stored `0` the way run 1's is read** — a numerator that was never populated, not a 0/40 result (see the denominator trap in the schema reference). Its 35 partial case results may be inspected as exploratory data but are not a run.
- Governance — `src/engine/config.py` was added to the `git-safety` measured-path list on 2026-09-02, after `83a4000` showed that `DEFAULT_MODELS` could change which model every judge lens runs on without the approval that list exists to require. The registration governing the experiment run 43 was attempting is `docs/benchmark/OFFLENS_BLOCKING_REGISTRATION.md`.
- Run 44 — the first completed run on the Sonnet judge, and Run 1 of `OFFLENS_BLOCKING_REGISTRATION.md`. Integrity gate passed on all four checks (0 error rows, 120/120 `call_status = ok`, 120/120 automated gates, and an exact 0/40 reconstruction of stored verdicts from stored defects). Scoring the identical stored defects under the registered candidate rule R-a (off-lens defects recorded but non-blocking) produced **no change whatsoever**: 36/40 under both arms, `false_pass` 0 under both, `false_unverified` 4 under both, zero per-case verdict changes, and **zero broken-case flips**, so the hard-reject criterion was not triggered. The rule's status is therefore **safety-clean in Run 1, benefit unproven** — a single run cannot ACCEPT it, and 0 clean-case fixes is the registered INCONCLUSIVE condition. Off-lens emission was present but never decisive: 7 off-lens defects, 4 of them blocking (3x `security -> CORRECTNESS/HIGH`, the live Debug failure's exact signature, plus 1x `correctness -> SECURITY/CRITICAL`), each on a case that also carried an on-lens blocker. Margin: 8 of the 20 blocked broken cases rested on a single on-lens blocker, none on zero. `security-03-clean` returned OK under both arms with no blocking defect at all.
- **`security-04-clean` is a STRUCTURAL false_unverified on dataset v4, not a judgment failure.** It has been `expected=OK, actual=UNVERIFIED` in every v4 run to date — 42, 43 and 44 — and in each case the UNVERIFIED came from `verdict.gate` failing closed on a schema error, not from any lens finding a defect. Forensics on run 44: the `correctness` and `security` lenses each returned `stop_reason = max_tokens` with `output_tokens = 1600`, `thinking_tokens = 1600/1599` and **zero characters of text** — the entire output budget consumed by thinking with no answer emitted. The Phase 9E retry fired correctly on both and **failed identically** (again 1600 output, 1600/1598 thinking, zero text), so 4 calls and ~$0.064 bought nothing. The same case truncated under **Haiku** at run 42 as well (`correctness`, `output_tokens = 800`, exactly the then-current cap), so this is a property of the case's v4 content that Sonnet amplifies from one lens to two — not a Sonnet-only defect. Anyone comparing v4 accuracy should treat one of the four `false_unverified` as a truncation artifact rather than a verdict.
- Schema reliability at Sonnet-1600 — **concentrated, not diffuse.** Across run 44's 122 calls, 118 ended `end_turn`, median output was 167 tokens, and only 4 calls (3.3%) reached the 1600 cap — all 4 being the `security-04-clean` pair and their retries. Thinking was zero on 65 of 122 calls. The run's 3 schema failures sit against a Haiku baseline of mean 1.00 per run (runs 20-42, n=23, SD 0.66, range 0-2), so the rate is elevated and outside the Haiku range, but on n=1 Sonnet run that is suggestive rather than established. The third failure, `quality-05-broken` x `security`, was **not** truncation: a complete 361-character response (`stop_reason = end_turn`, 135 output tokens, zero thinking) that declared `verdict: FAIL` while reporting only a MEDIUM defect, violating the schema's "FAIL iff CRITICAL or HIGH" rule. The retry correctly did not fire, exactly as `judge.py` intends. Historically that semantic class dominates: of 40 recorded schema failures, 24 are verdict inconsistencies and only 6 are missing-JSON.
- Phase 9E premise update — the retry was registered on the reasoning that an identical resample is "a fresh draw from a heavy-tailed distribution". On `security-04-clean` that does not hold: 4 of 4 attempts across two lenses burned ~1600 thinking tokens and emitted nothing, i.e. the outcome was effectively deterministic for this input. Raising the cap and lowering effort were both already tried and reverted (Phase 9C.3 and 9C.2, the latter having produced a false pass), so no cap-side lever should be re-attempted on this evidence without a new mechanism.
- **Run 45 — Answer-Budget Phase 2 targeted live validation, Stage 1** (`docs/benchmark/ANSWER_BUDGET_PHASE2_REGISTRATION.md` §7.1-7.3, implemented at commit `b069b45`). `engine bench --category security` — 10 cases, not the 40-case benchmark — is the registered vehicle, chosen because every retry firing ever observed (runs 43-44) occurred inside this category. **Excluded from every accuracy, variance and stability pool**: the 8/10 figure has a different denominator than every other row in this table and is not comparable to it.
  - **Retry firings: 4** — `security-04-clean` × {correctness, security, code-quality} and `security-02-clean` × security. One more lens (`code-quality`) fired than either prior Sonnet run (43, 44 each fired only correctness/security on `security-04-clean`); still entirely inside the `security` category, as the registration's own scope note anticipated.
  - **Invariants I1-I7, all held.** I1 (paired: every retry's sibling initial call has `thinking_tokens > 0`) — 4/4. I2 (aggregate: initial calls with `thinking_tokens > 0`) — 20/30, identical to both prior Sonnet runs, far above the registered floor of 10/30. I3 (no initial call shows the disabled signature) — 0 hits. I4 (every retry's sibling initial has `stop_reason = 'max_tokens'`) — 4/4. I5 (no retry issued for a non-truncated initial) — 0 violations across 26 non-`max_tokens` initials. I6 (retry `thinking_tokens = 0`, read from `usage.output_tokens_details`) — 0 on all 4 retries (baseline before Phase 2: 958-1600). I7 (a lens still `schema_valid = 0` after its retry leaves the case `UNVERIFIED`) — vacuously true; no lens ended unrescued this run.
  - **E1 (primary metric): 4/4 retries produced a schema-valid critic.** n=4, k=4 clears the registered §8.1 Fisher threshold (k≥3 required at n=4, p=0.048) at p=0.0079, and the n≥3 evaluability floor was reached from Stage 1 alone.
  - **Guardrails.** `false_pass = 0` (no attribution query needed). Integrity clean: 0 `agent_execution_metrics.status = 'error'` rows, 34/34 judge calls `ok` (30 initial + 4 retry), 30/30 `eval_case_automated_gates.passed`, 0 `eval_case_schema_failures` rows (both truncated lenses on `security-04-clean` and the one on `security-02-clean` were rescued to schema-valid; run 44 by comparison had 3 failures before Phase 2).
  - **Verdict: ACCEPT** under registration §8.2 — all of (a) offline gates pass (ruff/mypy/pytest, prior commit `b069b45`), (b) I1-I7 hold, (c) E1 clears §8.1 at n≥3, (d) `false_pass = 0`, (e) integrity clean.
  - **Stage 2 not run.** The registered extension rule (§7.2) adds runs only when cumulative firings are still below 3; Stage 1 alone reached 4, so the sequence stopped there per that same firing-count logic, spending $0.2279 of the registered $0.60 N=2 ceiling.
  - As predicted in registration §2, `correct_verdicts` (8/10) and `false_unverified` (2, both `security-04-clean` and `security-02-clean` — expected, since a schema-error rescue that lands on a blocking defect stays `UNVERIFIED-by-blocking-defect`) decide nothing per §8.3 and are recorded as observations only.
- **Run 46 — first full 40-case run under the Answer-Budget Phase 2 configuration**, and the run `docs/benchmark/DATASET_V5_AMENDMENT.md` bases its A-4/A-5 adjudication on. Integrity gate passed on all checks read from a scratchpad copy of `.engine/state.db`: 40/40 `eval_case_results` rows, 0 `error` rows, 120/120 `eval_case_lens_results.call_status = ok`, 120/120 `eval_case_automated_gates.passed = 1`, **0 rows in `eval_case_schema_failures`** (run 44, the prior full-40 Sonnet run, had 3). Score is unchanged from run 44 — 36/40, `false_pass` 0, `false_unverified` 4 — with the **identical four cases** failing in both runs: `correctness-02-clean`, `edge_case-02-clean`, `security-02-clean`, `security-04-clean`. Category accuracy: correctness 0.9, security 0.8, quality 1.0, edge_case 0.9. Cost `$0.533374`, matching the figure `DATASET_V5_AMENDMENT.md` cites. **This is not additional evidence of accuracy movement over run 44** (n=1 each, same four structural failures, well inside any noise floor) — read together with run 44, it is evidence that the Phase 2 retry change (commit `b069b45`) eliminated schema failures on this configuration without changing any verdict. **Run 46 is the valid Sonnet/v4 production result** and remains so after the v5 boundary below: 36/40, 0 false passes, 4 false-unverified label disagreements, 0 schema failures.
- **Dataset v5 boundary — commit `eea901e` ("Dataset v5 -- implement and close amendments A-4 and A-5"), registered in `docs/benchmark/DATASET_V5_AMENDMENT.md`.** Bumps `DATASET_VERSION` v4 -> v5. A-4 repairs `correctness-02-clean`'s float-subtraction boundary defect (exact decimal-value comparison, rejecting an exact 0.01 difference). A-5 repairs `security-02-clean`'s converter argument-injection gap (full-match filename whitelist, fixed absolute executable path, no-shell list-form invocation) and is closed as ACCEPT WITH DOCUMENTED PLATFORM ASSUMPTION (a POSIX `convert`-style CLI at a fixed path; see the amendment doc for the three-part structural safety argument that substitutes for live-binary execution). `edge_case-02-clean` and `security-04-clean` — the other two of run 46's four false_unverified cases — are **explicitly out of scope for this phase**; their grounding/severity issues are reserved for later verifier work, not touched by A-4/A-5. **A-4/A-5 are dataset/spec conformance corrections, not verifier accuracy improvements** — no prompt, rubric, schema, gate, merge, or model-configuration change is part of this commit, and P1/P2/P3 and the off-lens/R-a disposition (CLOSED: NO BENEFIT SHOWN) remain frozen. **v5 currently has zero live baseline measurements**: no `engine bench` run has executed against v5 as of this entry. **v5 scores are not comparable to v4** (or to v1/v2/v3) — the existing dataset-version boundary convention in this file applies to the v4/v5 line exactly as it does to v1/v2/v3/v4: any future v5 run opens a new series and must be recorded, analyzed and compared only within that series. **No historical v4 row is rewritten, relabeled or reinterpreted by this boundary** — run 46 stands exactly as recorded above, and every v3/v2/v1 row is likewise untouched.
- **Run 65 is an accidental zero-case audit artifact and must never be scored, averaged, or counted in a cluster.** While manually auditing the unknown-`--case-id` safety property of the `--adjudicate`/`--case-id` CLI plumbing (commits `882fd858c6a09f10f50066ba94c3f493ec02c9d6`, `a32633e20826d76cdf75b73d75cd847c87954325`), one command was run against the real `.engine/state.db` instead of a redirected scratch copy: `engine bench --adjudicate --case-id nonexistent-case-id`. This created `eval_run #65`: `total_cases = 0`, `correct_verdicts = 0`, `false_pass = 0`, `false_unverified = 0`, `total_cost = 0`, `git_commit_sha = 882fd858c6a09f10f50066ba94c3f493ec02c9d6`, and **zero** rows in `eval_case_results` — no eval case was executed and no provider/API call occurred, because the unknown case ID matched nothing and the benchmark loop never ran. `PRAGMA integrity_check` remained `ok`, re-verified from a scratchpad copy. **The row was intentionally not edited or deleted** — `.engine/state.db` is append-only with no backup, per the same rule that kept run 43's void row in place. Read its stored `0`s as a numerator that was never populated by any measurement, not as a 0/0 result. This is disclosed here for completeness; it carries no accuracy signal and is unrelated to the correctness of the audited commits, which passed their own focused/full test suites (188/1870 passed, ruff and mypy clean) before and after this incident. See `docs/benchmark/COMBINED_CONTRACT_EVIDENCE_MINING_SHADOW_REGISTRATION_ADDENDUM_03.md` §2 for the full incident record.
