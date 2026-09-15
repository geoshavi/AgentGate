# Contract Evidence Mining Shadow Registration — Addendum 01: Wiring Provenance

**Type: provenance only.** This addendum records the shadow-wiring implementation SHA and
its measured-path hashes now that they exist, as required by
`CONTRACT_EVIDENCE_MINING_SHADOW_REGISTRATION.md` §6.1. It changes **no** hypothesis,
metric, threshold, decision rule, frozen variable, phase, or cost ceiling.
`CONTRACT_EVIDENCE_MINING_SHADOW_REGISTRATION.md` is not edited and remains valid exactly
as written.

**This addendum records provenance only. It does not authorize a live run by itself, and
it does not claim efficacy or safety beyond what offline validation has shown.** No live
run has executed against this registration at the time of writing.

---

## 1. Why this addendum exists

The registration's §6.1 lists what must be true before Phase 1 may run: the shadow-wiring
implementation written in its own commit, passing its own offline test suite (item 1), and
that commit's SHA and resulting `pipeline.py` diff recorded in an addendum to the
registration (item 2). That implementation now exists at commit `8add6cd`. This document
supplies the required link between the frozen registration and the exact code that would
execute if Phase 1 is separately authorized.

---

## 2. SHAs

| role | SHA |
|---|---|
| registration / base SHA | `b9d16412e33747595283872de45b23140402cfef` |
| wiring implementation SHA | `8add6cd575a576218fecac25b9e66c2fb94a3cbd` |
| parent of the wiring implementation commit | `b9d16412e33747595283872de45b23140402cfef` |

The wiring implementation commit's parent **is** the registration/base SHA: nothing else
landed between the registration being frozen and the wiring being implemented. The
executable configuration a live Phase 1 run would be stamped with is `8add6cd`.

---

## 3. Measured-path hashes

| item | value |
|---|---|
| `pipeline.py` blob | `ece021e0e2b57cdc617fc6aeb78c3507935d1770` |
| `pipeline.py` sha256 | `9a2b5b3815015cad2fbd040925cacc050f1574af9d892dcc30e1e2d4f6a34936` |
| `pipeline.py` size | 7710 bytes |
| `evidence_mining.py` blob | `4c951869a1e8c9df7652995e774288282bfe6830` — **unchanged** from the frozen prototype recorded in the registration (§1); no rule, vocabulary, or matching logic was touched by the wiring commit |
| control `RESPONSE_INSTRUCTION` sha256 | `e5dd7f825008a752c19d4dc77fbec65ed74be9dbfc36c29c2bc9691c9924dd4f` |
| control `RESPONSE_INSTRUCTION` length | 1439 chars — **unchanged**, re-verified at `8add6cd` |

Re-verified for this addendum, directly against the committed `HEAD` blob (not the working
tree): `git hash-object src/engine/verification/pipeline.py` and a direct sha256 of its
bytes both match the table above exactly; `git hash-object
src/engine/verification/evidence_mining.py` matches the registration's frozen value
unchanged; `hashlib.sha256(RESPONSE_INSTRUCTION.encode()).hexdigest()` matches the control
value unchanged.

---

## 4. Exact wiring scope

- Mining occurs **only** inside shadow-record construction (`pipeline._shadow_record`, via
  the new `pipeline._with_mined_evidence` helper). No other function was touched.
- `merged["defects"]` — the list `verdict.gate()` reads — is **never** copied, mutated, or
  replaced by this wiring. `_shadow_adjudications` still iterates the exact same original
  list it always has.
- `verdict.gate()` continues reading the original, unaugmented defects exactly as before
  this commit; its own source is untouched.
- The mined evidence reaches only a **sidecar** structure: one entry in
  `merged["shadow_adjudications"]`, itself already non-authoritative
  (`tests/test_shadow_adjudication.py`'s entire pre-existing suite, 24 tests, passes
  unmodified with this wiring in place).
- **No authoritative admissibility.** `adjudicate=True` is untouched by this commit and
  unused by anything it added.
- **No severity mutation.** `evidence_mining.mine_trigger_evidence` and
  `admissibility.adjudication_record` both remain severity-blind, as they were before this
  wiring existed.
- **No prompt change.** `judge.py` and `RESPONSE_INSTRUCTION` are untouched (§3).

---

## 5. Offline validation (re-stated from the implementation turn, re-verified here)

- Full pytest: **1823 passed, 3 skipped**, 0 failed.
- Ruff: clean.
- mypy: clean (138 source files).
- Historical replay of the wired path against **1146 v6 defect records** (runs 48-62):
  - **10 miner hits, all on `edge_case-02-clean`.**
  - **2 shadow suppressions** (`admissible_to_block = False`), both on `edge_case-02-clean`,
    **runs 48 and 50** — the only two of its six historical `UNVERIFIED` v6 runs where the
    mined trigger landed on the case's actual blocking defect.
  - **0 hits and 0 suppressions on all 20 broken cases**, including all four named safety
    controls (`quality-04-broken`, `security-03-broken`, `edge_case-02-broken`,
    `security-04-broken`).

---

## 6. Unresolved scope — restated, not narrowed

- **`security-04-clean` remains unsolved by this mechanism.** Zero hits in the replay, as
  designed and as registered (§3 of the registration). No phase of this registration is
  evaluated on whether it improves.
- **This is not a claim of a full `edge_case-02-clean` fix.** The replay shows the
  mechanism would have affected 2 of its 6 historical `UNVERIFIED` v6 runs — partial
  potential only, exactly as §3 and §7 of the registration state. Nothing in the wiring
  implementation or this addendum changes that scope.

---

## 7. Live Phase 1 rules — unchanged, restated for reference

- First live run is **N=1**.
- **Shadow-only.** `adjudicate=True` is not set by anything this addendum or the wiring
  commit added; no phase this registration authorizes may set it.
- **No authoritative verdict changes.** The wiring's own construction (§4) makes this
  structural, not merely a rule to follow.
- **All STOP and success-criteria rules from the registration (§9, §10) apply unchanged**:
  any `false_pass > 0`, any loss of `quality-04-broken`'s blocker, any loss of
  `security-03-broken`'s sole blocker, `edge_case-02-broken` or `security-04-broken` no
  longer blocked, any miner hit on any broken case, or any prompt/severity change
  attributable to this implementation are each independently an immediate REJECT.
- **The live run still requires its own separate, explicit per-turn authorization** and a
  passing `git-safety` pre-run gate (clean tree, recorded `HEAD` matching `8add6cd` or
  whatever commit is current at that time, SHA matching this addendum). Nothing in this
  document authorizes that run.

---

## 8. What this addendum does not do

- Does not alter the hypothesis, the closed literal vocabulary, the STOP rules, the
  success criteria, or the cost ceiling in
  `CONTRACT_EVIDENCE_MINING_SHADOW_REGISTRATION.md`.
- Does not authorize Phase 1. Every future live run under this registration needs its own
  per-turn approval and a passing pre-run gate, exactly as §6.1 states.
- Does not claim the mechanism is effective, safe under live judge sampling, or complete.
  Offline replay against archived text is not the same measurement as a live run against a
  fresh judge sample — that is precisely what Phase 1, once separately authorized, exists
  to check.

---

## 9. Provenance

- Written: 2026-09-12, before any live run under this registration exists.
- Registration commit: `b9d16412e33747595283872de45b23140402cfef`.
- Wiring implementation commit: `8add6cd575a576218fecac25b9e66c2fb94a3cbd`, parent
  `b9d16412e33747595283872de45b23140402cfef`.
- Runs executed against this registration at time of writing: **none.**
- No benchmark run, no provider call, no spend produced this document.
