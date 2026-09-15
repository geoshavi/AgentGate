# Combined Contract Evidence Mining Shadow Registration — Addendum 02: Run 64 and Freeze

**Type: run record + status freeze.** This addendum records the one N=1 live shadow run
authorized and executed under this registration, and freezes the experiment's status based
on that run. It changes **no** hypothesis, metric, threshold, decision rule, frozen
variable, or cost ceiling in
`COMBINED_CONTRACT_EVIDENCE_MINING_SHADOW_REGISTRATION.md`, which is not edited and remains
valid exactly as written.

**This is the only live run executed against this registration. No further live run is
authorized by this document.**

---

## 1. Run 64

| item | value |
|---|---|
| run_id | 64 |
| stamped git commit SHA | `d72f1d080cc7c76f23701bc2702f9bfe1635fd72` |
| correct verdicts | 39/40 (97.5%) |
| false_pass | 0 |
| false_unverified | 1 — `security-04-clean`, already classified as a v6 benchmark limitation (see §7) |
| schema failures | 1 — `security-04-clean` / `correctness` lens, the same known limitation |
| cost | $0.736284 |

Mining outcome, this run only (not the historical replay recorded in the registration's
§4):

| item | value |
|---|---|
| Route A hits | 0 |
| Route B hits | 2, both MEDIUM severity, both on `edge_case-02-clean` |
| blocking miner hits | 0 |
| Route A/B overlap | 0 |
| broken-case miner hits | 0 |
| broken-case shadow suppressions | 0 |

All four named safety controls (`quality-04-broken`, `security-03-broken`,
`edge_case-02-broken`, `security-04-broken`) preserved their blockers. The actual verdict
path remained neutral: `merged["defects"]` was never touched by the shadow branch, and
`verdict.gate()` read only the original, unaugmented defects, exactly as designed in the
wiring recorded in Addendum 01.

No STOP rule from the registration's §6 fired.

---

## 2. Final experiment status

| axis | status |
|---|---|
| Offline efficacy | strong |
| Historical target coverage | 5/5 genuine `edge_case-02-clean` blocker runs |
| Live safety | demonstrated |
| Live blocking-efficacy | inconclusive |
| Authoritative suppression | disabled |
| Decision | **freeze as safe shadow prototype** |

Live blocking-efficacy is inconclusive, not negative: Run 64's two Route B hits landed on
non-blocking MEDIUM-severity defects because `edge_case-02-clean` did not produce a false
CRITICAL/HIGH block in this sample. The mechanism was never exercised against a live
blocking scenario, so no live efficacy claim follows from this run — only a safety claim
(zero contamination, zero suppression, structurally inert on the authoritative path).

**No further random paid validation** is planned under this registration.

---

## 3. Explicit statements

- `edge_case-02-clean` is **not** claimed fully fixed. Offline replay shows the mechanism
  covers all 5 of its historical genuine blocker runs; Run 64 did not exercise a live
  blocking instance of it at all.
- **No authoritative rollout is authorized.** `adjudicate=True` remains untouched and
  unused by anything this registration or its addenda added.
- If authoritative use is reconsidered later, it should use a **targeted validation** that
  deliberately exercises a blocking Route A or Route B condition, rather than another
  random full-dataset run — Run 64 shows that a random N=1 run is not guaranteed to
  encounter the condition this mechanism exists to address.
- `security-04-clean` remains deferred as a v6 dataset/spec limitation, unrelated to this
  registration's scope (registration §8) and unaffected by this run.

---

## 4. Post-run database state

| item | value |
|---|---|
| eval_runs | 64 |
| adjudications (`eval_case_defect_adjudications`) | 583 |
| sha256 | `f845f8db1b189f6e48b820437f233ec1f3c60fc60fc7836eb293e6279d52016c` |
| size | 5,222,400 bytes |
| `PRAGMA integrity_check` | ok |
| WAL/SHM present | none |

---

## 5. What this addendum does not do

- Does not alter the hypothesis, frozen variables, STOP rules, or success criteria in
  `COMBINED_CONTRACT_EVIDENCE_MINING_SHADOW_REGISTRATION.md`.
- Does not authorize any further live run under this registration.
- Does not enable authoritative suppression.
- Does not claim `edge_case-02-clean` is fixed, only that the shadow mechanism proved safe
  under one live sample.

---

## 6. Provenance

- Written: 2026-09-12, immediately after Run 64, no source/test/dataset/prompt/verdict/
  admissibility change and no benchmark or provider call made in producing this document.
- Registration commit: `5a7c9f8a2e68d3c3e206028a1b646dffaffc5332`.
- Wiring implementation commit: `4350a9f6606e49c9708de2b17860ad6310cea346`.
- Addendum 01 commit: `d72f1d080cc7c76f23701bc2702f9bfe1635fd72`.
- Runs executed against this registration: **one — Run 64.** No further run is planned.
