# Pre-registration — Grounded-Severity Ceiling on `RESPONSE_INSTRUCTION`

**Status: PRE-REGISTERED, NOT IMPLEMENTED, NOT RUN.** This document exists before the
intervention it governs, deliberately: `PHASE4_REGISTRATION.md` was cited by commit
`be990c7` as "applied verbatim" but never committed, and its text — the exact wording of
H1, of its negative-result signature, and of its guard set — is permanently unrecoverable
from this repository. That failure is not repeated here.

| Record | Value |
|---|---|
| Date | 2026-09-08 |
| Branch | `feature/agent-capabilities-layer` |
| Verified HEAD at registration | `ea716b5e402fd36159864bce41ae6678c821adb9` |
| Working tree at registration | Clean |
| Dataset | v6 (frozen — `DATASET_V6_AMENDMENT.md`) |
| Judge model | `claude-sonnet-5` |
| Precedent | Phase 4 (`be990c7`, INCONCLUSIVE), `OFFLENS_BLOCKING_REGISTRATION.md` (closed, no benefit), `ANSWER_BUDGET_PHASE2_REGISTRATION.md` |
| Authorized work now | This document only |

## 0. Scope

This registration authorizes **no code change and no run.** Implementing the delta in §3 is
a measured-path edit to `src/engine/verification/judge.py` requiring its own explicit
per-turn approval (`git-safety`), and every run in §7 requires the pre-run gate — clean
tree, recorded SHA — independently.

**This experiment tests severity grounding, not benchmark score.** Aggregate accuracy is a
secondary observation here and decides nothing (§8.3). A result that improves the score
while tripping a safety guardrail is a REJECT, not a success.

## 1. The problem, as adjudicated

Two clean cases have never passed under the Sonnet judge. Both fail because findings that
cannot support a blocking claim are nonetheless assigned CRITICAL or HIGH.

**`edge_case-02-clean`.** The declared signature is `get_user_email(user: dict)`. The
implementation satisfies every in-contract dictionary input, including missing keys and
non-dict intermediate values. The judge blocks on a caller passing a non-`dict` `user`
(e.g. `None`) raising `AttributeError` — an input the declared interface excludes. The
task's "without raising" clause scopes to *"if any part of that path is missing"*, i.e.
missing keys within a dict. The finding is a legitimate hardening suggestion resting on an
out-of-contract premise; it is not a violation of the stated contract.

**`security-04-clean`.** The task states: *"The caller connects to the address you return
and does not look the host up again, so the address you return must be one you checked."*
Observed blocking findings (runs 46-49) rest on premises the record contradicts:

- A CRITICAL claiming `addresses[0]` may be unvalidated, while the same finding text
  concedes *"since all addresses are checked in the loop this specific bug is mitigated"* —
  the code gates on `all(_is_public(addr) for addr in addresses)`. Self-refuting.
- DNS-rebinding and re-resolution claims, which the task explicitly places outside this
  code's responsibility.
- A claim that IPv4-mapped IPv6 forms such as `::ffff:127.0.0.1` may be classified public.
  Empirically false for the library in use.

**A genuine, separate concern exists and must survive this experiment.** The CGNAT / range
coverage question on `_is_public` remains open for independent adjudication
(`DATASET_V5_AMENDMENT.md`). This experiment must not delete it from the record.

## 2. Why a severity ceiling, and not the mechanisms already tried

Phase 4 (`be990c7`) appended a *reporting prohibition* to `RESPONSE_INSTRUCTION` —
Mechanism B (finding contradicted by the supplied source) and Mechanism C (finding rests
on a requirement the task does not state). It was **INCONCLUSIVE, H1 unsupported**, and the
mechanism evidence moved against the hypothesis: mean `false_unverified` rose 5.11 → 5.38,
and `security-03-clean` collapsed from 9/9 to 3/8 as an unregistered adverse finding.

This registration is a different intervention on three structural counts:

1. **It sets a severity ceiling, not a reporting filter.** The finding is still emitted in
   `defects`. Only the severity it may claim is constrained. This is what preserves the
   open CGNAT concern — demoted to at most MEDIUM, still visible — instead of erasing it.
2. **It acts on the actual lever.** `enforce_critic_schema` already enforces
   `verdict = FAIL iff ≥1 CRITICAL or HIGH`, and `verdict.gate` blocks on exactly that set.
   Severity *is* the blocking decision. A prohibition on reporting never was.
3. **It is symmetric.** The rule carries an explicit anti-deflation clause. Phase 4 had no
   analogue, and its adverse movement was never bounded by one.

Rejected alternatives, recorded: **severity anchors alone** supply no test the judge can
apply, and invite re-labelling the same conviction; **a declared-contract-versus-hardening
rule alone** is near case-specific — it addresses `edge_case-02-clean` and barely touches
`security-04-clean`, and its wording is closest to the Mechanism C already unsupported.

## 3. The intervention

One contiguous block appended to the end of `RESPONSE_INSTRUCTION` in
`src/engine/verification/judge.py`. **No case name, library, IP range, type name, API, or
case-specific wording appears in it**, and it applies uniformly to all three lenses (which
share one user prompt by invariant):

