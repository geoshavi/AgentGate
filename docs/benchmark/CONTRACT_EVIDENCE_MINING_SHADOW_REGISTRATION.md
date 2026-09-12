# Contract Evidence Mining — Shadow Registration

**Status: REGISTERED, FROZEN. No live run has been executed against it.**

Pre-registered per `.claude/skills/experiment-design`. This is a **new, independent
registration**. It does not reopen, amend, or supersede
`EVIDENCE_CAPTURE_PROMPT_REGISTRATION_B.md`, which remains **REJECTED and CLOSED**
exactly as recorded in `BASELINE.md`. Nothing here changes that record.

---

## 0. What this experiment is, in one sentence

Measure, first entirely offline and then in a single non-authoritative live shadow run,
whether a deterministic, judge-prompt-neutral text-and-AST miner
(`src/engine/verification/evidence_mining.py`) can recover enough `minimal_trigger`
evidence from a defect's own existing free text to make `edge_case-02-clean`'s recurring
out-of-contract finding newly eligible for the *existing, unmodified* declared-interface
adjudication path — **without asking the judge for anything, without touching severity,
and without ever letting a verdict actually change in this phase.**

**This is not a Registration-B-style prompt experiment.** No file the judge reads is
touched by this mechanism at any point, in any phase. The independent variable here is a
new, additive, currently-unwired Python module — not a prompt.

---

## 1. Frozen configuration

| item | value |
|---|---|
| branch | `feature/agent-capabilities-layer` |
| base SHA (control, pre-registration) | `b5abc6dfb48f46353955a505adae2779f0ecd3d5` |
| measured path at registration | **identical to `b5abc6d`** on every judge/verdict/schema file — the commit carrying this document adds only a regression test (`tests/test_admissibility.py`) and this document, neither on the measured path |
| dataset version | **v6** (`dataset.py:34 DATASET_VERSION = "v6"`), 40 cases |
| provider | `anthropic` |
| judge model | **`claude-sonnet-5`** (`config.py DEFAULT_MODELS["anthropic"]["judge"]`), unchanged |
| judge `RESPONSE_INSTRUCTION` sha256 | `e5dd7f825008a752c19d4dc77fbec65ed74be9dbfc36c29c2bc9691c9924dd4f` (1439 chars) — the Phase 0 control prompt, **byte-identical**, confirmed at `b5abc6d` |
| judge `judge.py` blob | `2a2a17f16611d4586d122d6e65710f9bd520910f` |
| `evidence_mining.py` blob | `4c951869a1e8c9df7652995e774288282bfe6830` |
| `evidence_mining.py` sha256 | `f38b8e146e126187bfff2afb703d9cbf63eb6dd454b16f9197bd85c99bb06e8f` (6731 bytes, 149 lines) |
| adjudicator version | `adjudication/1` (unmodified) |
| `evidence_mining.py` wired into any runtime path | **no** — not imported by `pipeline.py`, `verdict.py`, `judge.py`, or the CLI as of this registration |

### 1.1 This mechanism never touches the judge

Unlike Registration B, there is no "control vs. intervention prompt" arm here. Every arm
of every phase of this registration runs the identical, unmodified control prompt above.
The independent variable is exclusively whether `evidence_mining.mine_trigger_evidence()`
output is additionally computed and recorded alongside a run — never whether the judge is
asked anything different.

---

## 2. The mechanism (frozen, as implemented at `b5abc6d`)

`mine_trigger_evidence(defect, task_text, code_snapshot) -> dict` reads only:

- the defect's own existing `location` and `fix` free-text fields (already produced by
  the unmodified judge prompt today — nothing new is requested of it), and
- the code snapshot already available to every lens, AST-parsed via
  `adjudication._collect_annotations` / `adjudication._annotation_types` (reused, not
  duplicated).

It fires **only** when:

1. a function parameter is declared with an annotation that resolves to a single,
   non-Optional, simple type (via the existing type-resolution logic — this
   automatically excludes `X | None` / `Optional[X]` and any complex annotation), **and**
2. the defect's own text contains an explicit `(e.g., <literal>)` counter-example aside
   naming that exact parameter, **and**
3. the literal is one of a closed vocabulary, **and**
4. exactly one (parameter, literal) pair is implicated across the whole defect text — any
   second candidate parameter or literal anywhere in the text voids the result.

### 2.1 Closed literal vocabulary — exactly these six spellings

```
None
""
''
[]
{}
0
```

