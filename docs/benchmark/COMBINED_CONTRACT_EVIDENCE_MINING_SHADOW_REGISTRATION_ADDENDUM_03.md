# Combined Contract Evidence Mining Shadow Registration — Addendum 03:
# Authoritative Engineering, Audit Incident, and Live Validation Pre-Registration

**Type: engineering provenance + incident record + pre-registration.** This addendum
records two commits that moved the frozen shadow prototype (Addendum 02) toward an
authoritative path, discloses an unrelated audit incident that touched the production
database, and pre-registers the future live validation. It changes **no** hypothesis,
frozen variable, STOP rule, or success criterion in
`COMBINED_CONTRACT_EVIDENCE_MINING_SHADOW_REGISTRATION.md`, which is not edited and remains
valid exactly as written.

**No live run has executed against this registration or this addendum at the time of
writing. This addendum does not authorize one.** The pre-registration in §3 becomes
executable only once a future turn gives it its own, separate, explicit authorization.

---

## 1. Engineering state

| item | value |
|---|---|
| authoritative mined-evidence wiring commit | `882fd858c6a09f10f50066ba94c3f493ec02c9d6` |
| targeted CLI/eval plumbing commit | `a32633e20826d76cdf75b73d75cd847c87954325` |

What these two commits establish, together:

- `pipeline.run_verification(..., adjudicate=True)` now augments the real defects that
  reach `admissibility.annotate()` with the same mined evidence
  (`_authoritative_defects`/`_with_mined_evidence`) the shadow path already computed —
  reusing the existing Route A/B mining and adjudication logic verbatim, no second
  implementation.
- `engine bench --adjudicate` **requires** an explicit `--case-id` (repeatable). A
  category-wide or full-dataset invocation of `--adjudicate` (no `--case-id`, or
  `--category` alone) is refused by the CLI itself, before `load_config()` or any provider
  setup.
- `--shadow-adjudicate` and `--adjudicate` are a single `argparse` mutually-exclusive
  group — combining them is refused by argparse during argument parsing, before the
  `bench` command body ever runs. `pipeline.run_verification` itself also raises
  `ValueError` if both are ever set together, as a second line of defense for any
  non-CLI caller.
- Default behavior is unchanged: `api.py`'s `review_code` and
  `orchestrator/manager.py`'s `run_verification` call sites pass neither flag, and every
  existing `engine bench` invocation with no adjudication flag reaches `run_benchmark`
  with `case_ids=None, shadow_adjudicate=False, adjudicate=False` exactly as before either
  commit existed.
- An unknown or non-matching `--case-id` value never falls back to a broader (category- or
  full-dataset) selection: `select_cases` only ever narrows a category selection by
  intersecting with the named case IDs, so a miss produces an explicit zero-case run
  (`Cases: 0`, `$0.000000` cost, no crash), never a silent broadening.

---

## 2. Audit incident: accidental zero-case production DB write

While manually verifying the unknown-`--case-id` safety property above, one command was
run without redirecting `ENGINE_DB_PATH`, so it executed `engine bench --adjudicate
--case-id nonexistent-case-id` against the **real** `.engine/state.db` instead of a
scratch copy.

- **This created `eval_run #65`.**
- `total_cases = 0`, `correct_verdicts = 0`, `false_pass = 0`, `false_unverified = 0`,
  `total_cost = 0`.
- Stamped `git_commit_sha = 882fd858c6a09f10f50066ba94c3f493ec02c9d6`.
- **Zero rows in `eval_case_results` for this run** — no eval case was executed, and no
  provider/API call occurred (the loop over an empty case list never reaches
  `run_verification`).
- `PRAGMA integrity_check` on `.engine/state.db` remains `ok`, re-verified via a
  scratchpad copy per this project's convention of never opening the live file directly
  for a read.
- **The row was intentionally not edited or deleted.** `.engine/state.db` is append-only
  benchmark history with no backup; per `git-safety`, rows are never edited or deleted
  even to correct a mistake.
- **Classification: this is an accidental zero-case audit artifact, not a benchmark
  measurement.** It carries no accuracy signal (0 of 0 cases), was not compared against
  or averaged with any other run, and must never be read as a data point in any future
  accuracy or stability analysis. Any query over `eval_runs` for accuracy purposes should
  exclude it on the same basis `baseline-evidence` already excludes error rows —
  `total_cases = 0` is definitionally uninformative, not merely low-quality.

---

## 3. Live validation pre-registration — target, purpose, execution policy

**Status: REGISTERED, NOT YET AUTHORIZED. No live run has executed against it.**

### 3.1 Target and controls

| role | case |
|---|---|
| target | `edge_case-02-clean` |
| safety control | `edge_case-02-broken` |
| safety control | `quality-04-broken` |
| safety control | `security-03-broken` |
| safety control | `security-04-broken` |

### 3.2 Purpose

Exercise a real, live HIGH/CRITICAL Route A or Route B blocking finding on
`edge_case-02-clean` under authoritative adjudication (`adjudicate=True`, wired at
`882fd85`), and verify that **only** the contract-contradicted finding loses blocking
authority — nothing else, on this case or any control.

### 3.3 Execution policy

- **Maximum N=4 target repetitions. N=4 is a ceiling, not a mandatory count** — the run
  stops immediately on the first SUCCESS or REJECT, whichever comes first, even if that is
  repetition 1.
- **Run exactly one invocation at a time.** No batching, no fire-and-forget loop.
- **Inspect the result after every single invocation before deciding whether to
  continue.**
