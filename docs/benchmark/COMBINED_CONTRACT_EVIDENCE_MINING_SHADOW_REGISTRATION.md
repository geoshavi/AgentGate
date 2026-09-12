# Combined Contract Evidence Mining — Shadow Registration

**Status: REGISTERED, FROZEN. No live run has been executed against it.**

Pre-registered per `.claude/skills/experiment-design`. This is a **new, independent
registration** covering both deterministic evidence-mining routes together, before any
runtime wiring or live validation of either. It does not reopen, amend, or supersede
`CONTRACT_EVIDENCE_MINING_SHADOW_REGISTRATION.md` (the single-miner registration, still
valid as written — the run 63 shadow smoke it authorized already exists and is not
affected by this document) or `EVIDENCE_CAPTURE_PROMPT_REGISTRATION_B.md` (REJECTED and
CLOSED, unrelated mechanism — Registration B asked the judge for evidence; both routes
here ask the judge for nothing).

---

## 0. What this experiment is, in one sentence

Freeze, together, the two deterministic, judge-prompt-neutral evidence routes that between
them offline-cover every genuine historical `edge_case-02-clean` blocking failure — and
measure, in a single future non-authoritative live shadow run, whether a live judge sample
produces text either route can safely recognize, without ever letting a verdict change in
this phase.

---

## 1. Registration scope — exactly two routes

### Route A — declared-parameter-type evidence (unchanged from the prior single-miner registration)

- **Function:** `evidence_mining.mine_trigger_evidence(defect, task_text, code_snapshot)`
- **Adjudication path:** `adjudication._adjudicate_trigger` → `admissibility._from_facts`
  → rule `declared-interface`
- **Historical blocking coverage (v6 replay):** runs **48, 50**

### Route B — declared-return-type evidence (new this registration)

- **Function:** `evidence_mining.mine_return_value_evidence(defect, task_text, code_snapshot)`
- **Adjudication path:** `adjudication._adjudicate_return` → `admissibility._from_facts`
  → rule `factual-premise`
- **Historical blocking coverage (v6 replay):** runs **55, 59, 62**

### Properties both routes share, frozen together

- Both operate **deterministically** from the defect's own `location`/`fix` text plus the
  code snapshot and, where relevant, the AST-derived declared type annotations already
  available to every lens — **neither route reads or depends on the other's output.**
- Both emit **only** `minimal_trigger`-shaped evidence (`{"minimal_trigger": "<expr>"}`) —
  no new evidence key, no schema change, no widening of `ADJUDICATION_EVIDENCE_KEYS`.
- **Neither route ever changes severity or a verdict directly.** Evidence only ever reaches
  the *existing, unmodified* `adjudication.py` / `admissibility.py` machinery, which alone
  decides `admissible_to_block`.
- **Original defect objects are authoritative and untouched.** Any annotation happens on a
  throwaway copy built solely for a sidecar record — this registration authorizes no
  wiring that could do otherwise (§5).
- Neither route touches `judge.py`, `RESPONSE_INSTRUCTION`, `rubric.py`, `schema.py`,
  `verdict.py`, `adjudication.py`, or `admissibility.py`. Both are pure, additive functions
  in `src/engine/verification/evidence_mining.py`.

---

## 2. Frozen implementation provenance

Computed directly against the committed `HEAD` blob, not the working tree and not taken on
faith from any prior turn's report.

| item | value |
|---|---|
| implementation commit | `5a7c9f8a2e68d3c3e206028a1b646dffaffc5332` |
| parent commit | `0fcd54b17b47264f2c0506fdd3f2962a36fb8db2` |
| `evidence_mining.py` git blob | `3b6d69806d9d21cdf97c01e6a4701f8a885ae81b` |
| `evidence_mining.py` sha256 | `68f317d0766aaccfe09f9c43af782baee2e5bd8fbf46ec6c2cd4724986f726c8` |
| `evidence_mining.py` size | 12097 bytes |
| `tests/test_evidence_mining.py` git blob | `2aff10170de76ed3bb55f3c1a06f851d8cb9451c` |
| Route A function | `mine_trigger_evidence` (`evidence_mining.py:94`) |
| Route B function | `mine_return_value_evidence` (`evidence_mining.py:234`) |
| Route B private helpers | `_statements_in_own_scope` (:179), `_return_none_ifexp_candidates` (:191) |
| Route A private helper | `_candidate_parameters` (:70) |
| `judge.py` blob (unchanged, reconfirmed) | `2a2a17f16611d4586d122d6e65710f9bd520910f` |

---

## 3. Control prompt — verified unchanged