`0` additionally excludes any literal adjacent to another digit or a dot (so `100`,
`10.0`, and a hex literal like `0x7f000001` — the last observed verbatim in a real
`security-04-clean` defect during the offline replay, §7.1 — can never match).

### 2.2 No case-name logic

`evidence_mining.py` contains no case ID, no case-name denylist or allowlist, and no
dataset-specific conditional of any kind. Confirmed by direct inspection: the only two
occurrences of a case name in the file are in comments documenting the provenance of the
two guards in §2.1 and §7.1 above, not in any executable branch. The mechanism generalizes
to any future case whose text happens to match the same structural shape.

### 2.3 What this mechanism does not do

- Does not modify `judge.py`, `RESPONSE_INSTRUCTION`, or any prompt.
- Does not read or write `severity`.
- Does not decide admissibility, blocking authority, or a verdict — it only ever produces
  a candidate `minimal_trigger` string, which the **existing, unmodified**
  `adjudication._adjudicate_trigger` / `admissibility._from_facts` machinery independently
  evaluates, exactly as it already does for judge-supplied evidence.
- Does not widen `DEFECT_KEYS`, `ADJUDICATION_EVIDENCE_KEYS`, or `GROUNDING_ROUTES`. No
  schema change of any kind.

---

## 3. Scope — explicit, and narrower than it might sound

**This mechanism targets `edge_case-02-clean` only.**

- **`security-04-clean` is explicitly out of scope for this registration.** Its dominant
  historical complaint (a data-flow/factual claim about `addresses[0]`) is not a
  declared-parameter-type contradiction, and offline testing confirms the miner produces
  zero hits on it (`tests/test_evidence_mining.py::test_9*`; replay §7). No phase of this
  registration is evaluated on whether `security-04-clean` improves, and no future
  attribution analysis may claim this mechanism affects it.
- **Historical replay suggests partial potential only.** Of `edge_case-02-clean`'s 6
  historical v6 `UNVERIFIED` runs (48, 50, 55, 56, 59, 62), the miner's hit landed on the
  run's actual blocking defect in **2 of 6** (runs 48, 50) — not all 6. **No claim of a
  full fix is made or may be made from this registration.** A best-case, fully successful
  live shadow run demonstrates partial, not complete, coverage of this case's instability.

---

## 4. Frozen variables

Not modified by any phase of this registration:

```
src/engine/verification/judge.py          (RESPONSE_INSTRUCTION, LENSES)
src/engine/eval/dataset.py
src/engine/verification/rubric.py
src/engine/verification/schema.py
src/engine/verification/verdict.py
src/engine/verification/adjudication.py
src/engine/verification/admissibility.py
src/engine/verification/probes.py
src/engine/verification/pipeline.py
src/engine/eval/runner.py
src/engine/runtime/gateway.py
src/engine/runtime/budget.py
src/engine/config.py                      (DEFAULT_MODELS)
```

`pipeline.py` is listed as frozen **through Phase 1**. Wiring
`evidence_mining.mine_trigger_evidence()` into `pipeline.py`'s existing shadow-adjudication
path (`_shadow_adjudications` / `_shadow_record`) so it can even be exercised live is
**separate implementation work, not yet done, and not authorized by this document.** Per
§6, this registration only records what that wiring, once implemented and separately
committed, must satisfy before and during its first live run.

---

## 5. Shadow-only, non-authoritative — every phase, no exception