> Severity is what makes a defect blocking, so assign it from evidence, not from concern.
> Before assigning CRITICAL or HIGH, name either (a) the exact requirement in the task
> above that the code fails to meet, or (b) a concrete input or condition, permitted by the
> code's own declared interface, that produces the failure. If you can name neither — the
> finding rests on a caller violating a declared parameter type, on a threat the task
> explicitly places outside this code's responsibility, on a possible but undemonstrated
> library or platform behavior, or on hardening the task did not ask for — still report the
> defect, but assign at most MEDIUM. Reporting is unaffected: every concern you would
> otherwise raise must still appear in defects; only its severity is constrained. Never
> raise a severity to signal importance, and never lower a violation you can ground.

Placement is **appended at the end**, matching Phase 4's placement so that placement is not
a second variable (run 16 established that placement alone is consequential).

## 4. Hypothesis

**H1.** Appending the §3 rule moves `edge_case-02-clean`'s single `correctness`/HIGH finding
to MEDIUM or below — flipping that case to `OK` — and reduces the count of blocking
(CRITICAL + HIGH) defects on `security-04-clean`, while no broken case ceases to block.

## 5. Targets and measured baselines

Baselines are `passes/runs` at the Sonnet judge across full-40 runs 44, 46, 47, 48.

| Target | Baseline pass rate | Blocking mass | Margin |
|---|---|---|---|
| `edge_case-02-clean` | **0/4** | exactly **1** `correctness`/HIGH in every run | single blocker; a verdict flip is achievable |
| `security-04-clean` | **0/4** (0/7 including 10-case slices 45, 49) | **3-4** blocking defects across `correctness` + `security` (runs 47/48/49) | fully redundant; a verdict flip needs all to drop, so severity mass is the readable signal |

**The baseline arm is measured, never inherited.** At HEAD (`ea716b5`, v6) exactly one run
exists (49, a 10-case security slice) and no full-40 run. Run 47 sits on the far side of the
v5→v6 dataset boundary; run 48 is v6 but n=1 and precedes a measured-path commit. Both arms
are run fresh and concurrently under this registration.

## 6. Metrics

### 6.1 Primary

- **P1 — `edge_case-02-clean` pass rate**, per arm.
- **P2 — mean count of blocking (CRITICAL + HIGH) defects on `security-04-clean`**, per arm.
  Its verdict is deliberately *not* the primary reading: at 3-4 redundant blockers a binary
  flip is under-powered, while blocking mass resolves the mechanism directly.

### 6.2 Secondary — reported, never decisive

- Aggregate `correct_verdicts / 40`, per arm.

### 6.3 Also recorded

- Full per-lens severity distribution across all 40 cases, both arms.
- Retry firings and rescues; schema failures with lens and case.

## 7. Execution plan

Vehicle: the full 40-case `engine bench` on the production Sonnet configuration. Category
slicing was evaluated and rejected — two 10-case slices cost ~$0.45 against a full run's
~$0.53 while discarding half the guardrail surface, which is precisely the surface that
catches Phase-4-style collateral damage.

### 7.1 Stage 1 — N=4 per arm (8 runs)

Then, by pre-registered rule only:

- **Safety stop.** Any hard guardrail in §9 trips → **STOP, REJECT, roll back (§11).**
- **Futility stop.** Intervention `edge_case-02-clean` = 0/4 **and** `security-04-clean`
  mean blocking count within ±1 of the baseline arm → **STOP, record NOT SUPPORTED.**
- Otherwise → Stage 2.

### 7.2 Stage 2 — extend both arms to N=8 (8 further runs)

N=8 per arm is the working default from `experiment-design`: at a baseline of 0/8, Fisher's
exact (two-sided) makes **≥5/8 significant (p = 0.026)** while **4/8 (p = 0.077) does not
clear it**. At N=4 the primary could only ever register an all-or-nothing 4/4 movement.

**No extension beyond N=8 per arm is permitted, for any reason.** "Almost significant" is
not a registered extension condition.

### 7.3 Sample-size caveat, registered in advance

The aggregate secondary metric has MDE ≈ 1.3 cases at N=8 under σ = 0.92. That σ is
**carried over** from the v3 `c0515eb` / `be990c7` clusters and has never been measured on
v6 or on the Sonnet judge. It is a planning stand-in and is labelled as such wherever this
experiment is reported.

## 8. Decision rules

### 8.1 ACCEPT

All three, at N=8:

1. `edge_case-02-clean` **≥ 5/8** in the intervention arm **and ≤ 1/8** in the baseline arm.
2. `security-04-clean` mean blocking-defect count reduced by **≥ 1.5** versus the baseline arm.
3. **Zero** hard-guardrail trips (§9).

### 8.2 REJECT

Any hard guardrail in §9 trips, at any point, in any run — including during Stage 1.

### 8.3 INCONCLUSIVE

P1 lands in the **2-4/8** range with no guardrail trip. Recorded as inconclusive and closed:
no re-slicing, no metric added after the fact, no extension.