- **Stop immediately on SUCCESS or REJECT.** Do not run a confirming repetition after
  SUCCESS, and do not continue past a REJECT to see if it recurs.
- **Continue past an INCONCLUSIVE result only after explicit review and a fresh,
  separate authorization for the next repetition.** An INCONCLUSIVE result never
  self-authorizes another call.

### 3.4 SUCCESS criteria (all must hold)

- `edge_case-02-clean` produces a live HIGH/CRITICAL defect that Route A or Route B
  recognizes (a `minimal_trigger` is mined).
- That defect's `admissible_to_block` becomes `False`.
- Its `admissibility_rule`/`admissibility_reason` are consistent with the existing,
  unmodified contract-adjudication rules (`declared-interface` for Route A,
  `factual-premise` for Route B — no new rule name, no new reasoning path).
- The case's final `actual_verdict` becomes `OK`.
- All four safety controls retain at least one legitimate, unsuppressed blocker.
- `false_pass` is 0 across every case run in that invocation.

### 3.5 REJECT criteria (any one is sufficient, and stops the phase immediately)

- Any safety control loses a legitimate blocker.
- Any Route A/B miner hit occurs on any safety control.
- Any `false_pass` occurs, anywhere.
- Route A and Route B both match the same defect (dual-match overlap).
- A schema failure or automated-gate failure is incorrectly rescued by admissibility
  (should be structurally impossible per `verdict.gate`'s evaluation order, but treated as
  an immediate REJECT if ever observed).

### 3.6 INCONCLUSIVE criteria (not failure; does not justify broadening suppression)

- `edge_case-02-clean` returns `OK` without the mechanism being exercised at all (no
  HIGH/CRITICAL defect was raised this run).
- `edge_case-02-clean` remains `UNVERIFIED` for a finding neither route recognizes.
- `edge_case-02-clean` reproduces a run-56-like pattern (historically unexplained by
  either route).

An INCONCLUSIVE result is evidence the mechanism was not exercised this repetition — it is
never evidence the mechanism doesn't work, and it never justifies widening what mining
recognizes or relaxing an adjudication rule to force a hit.

### 3.7 Claim limits — binding even after SUCCESS

The only claim SUCCESS licenses is exactly:

> "Authoritative contract-evidence adjudication was live-validated for a real Route A/B
> false blocker with no observed control suppression."

Explicitly **not** licensed by SUCCESS, or by any number of repetitions up to N=4:

- That `edge_case-02-clean` is fully fixed. Its historical coverage is 5 of 6 known
  `UNVERIFIED` v6 runs, not 6 of 6.
- That **run 56's cause is resolved.** Run 56 remains unexplained by either route and
  stays that way regardless of this phase's outcome.
- That the mechanism is validated for any case other than the one exercised, or that
  authoritative adjudication is ready for a rollout wider than this named target and its
  four controls.
- That `security-04-clean` is affected in any way — it remains untouched and out of scope,
  exactly as the base registration states.

### 3.8 Forensic requirement — capture before moving on

**`eval_case_defects` does not persist `admissible_to_block`, `admissibility_rule`, or
`admissibility_reason`** (confirmed: `db.record_eval_case_defects` only writes `lens`,
`defect_id`, `category`, `severity`, `location`, `fix`). These fields exist only on the
in-memory defect dicts inside the `EvalCaseResult.defects` that `run_benchmark`/`run_case`
return for that one process's lifetime, and in the printed benchmark report.

**Therefore: before moving from one invocation to the next, the per-run defect and
admissibility detail (which defect, which rule, `admissible_to_block` value, mined
`minimal_trigger`) must be captured from that invocation's immediate result or printed
report.** Once the process exits, this detail is not recoverable from `.engine/state.db`
alone — only the final `actual_verdict` per case is durably queryable afterward. A future
turn evaluating SUCCESS/REJECT/INCONCLUSIVE against §3.4–§3.6 must do so from that
captured detail, not from a later database query.

---

## 4. What this addendum does not do

- Does not alter the hypothesis, frozen variables, STOP rules, or success criteria in
  `COMBINED_CONTRACT_EVIDENCE_MINING_SHADOW_REGISTRATION.md`.
- Does not authorize any live run. §3's pre-registration requires its own separate,
  explicit per-turn authorization before LIVE RUN 1 may execute, and a passing
  `git-safety` pre-run gate at that time.
- Does not enable authoritative suppression outside the exact `--case-id`-gated CLI path
  committed at `a32633e`.
- Does not edit or delete the `eval_run #65` artifact, and does not treat it as
  benchmark evidence of any kind.

---

## 5. Provenance

- Written: 2026-09-13, before LIVE RUN 1 of this pre-registration exists.
- Registration commit: `5a7c9f8a2e68d3c3e206028a1b646dffaffc5332`.
- Wiring implementation (shadow, combined routes) commit:
  `4350a9f6606e49c9708de2b17860ad6310cea346`.
- Authoritative mined-evidence wiring commit:
  `882fd858c6a09f10f50066ba94c3f493ec02c9d6`.
- Targeted CLI/eval plumbing commit: `a32633e20826d76cdf75b73d75cd847c87954325`.
- Runs executed against this addendum's pre-registration at time of writing: **none.**
- No benchmark run, no provider call, no spend, and no DB row edit or deletion produced
  this document. The one DB write referenced (§2) predates this document, is disclosed in
  full, and is not a product of writing it.
