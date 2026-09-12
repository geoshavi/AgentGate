# Combined Contract Evidence Mining Shadow Registration — Addendum 01: Wiring Provenance

**Type: provenance only.** This addendum records the shadow-wiring implementation SHA and
its measured-path hashes now that they exist. It changes **no** hypothesis, metric,
threshold, decision rule, frozen variable, phase, or cost ceiling.
`COMBINED_CONTRACT_EVIDENCE_MINING_SHADOW_REGISTRATION.md` is not edited and remains valid
exactly as written.

**This addendum records provenance only. It does not authorize a live run by itself, and
it does not authorize authoritative suppression.** No live run has executed against this
registration at the time of writing.

---

## 1. Why this addendum exists

The registration was frozen at `5a7c9f8` before the shadow-wiring implementation existed.
That implementation now exists, in its own commit, on top of the registration's parent
chain. This document supplies the required link between the frozen registration and the
exact code that would execute if a future live shadow run is separately authorized.

---

## 2. SHAs

| role | SHA |
|---|---|
| implementation commit | `4350a9f6606e49c9708de2b17860ad6310cea346` |
| parent commit | `88368d8e44891d4a3c3e6d1ebf1d78f1b4486d36` |

Files changed in the wiring commit (verified via `git diff-tree --no-commit-id --name-only
-r HEAD`):

- `src/engine/verification/pipeline.py`
- `tests/test_shadow_adjudication.py`

---

## 3. Measured-path hashes

Computed directly against the committed `HEAD` blob, not the working tree.

| item | value |
|---|---|
| `pipeline.py` git blob | `0e4e0c906d7a08595f1142a20552a5a91457496f` |
| `pipeline.py` sha256 | `4aa24795e4a1cfb52c72b6f134ab79e922501f243d0d1e385b4e39983d504b1` |
| `pipeline.py` size | 9815 bytes |
| `evidence_mining.py` git blob | `3b6d69806d9d21cdf97c01e6a4701f8a885ae81b` — **unchanged** from the value frozen in the registration's §2; the wiring commit did not touch it |
| `evidence_mining.py` sha256 | `68f317d0766aaccfe09f9c43af782baee2e5bd8fbf46ec6c2cd4724986f726c8` — matches registration §2 exactly |
| `evidence_mining.py` size | 12097 bytes — matches registration §2 exactly |
| control `RESPONSE_INSTRUCTION` sha256 | `e5dd7f825008a752c19d4dc77fbec65ed74be9dbfc36c29c2bc9691c9924dd4f` |
| control `RESPONSE_INSTRUCTION` length | 1439 chars |

Re-verified for this addendum, directly against the committed `HEAD` blob: `git ls-tree
HEAD` blob SHAs, a direct sha256 of file bytes read from disk at `HEAD` (clean tree, no
working-tree divergence), and `hashlib.sha256(RESPONSE_INSTRUCTION.encode()).hexdigest()`
imported live from `judge.py` all match the values above exactly.

---

## 4. Exact shadow wiring scope

- Original defects stay in `merged["defects"]`; `verdict.gate()` continues reading only
  this original list, unaugmented.
- The shadow path operates on a **throwaway copy** of the defects, never the original list
  or object.
- Evidence precedence within the shadow path: judge-supplied `minimal_trigger` first, then
  Route A (`mine_trigger_evidence`), then Route B (`mine_return_value_evidence`), then no
  mined evidence.
- A **dual Route A + Route B match fails closed**: no mined evidence is produced when both
  routes hit on the same defect.
- Only the throwaway copy is passed through `admissibility.adjudication_record()`. This
  call is never made against the original defects.
- The result is written only to the `shadow_adjudications` sidecar structure — never merged
  back into `merged["defects"]` and never read by `verdict.gate()`.

---

## 5. Offline replay (re-verified for this addendum)

- Route A: **10 total hits, 2 blocking** — runs 48 and 50.
- Route B: **7 total hits, 3 blocking** — runs 55, 59, and 62.
- Combined, the two routes cover **all 5** genuine `edge_case-02-clean` blocker runs.
- **Overlap = 0** — no defect record is hit by both routes.
- **Broken-case hits = 0** across all routes.
- **Broken-case shadow suppressions = 0.**
- **Run 56 remains VOID** — neither route produces mined evidence for it; this addendum
  does not change that.

---

## 6. Validation (re-verified for this addendum)

- Targeted tests: **109/109 passed.**
- Shadow tests: **38 passed** (within the targeted total).
- Full pytest: **1847 passed, 3 skipped.**
- Ruff: clean.
- mypy: clean (138 source files).

---

## 7. Production database — unchanged

| item | value |
|---|---|
| sha256 | `de184e5e81519bba9540def11cffcb38476e4df53e305c5eaeb92bd44a58cb` |
| size | 5,074,944 bytes |
| `eval_runs` rows | 63 |
| adjudication rows (`eval_case_defect_adjudications`) | 495 |
| `PRAGMA integrity_check` | `ok` |
| WAL/SHM files present | none |

Re-verified directly against `.engine/state.db` on disk immediately before writing this
document. No benchmark run, provider call, or write touched this file to produce these
figures.

---

## 8. What this addendum does not do

- Does not alter the hypothesis, frozen variables, STOP rules, or success criteria in
  `COMBINED_CONTRACT_EVIDENCE_MINING_SHADOW_REGISTRATION.md`.
- Does not authorize authoritative suppression. `adjudicate=True` remains untouched and
  unused by the wiring this addendum describes; the shadow path writes only to the sidecar
  (§4).
- Does not authorize a paid live run. The experiment becomes ready for a live shadow run
  only once that run receives its own, separate, explicit per-turn authorization and a
  passing `git-safety` pre-run gate against whatever commit is current at that time.

---

## 9. Provenance

- Written: 2026-09-12, before any live run under this registration exists.
- Registration commit: `5a7c9f8a2e68d3c3e206028a1b646dffaffc5332`.
- Wiring implementation commit: `4350a9f6606e49c9708de2b17860ad6310cea346`, parent
  `88368d8e44891d4a3c3e6d1ebf1d78f1b4486d36`.
- Runs executed against this registration at time of writing: **none.**
- No benchmark run, no provider call, no spend produced this document.
