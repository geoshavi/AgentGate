# Registration B — Addendum 01: Executable SHA and pre-run database baseline

**Type: provenance only.** This addendum records two facts that did not exist when
Registration B was frozen. It changes **no** hypothesis, metric, threshold, decision rule,
frozen variable, phase, or cost ceiling. `EVIDENCE_CAPTURE_PROMPT_REGISTRATION_B.md` is not
edited and remains valid exactly as written.

If any decision rule ever needs to change, that is a **new registration**, not an addendum.

---

## 1. Why this addendum exists

Registration B records one SHA — `41584085dc098ed9a9e97772389cf9354136cfb3` — as the base
(control) configuration. The document was then committed at
`44ef7a4785d58b4da7fee6fa6d5680f6c93a62dd`, which is now HEAD.

`get_git_commit_sha()` stamps each run with **HEAD**, so a live run started now records
`44ef7a4`. Registration B §10.2 and §16.2 require that the recorded SHA "matches this plan,"
and the plan contains no SHA equal to `44ef7a4` — it could not, since that commit did not
exist when the document was frozen.

The configuration is provably unchanged (§2). What was missing is the explicit link between
the registered plan and the SHA a run will actually be stamped with. Leaving that to
inference is the precise failure mode this repository's discipline exists to prevent: a run
is only interpretable if the code that produced it is exactly identifiable. This addendum
supplies the link.

---

## 2. Executable SHA

| role | SHA | meaning |
|---|---|---|
| **measured-path base (control configuration)** | `41584085dc098ed9a9e97772389cf9354136cfb3` | unchanged from Registration B §1 |
| **executable SHA (control arm)** | `44ef7a4785d58b4da7fee6fa6d5680f6c93a62dd` | the SHA a Phase 0 / control-arm run is stamped with |

**Both refer to the same measured configuration.** Verified at blob level: every file on the
`git-safety` measured path and every file in Registration B §9's frozen-variable list is
**byte-identical** between the two commits.

```
dataset.py  runner.py  judge.py  rubric.py  schema.py  verdict.py  pipeline.py
adjudication.py  admissibility.py  probes.py  gateway.py  budget.py  config.py
```

`git diff --name-status 4158408 44ef7a4` returns exactly three paths, none of them frozen:

| path | status | frozen by §9? |
|---|---|---|
| `docs/benchmark/EVIDENCE_CAPTURE_PROMPT_REGISTRATION_B.md` | added | no — the registration itself |
| `src/engine/cli.py` | modified | **no** — absent from §9 |
| `tests/test_eval_cli_shadow.py` | added | no |

The `cli.py` change is the `--shadow-adjudicate` flag. It is **required infrastructure**:
Registration B §6 states that *every* run under this registration uses
`engine bench --shadow-adjudicate`, and before `44ef7a4` no CLI surface existed to enable it.
The flag defaults to `False`, so with it absent the `run_benchmark` call is identical to
before it existed. Registration B §1 already anticipated this commit in the
"measured path at registration" row.

`judge.py` blob remains `2a2a17f16611d4586d122d6e65710f9bd520910f` and
`RESPONSE_INSTRUCTION` sha256 remains
`e5dd7f825008a752c19d4dc77fbec65ed74be9dbfc36c29c2bc9691c9924dd4f`.

### 2.1 Shadow mode is held constant, not varied

Running with `--shadow-adjudicate` executes `adjudication_record()` per defect — local
computation only (`ast.parse`, string comparison), no provider call, no added cost. It writes
sidecar rows and marginally increases wall time. It cannot change a verdict
(`tests/test_shadow_adjudication.py`). Because **both arms** use it, it is a constant, not a
second independent variable. It does mean runs under this registration are not directly
comparable to historical runs that executed without it — already covered by §1.2, which
records that this configuration cluster holds zero completed runs regardless.

### 2.2 When the intervention SHA exists

Registration B §16.5 requires the intervention SHA and its new `RESPONSE_INSTRUCTION` sha256
to be recorded once they exist. They go in **Addendum 02**, not in the frozen document.