Every phase of this registration, including its eventual live phase, runs with
`adjudicate=True` **never** set. `admissibility.annotate()` is never called
authoritatively; `merged["defects"]` is never touched; `verdict.gate()` reads raw judge
severity exactly as it does today. The miner's output — once wired — may only ever reach a
**sidecar record** (mirroring `_shadow_adjudications`'s existing shape), never
`verdict.gate()`'s inputs.

**This is stricter than Registration B's own shadow mode**, which was verdict-neutral at
the adjudication layer but still carried full false-pass risk from the *prompt* itself
(§6.1 of that registration). Here there is no prompt to carry that risk: nothing this
mechanism computes can reach a verdict in any phase this registration authorizes, by
construction, not merely by convention.

---

## 6. Phases

| phase | what runs | live? | purpose |
|---|---|---|---|
| **0 — offline replay** | `evidence_mining.mine_trigger_evidence()` over every v6 defect record (runs 48-62, 1146 defects) from a scratchpad copy of `.engine/state.db` | no — zero provider calls | pre-registration safety evidence, already collected (§7) |
| **1 — N=1 live shadow smoke** | one `engine bench` run, current control prompt, with the miner wired into the shadow-adjudication sidecar **only** (separate implementation commit required first) | **yes — one live run** | first live measurement of the mechanism against a fresh judge sample, not just archived text |

No further phase is registered. Whether a Stage 2 (larger N) or an authoritative wiring
is ever proposed requires its **own new registration** — exactly as Registration B's own
rules required for its would-be authoritative phase, and for the same reason: this
document authorizes shadow measurement only.

### 6.1 Before Phase 1 may run

1. The shadow-wiring implementation (miner output → sidecar record only) is written, in
   its own commit, and passes its own offline test suite (ruff, mypy, full pytest).
2. That commit's SHA and the resulting `pipeline.py` diff are recorded in an addendum to
   this document, mirroring Registration B Addendum 02's pattern.
3. Explicit per-turn approval for the specific live run, per `git-safety`.
4. `git-safety` pre-run gate passed: clean tree, recorded `HEAD`, SHA matches this plan.

Analysis of Phase 0 (already complete, §7) does not itself authorize Phase 1. It supplies
the offline evidence that makes proposing Phase 1 responsible; the live run still needs
its own separate approval.

---

## 7. Phase 0 — offline replay (already executed, zero cost, recorded here)

Executed against a scratchpad copy of the production `.engine/state.db`, restricted to v6
runs (48-62) — the only range whose exact historical code/task text this checkout can
reconstruct (`dataset-version boundaries are hard walls`, `baseline-evidence`). Pre-v6
rows (4,434 of 5,580 total defect records) are excluded from mining for this reason, not
mined and not counted below.

| metric | value |
|---|---|
| v6 defects examined | **1,146** (runs 48-62) |
| total miner hits | **10** |
| HIGH/CRITICAL hits | **2** |
| distinct cases hit | **1** — `edge_case-02-clean` only |
| hits on any of the 20 broken cases | **0** |
| `quality-04-broken` hits | **0** |
| `security-03-broken` hits | **0** |
| `edge_case-02-broken` hits | **0** |
| `security-04-broken` hits | **0** |
| `security-04-clean` hits | **0** |
| `edge_case-02-clean` v6 `UNVERIFIED` runs | 6 (runs 48, 50, 55, 56, 59, 62) |
| of those, hit landed on the actual blocking defect | **2** (runs 48, 50) |

### 7.1 The replay caught two precision bugs before any live exposure

The first implementation over-fired on two real, non-target defects: `edge_case-04-broken`
(a genuine bug — a bare numeric range `(0 <= hour <= 23)` with no `e.g.` marker, matched
because the marker was optional) and `security-04-clean` (a hex literal `0x7f000001`
inside a genuine `(e.g., ...)` aside, matched because the zero-literal boundary check only
excluded adjacent digits, not adjacent letters). Both were fixed — `e.g.` is now mandatory,
and the zero literal excludes any adjacent word character — and the corrected version is
what this registration freezes (§1). **This is the central safety argument for proceeding
to a live phase at all**: both flaws were found and fixed with zero spend, against
already-paid-for historical data, before a single live judge call under this mechanism has
ever been made.

---

## 8. Target case and safety controls for Phase 1

| case | role |
|---|---|
| `edge_case-02-clean` | **primary target.** The only case this mechanism is designed to help. |
| `security-04-clean` | **explicit non-target** (§3). Recorded for completeness; no pass/fail criterion depends on it. |
| `quality-04-broken` | **primary safety witness.** Rests on a single blocking defect in every Phase 0 control run; lost it in Registration B's run 62. Categorically outside this mechanism's reach (no declared-parameter-type claim in its text — `tests/test_admissibility.py::test_9b`). |
| `security-03-broken` | sole blocker in every control run (`tests/test_admissibility.py::test_6c`). |
| `edge_case-02-broken` | must remain blocked (`tests/test_admissibility.py::test_5`, `test_5b`). |
| `security-04-broken` | must remain blocked (`tests/test_admissibility.py::test_7`). |

---

## 9. STOP rules — absolute, evaluated before any success metric

Any one of these firing in Phase 1 ends the registration immediately. None can be waived
or reversed by a subsequent attribution analysis, for the same reason Registration B's
own §12 rules could not be.

1. **Any `false_pass > 0` in the actual (non-shadow) verdict.** Zero tolerance. Since
   `adjudicate=True` is never set, this rule is not expected to be reachable by the
   mechanism itself — its presence here is a direct safety-net check that the wiring
   commit (§6.1) did not accidentally make the shadow path authoritative.
2. **`quality-04-broken` blocker loss** — any fall in its blocking (CRITICAL/HIGH) defect
   count in the actual verdict.
3. **`security-03-broken` sole-blocker loss** — any loss of its blocking severity in the
   actual verdict.
4. **`edge_case-02-broken` no longer blocked** in the actual verdict.
5. **`security-04-broken` no longer blocked** in the actual verdict.
6. **Any miner hit on any of the 20 broken cases**, in the shadow-only sidecar record —
   even though it cannot reach the verdict in this phase, a live hit on a broken case
   the offline replay never produced is itself a REJECT signal requiring the mechanism to
   be re-examined before any further phase.
7. **Any change to judge prompt content or severity distribution attributable to this
   implementation.** Since no prompt file is touched, this is a construction check: if a
   live run under this registration ever shows an altered `RESPONSE_INSTRUCTION` hash or a
   severity distribution shift, the wiring commit itself is defective (e.g., an accidental
   import-time side effect) and the registration is void pending investigation.

---

## 10. Success criteria for the shadow phase

**Success here means "safe to consider a future authoritative registration," not "this
mechanism works."** All of the following, evaluated only after no §9 rule has fired:

1. Zero false passes in the actual verdict (restates §9.1 as a positive criterion).
2. Zero miner hits on any of the 20 broken cases, in the shadow sidecar (restates §9.6).
3. `quality-04-broken` blocking defect count preserved exactly.
4. `security-03-broken` sole blocker preserved.
5. `edge_case-02-broken` preserved, fully blocked.
6. `security-04-broken` preserved, fully blocked.
7. **At least one meaningful `edge_case-02-clean` finding is mined and shadow-adjudicated
   to a non-`fail-closed-unresolved` rule** (i.e., the offline-predicted mechanism
   actually fires on a fresh, live judge sample, not only on archived text).
8. No evidence of broad overmatching: the shadow sidecar's hit count and distribution for
   this one live run stay in the same order of magnitude and on the same case as the
   offline replay predicts — a sudden broad spread across many cases is itself a signal
   to stop and investigate before proposing anything further, even without a formal
   numeric threshold at N=1.

**`security-04-clean` improvement is explicitly not required and not evaluated** (§3).

Meeting all eight criteria authorizes **nothing beyond recording the result and
considering whether a larger-N shadow phase or a future authoritative registration is
worth proposing** — exactly as Registration B's own ACCEPT criteria never authorized more
than "continued shadow capture."

---

## 11. Anti-post-hoc rules

- Decision rules are written above, before any live run exists, and are never edited
  afterward.
- The closed vocabulary (§2.1), the `e.g.`-mandatory rule, and the STOP/success criteria
  (§9-10) are fixed now.
- No metric added after seeing live data and presented as the endpoint.
- A negative or null result (mechanism fires on nothing live, or fires unsafely) is
  recorded with the same weight as a positive one.
- **One change per experiment.** No dataset, schema, rubric, or judge-prompt change may be
  bundled with any phase of this registration.

---

## 12. Cost ceiling

Phase 1 is exactly one `engine bench --shadow-adjudicate`-class run at the existing,
unmodified control prompt and dataset v6 — same cost profile as any Phase 0 control run
under Registration B (~$0.51-0.78 per run, BASELINE.md). **Hard stop-loss: $2.00** for this
registration's Phase 1 (a single run, generously bounded). Reaching it halts the phase,
recorded as INCOMPLETE.

---

## 13. Provenance

- Registered: 2026-09-12
- Base SHA: `b5abc6dfb48f46353955a505adae2779f0ecd3d5`
- `evidence_mining.py` sha256: `f38b8e146e126187bfff2afb703d9cbf63eb6dd454b16f9197bd85c99bb06e8f`
- Offline review that produced this design: full v6 historical replay (1,146 defects,
  §7); two precision bugs found and fixed before any live exposure; two new safety
  regression tests added (`tests/test_admissibility.py::test_9b`, `::test_6c`) proving the
  real Phase 0 `quality-04-broken` HIGH shape and `security-03-broken`'s sole blocker
  survive the actual (unmodified) admissibility decision path with zero evidence supplied.
  No model call, no benchmark run, no spend.
- Runs executed against this registration at time of writing: **none.**