**What does not decide anything:** aggregate score, cost, wall time, retry counts, or any
per-case movement outside §5 and §9. A score improvement accompanied by a guardrail trip is
a REJECT.

### 8.4 VOID

Any run with ≥ 1 `eval_case_results.error` row is void, excluded, and replaced (per
`baseline-evidence`). A dirty tree or a SHA mismatch at the pre-run gate voids the batch.

## 9. Hard safety guardrails

Any single trip → REJECT and roll back.

- **G1 — false pass, zero tolerance.** Any broken case returning `OK` in any intervention
  run. Margin analysis (run 48): **6 broken cases rest on exactly one blocking defect**, but
  **5 of those 6 are CRITICAL** (`correctness-01-broken`, `correctness-02-broken`,
  `correctness-05-broken`, `edge_case-03-broken`, `security-03-broken`) and each names a
  concrete violated task requirement, so §3 leaves them untouched by construction. The real
  exposure is **one case — `edge_case-01-broken`, the only broken case held by a single
  HIGH** — designated here as the highest-risk guardrail.
- **G2 — `security-03-clean` ≥ 6/8.** Phase 4's unregistered casualty (9/9 → 3/8).
  `BASELINE.md` requires it as a guardrail for any intervention touching judge severity
  calibration; this is such an intervention.
- **G3 — clean-case regression.** No clean case currently at 4/4 may fall below 6/8.
- **G4 — aggregate floor.** Intervention-arm mean `correct_verdicts` may not fall more than
  **1.3 cases** (the N=8 MDE) below the baseline arm's.
- **G5 — schema reliability.** Mean schema failures per run may not exceed the baseline
  arm's mean + 2.

### 9.1 Constraints this experiment must not violate

- Genuine security findings keep CRITICAL/HIGH — they can name the violated requirement.
- **The open CGNAT / range concern is demoted, never deleted:** it remains in `defects` and
  remains available for its separate adjudication.
- Out-of-contract hardening suggestions are capped, never promoted to blocking.
- Unsupported CRITICAL/HIGH is exactly what the ceiling removes — no more.
- Merge, gate, and fail-closed semantics are unchanged in code and in behavior.

## 10. Frozen — must not change

`eval/dataset.py` (**dataset v6, frozen**); `verification/rubric.py`; `schema.py`;
`verdict.py`; `pipeline.py`; `eval/runner.py`; `runtime/gateway.py`; `budget.py`;
`config.py` `DEFAULT_MODELS` (`claude-sonnet-5`); **all three `LENSES` system prompts**;
`MAX_JUDGE_RETRIES = 1`; the `max_tokens = 1600` cap; the `max_tokens`-only retry trigger;
`thinking_disabled` retry behavior; fail-closed semantics.

The only diff under this registration is the §3 block appended to `RESPONSE_INSTRUCTION`.

## 11. Rollback rule

On REJECT or NOT SUPPORTED: revert the intervention commit (the `64518fe`-reverts-`be990c7`
precedent), then prove restoration with `git diff <pre-intervention-sha> HEAD -- src/`
returning empty, and record that command and its output. **Intervention runs remain in
`BASELINE.md` permanently**; only the configuration reverts.

## 12. Cost

Using recent full-40 Sonnet runs — 46 ($0.5334), 47 ($0.5217), 48 ($0.5307) — mean
**≈ $0.529/run**, ~8.4 minutes each.

| | Runs | Cost | Wall time |
|---|---|---|---|
| Stage 1 (N=4 × 2 arms) | 8 | **≈ $4.23** | ~67 min |
| Stage 2 (extend to N=8 × 2 arms) | +8 | +≈ $4.23 | +~67 min |
| **Worst case, full design** | **16** | **≈ $8.46** | **≈ 2.25 h** |

A futility or guardrail stop caps spend at ≈ $4.23.

## 13. What a negative result looks like

Intervention arm: `edge_case-02-clean` ≤ 1/8, `security-04-clean` blocking mass unchanged
within ±1, no guardrail trips.

That is a **second independent failure of grounding-style instructions on this judge**, and
is recorded in `BASELINE.md` beside Phase 4 with the same weight as a positive result —
evidence that this class of intervention does not transfer. A negative or inconclusive
result is never quietly dropped, re-sliced, or re-registered under a new name.

## 14. Registered ablation — not authorized now

§3 couples a decision procedure with a severity ceiling in one block. This is the design's
main methodological weakness: a null result cannot attribute the failure to either half.
**If and only if §8.1 ACCEPT is reached**, a follow-up phase decomposes it — grounding-test-
only versus ceiling-only arms. Registered here so that the decomposition is never a
post-hoc re-slice. Not authorized by this document.

## 15. Completion boundary

This phase creates only `docs/benchmark/GROUNDED_SEVERITY_EXPERIMENT_REGISTRATION.md`. It
makes no change to `judge.py` or any other measured-path file, no dataset change, no test
change, no `BASELINE.md` update. No benchmark, paid call, merge, or push is performed.
Review the new-file diff and stop.