| item | value |
|---|---|
| `RESPONSE_INSTRUCTION` sha256 | `e5dd7f825008a752c19d4dc77fbec65ed74be9dbfc36c29c2bc9691c9924dd4f` |
| `RESPONSE_INSTRUCTION` length | 1439 chars |
| dataset version | v6 |
| judge model | `claude-sonnet-5` |

Re-verified at `5a7c9f8` before writing this document: hash and length match exactly. Per
§6 of this registration, the whole experiment is void if this ever changes.

---

## 4. Offline evidence (measured, not projected, except where marked)

Full v6 historical replay, 1228 defect records, runs 48–63 (restricted to v6, the only
range whose code/task text this checkout reconstructs exactly — the same dataset-version
boundary every prior registration in this series has observed).

| metric | value |
|---|---|
| Route A total hits | 10 |
| Route A blocking hits | 2 (runs 48, 50) |
| Route B total hits | 7 |
| Route B blocking hits | 3 (runs 55, 59, 62) |
| Combined: distinct `edge_case-02-clean` blocking runs covered | **5 of 5** — every genuine historical `UNVERIFIED` run |
| Run 56 | **excluded as VOID** (`eval_case_results.error` — API credit exhaustion, the same class as the run-56/run-43 precedent already recorded in `BASELINE.md`) — not a defect-driven failure, not counted toward or against either route |
| Broken-case hits (either route, all 20 cases, all v6 runs) | **0** |
| Overlap / double-hit between routes on any record | **0** |
| Projected `edge_case-02-clean` valid-run result if both routes were authoritative | **14/14** (100%), computed by a read-only replay feeding mined evidence through the real, unmodified `admissibility.decide()` — no DB write |
| Projected false-pass count across every v6 broken-case run, same method | **0** |

Offline validation at the implementation commit: `tests/test_evidence_mining.py` 32/32;
combined with `test_admissibility.py` + `test_shadow_adjudication.py`: 103/103; full
suite 1841 passed, 3 skipped, 0 failed; Ruff clean; mypy clean (138 source files). No
provider or API call produced any of this evidence.

---

## 5. Shadow-only hypothesis for the next runtime phase

**Hypothesis (falsifiable):** the combined deterministic evidence miners can recover
enough contract evidence from a *live* judge's defect text to correctly classify
`edge_case-02-clean`'s blocking defects — via the existing, frozen admissibility
pipeline — without changing the real verdict path and without touching any broken-case
blocker, anywhere in the dataset.

**This document does not authorize that phase.** It freezes what any future
shadow-wiring implementation must satisfy before its own live run, exactly as
`CONTRACT_EVIDENCE_MINING_SHADOW_REGISTRATION.md` did for Route A alone. Wiring
`mine_return_value_evidence` into the shadow sidecar (mirroring how Route A was wired in
commit `8add6cd`) is separate, not-yet-authorized implementation work.

Once wired, the shadow-only sidecar may record:
- which route(s), if any, mined evidence for a given defect
- the resulting `admissibility.decide()` conclusion (rule, `admissible_to_block`)
- the hypothetical suppression that conclusion implies

But structurally, in every phase this registration ever authorizes:
- `verdict.gate()` continues reading the original, unaugmented `merged["defects"]`
- no authoritative suppression of any kind
- no severity change, ever
- no judge prompt change, ever

---

## 6. Absolute STOP rules — frozen for any future live phase

Any one of these firing ends the phase immediately, with no waiver and no reversal by
subsequent attribution analysis — the same asymmetry every prior registration in this
series has fixed in advance, precisely so it cannot be argued away once it fires.

1. **`false_pass > 0`** in the actual (non-shadow) verdict.
2. **Any miner hit — either route — on any of the 20 broken cases.**
3. **Any hypothetical/shadow suppression on any broken case** (an `admissible_to_block =
   False` shadow record on a broken-case defect), even though it cannot reach the verdict
   in shadow mode — a live hit the offline replay never produced is itself a REJECT
   signal requiring re-examination before any further phase.
