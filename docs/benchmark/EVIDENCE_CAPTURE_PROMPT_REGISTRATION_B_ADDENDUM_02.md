# Registration B — Addendum 02: Intervention Provenance

**Type: provenance only.** This addendum records the intervention SHA and its
`RESPONSE_INSTRUCTION` hash now that they exist, as required by
`EVIDENCE_CAPTURE_PROMPT_REGISTRATION_B.md` §16.5. It changes **no** hypothesis, metric,
threshold, decision rule, frozen variable, phase, or cost ceiling.
`EVIDENCE_CAPTURE_PROMPT_REGISTRATION_B.md` is not edited and remains valid exactly as
written; nor is Addendum 01.

If any decision rule ever needs to change, that is a **new registration**, not an addendum.

This document **records provenance only. It does not claim the intervention is effective or
safe.** That remains to be established by Phase 1 live shadow validation — no live run has
executed against this intervention at the time of writing.

---

## 1. Why this addendum exists

Registration B §16 lists what must be true before Phase 1 may run. §16.6 (Phase 0's control
figures in BASELINE.md) was satisfied first and is re-confirmed in §2 below. §16.4 (the
intervention implemented in its own commit) and §16.5 (that commit's SHA and prompt hash
recorded here) are satisfied by the commit this addendum documents. Leaving either
unrecorded is the precise failure mode this repository's discipline exists to prevent: a run
is only interpretable if the exact code and prompt that produced it are identified in
advance, not reconstructed after the fact.

---

## 2. Control arm (Phase 0 — unchanged, restated for reference)

| item | value |
|---|---|
| executable SHA | `44ef7a4785d58b4da7fee6fa6d5680f6c93a62dd` |
| control `RESPONSE_INSTRUCTION` sha256 | `e5dd7f825008a752c19d4dc77fbec65ed74be9dbfc36c29c2bc9691c9924dd4f` (1439 chars) |
| control `judge.py` blob | `2a2a17f16611d4586d122d6e65710f9bd520910f` |
| Phase 0 runs | **58, 59, 60, 61** (N=4), all VALID, `git_commit_sha = 44ef7a4785d58b4da7fee6fa6d5680f6c93a62dd` on every run |
| Phase 0 recorded in | `docs/benchmark/BASELINE.md`, section "Registration B — Phase 0 Control Baseline", committed at `d7d3c4aeb697acdb3d3d5d1cdb329c3b58b81099` |
| Phase 0 result | control-arm reference only — **E1 = 0%, E2 = 0% (0/198 blocking defects resolved), E3 = all routes NULL**, `false_pass = 0`, no STOP rule fired (BASELINE.md, this section) |

Re-verified for this addendum: `git log --oneline -- docs/benchmark/BASELINE.md` shows
`d7d3c4a docs: record Registration B Phase 0 baseline` as the commit that added the section
above, and that section records runs 58-61 exactly as tabulated there. Nothing in §2 is
restated as new fact; it is copied forward so the intervention arm below has its comparison
point in the same document.

**Note on the control hash.** The value above (`...9924dd4f`, 64 hex characters) is the one
verified directly against `EVIDENCE_CAPTURE_PROMPT_REGISTRATION_B.md` §1 and
`BASELINE.md`'s Phase 0 section, both of which agree byte-for-byte. It is recorded here
exactly as those two sources give it.

---

## 3. Intervention arm

| item | value |
|---|---|
| implementation commit SHA | `cff6196df64fa7b7ece003e729b7eaac484f0d50` |
| parent SHA | `d7d3c4aeb697acdb3d3d5d1cdb329c3b58b81099` |
| commit message | `feat: add optional judge grounding evidence` |
| intervention `RESPONSE_INSTRUCTION` sha256 | `46798d4a1ec790360c78e3af940c4a3ed8cc92f340f7fc98af3e80e8dc4cb1af` |
| prompt length | **2452 chars** (control was 1439; +1013 chars, the evidence block) |
| files changed vs. parent | `src/engine/verification/judge.py`, `tests/test_verification.py` — exactly these two, nothing else (`git diff --name-status d7d3c4a cff6196`) |