---

## 3. Pre-run database baseline

`.engine/state.db` underwent an **accidental additive schema migration** on 2026-09-11 when a
CLI test reached `db.connect(config.db_path)` without redirecting `ENGINE_DB_PATH`.
`db.connect` runs `executescript(SCHEMA)`, `_migrate()` and `commit()` on whatever file it is
given. Fixed at `44ef7a4`; every test in `tests/test_eval_cli_shadow.py` now redirects to
`tmp_path`, and `test_compare_never_touches_the_production_database` pins it.

| | before | after (frozen baseline) |
|---|---|---|
| sha256 | `62e42d44d7c04de68e2cdae0a2784e4c1ab6f9eeb3a405148c8b33e8a8edacce` | **`665773a9d626d04ac7eb4792ebd4af0a0d5b2617461a877f08501adf8a07fba9`** |
| size | 4190208 | **4198400** (+8192, two pages) |

**The frozen pre-run baseline for every future live run under Registration B is
`665773a9d626d04ac7eb4792ebd4af0a0d5b2617461a877f08501adf8a07fba9`, size 4198400.**

Any future divergence from this hash that is not explained by a recorded `engine bench` run
is an integrity incident and must be investigated before the run it precedes is trusted.

### 3.1 Verified intact

- `PRAGMA integrity_check` = `ok`; `journal_mode` = `delete`; **no `-wal`, no `-shm`**
- `eval_runs`: 57 rows, ids **1-57 contiguous, zero gaps**
- runs **50, 51, 52, 53, 54, 55, 57** — `git_commit_sha`, `dataset_version`, `total_cases`,
  `correct_verdicts`, `false_pass`, `false_unverified` all **match BASELINE.md exactly**;
  run 56 present and still VOID
- `eval_case_results` 2215 · `eval_case_defects` 5167 · `eval_case_lens_results` 6405 ·
  `eval_case_automated_gates` 6372 · `eval_case_schema_failures` 62
- `eval_case_defect_adjudications`: **0 rows**, DDL identical to the committed `SCHEMA`
- No table exists outside the committed `SCHEMA`; none is missing. The one pre-existing DDL
  difference (`agent_execution_metrics` column *ordering*) is an artifact of an older
  `_migrate()` `ALTER TABLE`, same column set, unrelated to this incident

### 3.2 Effect on experiment validity: none

The mutation added an empty table and changed no row. No `eval_runs`, `eval_case_results`,
`eval_case_defects`, `eval_case_lens_results` or aggregate figure differs. No measurement was
created, altered or deleted, so no run's provenance and no historical comparison is affected.

The table is **left in place**. It is part of the committed `SCHEMA`, so the next
`engine bench` would create it regardless; dropping it would be a second unapproved mutation
of a file with no backup.

**What it does establish** is that `.engine/state.db` can be written by something other than
`engine bench`, contrary to Registration B §10.5. The safeguard is the test-level redirect
plus §10.5 itself, and the frozen hash above makes any recurrence detectable rather than
silent.

---

## 4. What this addendum does not do

- Does not alter the hypothesis, E1/E2/E3, the 40% futility floor, the false-pass STOP rule,
  the schema-failure abort threshold of 6, the `quality-04-broken` guardrail, the
  sole-blocker rule, N per arm, ACCEPT/REJECT/INCONCLUSIVE criteria, or the $30 stop-loss.
- Does not authorise any run. Every phase still requires its own per-turn approval and a
  passing `git-safety` pre-run gate.
- Does not change the ordering in §16: **Phase 0 (control prompt, no `judge.py` change) runs
  first**, and its figures reach BASELINE.md before any intervention run.

---

## 5. Provenance

- Written: 2026-09-11, before any run under Registration B existed
- Registration B commit: `44ef7a4785d58b4da7fee6fa6d5680f6c93a62dd`
- Registration B base SHA: `41584085dc098ed9a9e97772389cf9354136cfb3`
- Runs executed against Registration B at time of writing: **none**
- No benchmark run, no provider call, no spend produced this document