4. **`quality-04-broken` loses its blocker.**
5. **`security-03-broken` loses its sole blocker.**
6. **`edge_case-02-broken` stops blocking.**
7. **`security-04-broken` stops blocking.**
8. **The control prompt hash changes** (§3's value) — a construction check: neither route
   touches the prompt, so any drift means the wiring itself is defective.
9. **The dataset version changes.**
10. **The judge model changes unexpectedly** (i.e., not as part of a separately approved,
    separately registered change).
11. **Either evidence miner alters an original defect object** — checked structurally
    (`merged["defects"]` byte-identical before/after), not merely assumed safe because the
    functions are "supposed to" be pure.
12. **The authoritative verdict path changes in any way** attributable to this
    experiment's wiring.
13. **Schema-failure behavior is worsened** — any increase in schema failures per run
    attributable to the wiring (there should be none: neither route touches the judge or
    the parser).
14. **Unexpected overlap/double-hit creates ambiguous evidence** — e.g., both routes
    firing on the same defect with different `minimal_trigger` values, or one route's
    output interfering with the other's input. Measured at 0 in the full v6 offline
    replay (§4); any live occurrence is a REJECT signal, not a tiebreak to resolve
    on the fly.

**No retry after a STOP result without a new registration.**

---

## 7. Success criteria for a future N=1 live shadow run

All of the following, evaluated only after no §6 rule has fired:

1. `false_pass = 0`.
2. Zero broken-case miner hits (either route).
3. Zero broken-case shadow suppressions.
4. All four safety controls (`quality-04-broken`, `security-03-broken`,
   `edge_case-02-broken`, `security-04-broken`) preserved, fully blocked.
5. **At least one live miner hit on `edge_case-02-clean`, if and only if the judge emits a
   historically-covered blocking pattern that run.** A run where the judge doesn't emit
   either pattern is not a failure of this criterion — see the explicit note below.
6. Any mined evidence on a target blocker resolves, through the existing unmodified
   admissibility logic, to the expected `factual-premise` / `declared-interface` rule —
   not to an unexpected rule, and not to `fail-closed-unresolved` (which would mean the
   mining fired but the adjudicator still couldn't act on it — a wiring bug, not a
   negative result).
7. The actual verdict path is neutral — `merged["defects"]` and `verdict.gate()`'s
   result are unaffected by either miner's presence, exactly as the single-Route-A shadow
   run already proved for Route A alone.
8. No prompt, severity, or dataset mutation of any kind.

**Explicit, important note (carried forward from the prior registration's own caution):**
a run where `edge_case-02-clean` is already `OK` and neither route fires is **SAFE but
efficacy-inconclusive** — it is not a failure, and it is not positive evidence either.
Given the case's measured historical instability (9 of 14 valid v6 runs already land on
`OK` without any mechanism), a single N=1 live run has a real chance of landing on exactly
this uninformative outcome, exactly as run 63 did for Route A alone. **No claim that
`edge_case-02-clean` is "fixed" may be made from a single run, or from this registration,
under any outcome.**

---

## 8. `security-04-clean` — explicitly excluded

**`security-04-clean` is not part of this experiment, in any respect.** It is closed —
per `BASELINE.md`'s dedicated entry — as a v6 dataset/spec-precision limitation and
deferred to a future v7 revision (task-text coverage-standard clarification plus a CGNAT
fixture fix, bundled together if v7 is ever opened for independent reasons). **No rule,
metric, or success criterion in this registration may be justified, tuned, or evaluated
by reference to `security-04-clean`.** Both routes were independently confirmed to mine
zero evidence on it (§4); that is recorded as a broken/non-target-case safety fact, not as
progress toward solving it.

---

## 9. Frozen variables

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
src/engine/verification/pipeline.py        (through this registration's Phase 0; wiring is separate, later work)
src/engine/eval/runner.py
src/engine/runtime/gateway.py
src/engine/runtime/budget.py
src/engine/config.py                       (DEFAULT_MODELS)
```

---

## 10. Anti-post-hoc rules

- Decision rules are written above, before any live run under this combined registration
  exists, and are never edited afterward.
- The STOP rules (§6) and success criteria (§7) are fixed now.
- No metric added after seeing live data and presented as the endpoint.
- A negative or null result (neither route fires live, or either fires unsafely) is
  recorded with the same weight as a positive one.
- **One change per experiment.** No dataset, schema, rubric, or judge-prompt change may
  be bundled with any phase of this registration.
- Extension rules must be pre-registered to be legitimate; none is pre-registered here.

---

## 11. Provenance

- Registered: 2026-09-12
- Implementation commit: `5a7c9f8a2e68d3c3e206028a1b646dffaffc5332`, parent
  `0fcd54b17b47264f2c0506fdd3f2962a36fb8db2`
- Offline review that produced this design: full v6 historical replay across both routes
  (1228 defect records); zero overlap; zero broken-case hits from either route; a
  read-only theoretical verdict replay through the real `admissibility.decide()`
  projecting 14/14 on `edge_case-02-clean` and 0 false passes on every broken case. No
  model call, no benchmark run, no spend.
- Runs executed against this registration at time of writing: **none.**