Re-verified for this addendum, directly against the committed `HEAD` blob (not the working
tree): `hashlib.sha256(RESPONSE_INSTRUCTION.encode()).hexdigest()` returns
`46798d4a1ec790360c78e3af940c4a3ed8cc92f340f7fc98af3e80e8dc4cb1af`, `len(RESPONSE_INSTRUCTION)
== 2452`, and `RESPONSE_INSTRUCTION.endswith("never lower a violation you can ground.")` —
the grounded-severity ceiling's own final sentence — is `True`.

### 3.1 Optional evidence fields requested (exactly three, per Registration B §3)

- `grounded_in_clause` — a span of the task text copied verbatim that the finding rests on.
  Record-only in this experiment (Registration B §3.1): captured and persisted, but no `Fact`
  in `adjudication.py` consumes it.
- `minimal_trigger` — the smallest concrete argument demonstrating the defect, as
  `name=<python literal>`, scoped in the prompt to an argument binding and never
  `return=...` (§3.3).
- `grounding_route` — one value from the canonical enum, §4 below.

No other evidence key is requested. `excluded_by_clause` and `runtime_probe` — the two
`ADJUDICATION_EVIDENCE_KEYS` that can strip a finding's blocking authority through a premise
the judge itself would author — are deliberately withheld, exactly as Registration B §3.3
requires. Neither string appears anywhere in `RESPONSE_INSTRUCTION`.

---

## 4. Canonical `grounding_route` values (exactly these four, per Registration B §3.2)

```
explicit_requirement
permitted_input
stated_purpose
none/unclear
```

`runtime_premise` and `none_or_unclear` are excluded and do not appear in the prompt. Neither
is in `rubric.py:GROUNDING_ROUTES`, so `extract_evidence` would silently discard either one —
confirmed by the existing test
`test_extract_evidence_ignores_non_string_and_malformed_values` in `tests/test_adjudication.py`
(unmodified by the intervention commit) and, on the prompt side, by
`test_evidence_block_emits_only_the_canonical_routes` in `tests/test_verification.py`.

---

## 5. Explicit invariants (verified, not assumed)

- **Evidence fields remain optional, forever.** A defect carrying none of them is a complete,
  valid finding with full severity intact — stated in the prompt itself and pinned by
  `test_evidence_block_declares_all_three_fields_optional_forever`.
- **Severity remains impact-based, independent of evidence presence or absence.** The prompt
  states this explicitly and pins it with
  `test_evidence_block_preserves_severity_independence`; the pre-existing grounded-severity
  ceiling text is byte-identical and unmoved.
- **The intervention does not decide admissibility.** `admissible_to_block` is never named or
  requested from the judge.
- **The intervention does not decide blocking authority.** The judge is never asked whether a
  finding "may block."
- **The intervention does not suppress findings.** Nothing in the added text conditions
  reporting on evidence; every defect the judge would otherwise raise still appears in
  `defects`.
- **The grounded-severity ceiling remains the final instruction**, unchanged since the
  grounded-severity registration, verified in §3 above and pinned by
  `test_evidence_block_sits_before_the_grounded_severity_ceiling` and
  `test_registered_block_sits_at_the_registered_placement`.
- **Historical/control-shaped output remains schema-valid.** `enforce_critic_schema` is
  unmodified; it already tolerates unlisted per-defect keys (`schema.py:20` checks only for
  *missing* required keys). Pinned by `test_parse_critic_accepts_defect_with_no_evidence_fields`
  through `test_parse_critic_accepts_out_of_enum_grounding_route_without_invalidating_the_defect`
  in `tests/test_verification.py`.
- **No dataset, rubric, schema, verdict, or admissibility behavior changed.** `git diff
  --name-status d7d3c4a cff6196` touches only `src/engine/verification/judge.py` and
  `tests/test_verification.py`; `DEFECT_KEYS`, `GROUNDING_ROUTES`, `enforce_critic_schema`,
  `verdict.merge`/`verdict.gate`, `adjudication.py` and `admissibility.py` are byte-identical
  to the control arm.

The judge is asked to decide none of the following, per Registration B §4 — confirmed absent
from `RESPONSE_INSTRUCTION` by `test_evidence_block_asks_nothing_the_judge_may_not_decide`:
`trigger_in_contract`, `premise_excluded_by_guarantee`, `premise_depends_on_runtime_behaviour`,
`violation_present_in_submitted_code`, `self_contradiction`, `admissible_to_block`.

---

## 6. Phase 1 safety gates — unchanged, restated for reference

Nothing below is modified by this addendum or by the implementation commit. All thresholds
are exactly as frozen in `EVIDENCE_CAPTURE_PROMPT_REGISTRATION_B.md`.

- **§12.1 — false pass.** Any `false_pass >= 1` in any arm, any phase ⇒ immediate REJECT /
  STOP. Zero tolerance, no per-case exception.
- **§12.2 — schema failures.** Abort threshold **6 per run**, unchanged. Phase 0's control
  arm measured a max of 2/run (BASELINE.md), giving a concurrently measured reference, not a
  relaxed threshold.
- **§12.4 — `quality-04-broken` drift guardrail.** Must not fall from ≥1 blocking defect in
  control to 0 in intervention in any paired run; Phase 0 measured **exactly 1 blocker in
  every control run** — the tightest possible margin, and the case this rule exists to
  protect.
- **§12.5 — sole-blocker loss.** Any case resting on a single blocking defect in control that
  loses that defect's blocking severity in intervention ⇒ immediate REJECT. Phase 0 recorded
  `quality-04-broken` and **`security-03-broken`** as resting on exactly one blocker in
  **every** control run (BASELINE.md, sole-blocker census) — the narrowest-margin cases this
  rule watches.
- **Safety-control cases must remain blocked.** Phase 0 measured `edge_case-02-broken`
  blocked 4/4 and `security-04-broken` blocked 4/4 (BASELINE.md, safety-control results); an
  intervention run dropping either to unblocked triggers §12.4/§12.5 as applicable.
- **§11 — evidence-availability floor.** The intervention arm must reach **E2 ≥ 40%** (share
  of blocking defects resolved to a non-`fail-closed-unresolved` rule) to avoid closing
  INCONCLUSIVE-futility. Phase 0 measured the control floor at **E2 = 0%** — this is the
  baseline the intervention must move, not a target already met.
- **No efficacy claim exists yet.** Section 0 above states it explicitly: this document
  records what code and prompt will run, not what running them produced. E1/E2/E3, aggregate
  accuracy, and every §12 outcome for the intervention arm remain unmeasured until Phase 1
  executes.

---

## 7. What this addendum does not do

- Does not alter the hypothesis, E1/E2/E3, the 40% futility floor, the false-pass STOP rule,
  the schema-failure abort threshold of 6, the `quality-04-broken` or sole-blocker
  guardrails, N per arm, ACCEPT/REJECT/INCONCLUSIVE criteria, or the $30 stop-loss.
- Does not authorise any run. Phase 1 still requires its own per-turn approval and a passing
  `git-safety` pre-run gate (clean tree, recorded `HEAD`, SHA matching this addendum).
- Does not claim the intervention changes any verdict, resolves any evidence, or is safe.
  Shadow mode makes the adjudication layer verdict-neutral; it does nothing about the prompt
  itself (Registration B §6.1), so the intervention carries full false-pass risk on its first
  live run exactly as registered.
- Does not modify `judge.py`, any test, the prompt, or any file under
  `src/engine/verification/` beyond what commit `cff6196` already contains. No file changed
  in the making of this addendum other than the one it adds.

---

## 8. Provenance

- Written: 2026-09-12, before any run against this intervention exists.
- Registration B commit: `44ef7a4785d58b4da7fee6fa6d5680f6c93a62dd`.
- Addendum 01 commit: recorded the executable SHA and pre-run database baseline; unmodified
  by this addendum.
- Phase 0 baseline commit: `d7d3c4aeb697acdb3d3d5d1cdb329c3b58b81099`.
- Intervention implementation commit: `cff6196df64fa7b7ece003e729b7eaac484f0d50`, parent
  `d7d3c4aeb697acdb3d3d5d1cdb329c3b58b81099`.
- Runs executed against this intervention at time of writing: **none.**
- No benchmark run, no provider call, no spend produced this document.
