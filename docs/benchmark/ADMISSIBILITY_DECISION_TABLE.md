# Admissibility Decision Table — specification (spec only, not implemented)

**Status: SPEC ONLY. Nothing in this document is implemented, and nothing in it authorises a
run.** No production code, prompt, rubric, schema, judge or dataset fixture is changed by this
document. It defines a predicate and records how that predicate scores retrospectively against a
frozen label set. It is not an efficacy claim, and it must not be cited as one.

| Record | Value |
|---|---|
| Date | 2026-09-10 |
| Branch | `feature/agent-capabilities-layer` |
| HEAD at authoring | `cff9764906749ea7caf6f17e59decbdf62452b95` |
| Working tree at authoring | Clean (before this file and the gold set were written) |
| Dataset | v6 — **not modified by this document** |
| Judge model | `claude-sonnet-5` (unchanged; runs 44+) |
| Gold set | [`admissibility-gold-v6.json`](./admissibility-gold-v6.json) v1.0.0 |
| Authorised work | Offline specification and offline scoring only. **No live run authorised.** |

---

## 0. What problem this addresses, and what it does not

The offline separability analysis of the v6 corpus established that blocking defects fall into two
populations that are cleanly distinguishable from evidence already present in the task contract and
the judge's own output:

- **genuine** blockers, grounded in an explicit requirement, a permitted input, or the stated
  purpose of the function;
- **inadmissible** blockers, resting on a premise that the contract excludes, an input the contract
  forbids, or a technical fact that is false on the pinned runtime.

**What this predicate does.** It decides, per defect, whether that defect may contribute to the
blocking gate.

**What this predicate does not do.** It does not change severity, in either direction (§2,
principle 7). It does not fix `quality-04-broken`, whose failure is a *severity* disagreement, not a
grounding failure — see §7F. It does not address the schema-failure path, which after this predicate
becomes the dominant remaining source of false blockers (§6.4).

### Relationship to the rejected structured-grounding arm

`STRUCTURED_GROUNDING_REGISTRATION.md` is **CLOSED — REJECTED AT L0**, rolled back at HEAD. That
intervention added required grounding fields to the critic schema and routed compliance through
severity. This specification differs in three ways that matter:

1. it changes **no schema**, so it cannot produce new schema errors, and cannot fail closed into
   `UNVERIFIED` the way added required fields did;
2. it **never forces severity upward**, which is the mechanism that produced the L0 `false_pass` on
   `quality-04-broken`;
3. it is **scored offline against a frozen label set before any implementation exists**.

That prior rejection stands. Nothing here reverses it, and no efficacy claim from that arm is
revived.

---

## 1. Scope

Applies to one judge-emitted defect at a time, from lenses `correctness`, `security`,
`code-quality`. Out of scope: anything not emitted by a judge lens (§2, principle 9), and every
non-blocking defect, which the predicate never touches.

---

## 2. Principles, and the evidence each one rests on

Each principle is required by a specific observation in the v6 corpus. None is speculative.

| # | Principle | Evidence in the corpus |
|---|---|---|
| 1 | **Minimal-trigger.** Classify on the minimal condition required for the claimed failure, never on what the prose incidentally mentions. | 12 of 19 `edge_case-02-broken` blockers mention non-dict input while resting on an in-contract `KeyError`. Mention-based rejection destroys all 12. |
| 2 | **Declared-interface.** Parameter and return annotations are contract facts. | `edge_case-02-clean` needs `user: dict` to reject family 1, and `-> str \| None` to reject family 2. |
| 3 | **Explicit-guarantee.** A task guarantee is authoritative and cannot be argued around. | 17 of 23 `security-04-clean` blockers demand protection against caller re-resolution, which the task explicitly guarantees does not happen; many concede the point in their own text. |
| 4 | **Factual-premise.** A premise false or unverifiable on the pinned runtime cannot support blocking. | Every claimed IPv4-mapped / 6to4 / NAT64 / ULA bypass is already rejected by the submitted code on Python 3.14.5. |
| 5 | **Purpose-grounding.** A genuine defect implied by the stated purpose stays admissible without an explicit requirement sentence. | `security-03-broken` (weak randomness) has no cryptographic sentence in the task and no input at all. It is the **sole** blocker in all 8 runs. |
| 6 | **Citation is not grounding.** Quoting the task proves nothing. | 42 non-blocking clean-case defects cite the task. Forcing on citation costs +20 false blockers. |
| 7 | **No severity forcing.** The predicate decides admissibility only. | Forcing class A to HIGH re-breaks `security-04-clean` through the genuine CGNAT finding: 311 correct vs 313 without forcing. |
| 8 | **Per-defect.** Each defect is judged alone; a case blocks if any admissible blocker survives. | `security-01-broken` survives on the correctness lens' permitted-input grounding while the security lens' grounding is weaker. |
| 9 | **ENV separation.** Environment and tooling failures are not judge findings. | `run55 / security-03-clean / mypy` exited 3221225501 — a Windows process crash, not a type error. |

---

## 3. Required semantic inputs

The predicate is **semantic**, not lexical. No gate may be decided by keyword or substring
matching. Each input below must be established by reading the defect against the task contract.

| Key | Input | Question it answers |
|---|---|---|
| `S0` | `emitted_by_judge_lens` | Did a judge lens produce this, or a tool? |
| `S1` | `minimal_trigger` | What is the smallest input or condition under which the claimed failure actually occurs? |
| `S2` | `trigger_in_contract` | Is that minimal trigger permitted by the declared interface — parameter annotations, return annotation, and any stated input constraints? |
| `S3` | `premise_excluded_by_guarantee` | Does the load-bearing premise require a condition the task explicitly guarantees does not occur? |
| `S4` | `premise_true_on_pinned_runtime` | Is the load-bearing technical premise true, and checkable, on the pinned runtime and toolchain? |
| `S5` | `violation_present_in_submitted_code` | Is the violation in the code under review, rather than hypothetical, future, or dependent on misuse elsewhere? |
| `S6` | `grounding_route` | `explicit_requirement` \| `permitted_input` \| `stated_purpose` \| `none` |

### Deciding `S1`/`S2` — the minimal-trigger rule

> If **any** input permitted by the declared interface triggers the claimed failure, then
> `trigger_in_contract = true`, **regardless of any out-of-contract inputs the defect also
> mentions.** `trigger_in_contract = false` only when **every** input that triggers the claimed
> failure lies outside the declared interface.

This rule exists because violating it destroys 12 genuine blockers on `edge_case-02-broken`. It is
the single most implementation-critical sentence in this document.

### Deciding `S6` — grounding routes

- `explicit_requirement` — a normative sentence in the task text states the rule, and the code
  demonstrably violates it. **Quoting the task is not sufficient**; the quoted sentence must be the
  rule the code actually breaks (principle 6).
- `permitted_input` — a concrete input permitted by the declared interface deterministically
  produces the claimed failure.
- `stated_purpose` — the task's stated purpose establishes the property (`"for password-reset
  links"` establishes unpredictability; `"guard … against SSRF"` establishes address validation),
  and the defect names a real violation of it.
- `none` — none of the above. Severity may still be reported; blocking authority is not earned.

---

## 4. The decision table

**First match wins. Order is normative.**

| # | Gate | Condition | Result | Expected class |
|---|---|---|---|---|
| **0** | Scope | `S0` is false — not emitted by a judge lens | `OUT_OF_SCOPE` | `ENV` |
| **1** | Presence | `S5` is false — hypothetical, future, or misuse elsewhere | `INADMISSIBLE` | `E` / `F` |
| **2** | Guarantee | `S3` is true — premise excluded by an explicit task guarantee or a declared annotation | `INADMISSIBLE` | `D` |
| **3** | Contract | `S2` is false — every triggering input is out of contract | `INADMISSIBLE` | `C` |
| **4** | Premise | `S4` is false — premise false, or not verifiable on the pinned runtime | `INADMISSIBLE` | `E` |
| **5** | Grounding | `S6` ∈ {`explicit_requirement`, `permitted_input`, `stated_purpose`} | **`ADMISSIBLE`** | `A` / `B` / `G` |
| **6** | Default | otherwise | `INADMISSIBLE` | `F` |

### Why the prohibitions precede the grounding gate

Gates 1–4 run **before** gate 5. A defect that cites a task requirement but rests on an excluded
premise is still inadmissible. Reversing this order is not a stylistic choice — §6.5 measures it:
grounding-first admits every `edge_case-02-clean` out-of-contract blocker, because each one quotes
the task's `"without raising"` wording.

### What `INADMISSIBLE` means operationally

The defect is **retained in the report at its original severity** and continues to be shown to the
user. It does not contribute to the blocking gate. It is never deleted, never downgraded, and never
upgraded (principle 7). This is what keeps the genuine CGNAT and `fec0::/10` findings visible while
denying blocking authority to the false premises they are bundled with.

### Case-level rule

A case blocks if **at least one** admissible blocking defect survives. Gate results are never
aggregated or averaged across a case.

### Interaction with the existing gate

`verdict.gate()` has three independent paths to `UNVERIFIED`: `schema_errors`, then
`not automated_passed`, then `_has_blocking`. This predicate would sit **only** in front of the
third. It cannot rescue a case that fails closed on schema, and it must never be credited with one
(§6.4).

---

## 5. What the retrospective score can and cannot establish

**It validates the table's logic and ordering.** Gate ordering, the minimal-trigger rule and the
purpose-grounding route are all falsifiable against the frozen labels, and §6.5 shows that plausible
variants of the table score materially worse.

**It does not validate extraction.** The gold set records semantic facts (`S1`–`S6`) that were
established by human reading. Scoring the table against those facts measures the table, **not** any
implementation's ability to recover them from a judge's prose. A real implementation's accuracy is
bounded above by these numbers and is unmeasured.

**It is a deterministic recount, not a measurement.** The figures below carry no sampling error as
arithmetic on fixed data, and they are not an intervention effect. A live effect would average
≈ +1.1 cases/run against pooled σ ≈ 0.92 — about 1.2σ, **carried over** from the v3
`c0515eb`/`be990c7` clusters and never measured on v6 or on Sonnet. A single run could not
demonstrate it.

---

## 6. Retrospective score

Frozen gold set: 385 blocking defects, runs 48, 50, 51, 52, 53, 54, 55, 57. Run 56 excluded (11
error rows). See `admissibility-gold-v6.json` for every record.

### 6.1 Defect level

| Outcome | Count |
|---|---|
| must-preserve defects **preserved** | **356 / 356** |
| must-preserve defects **lost** | **0** |
| must-suppress defects **suppressed** | **28 / 28** |
| must-suppress defects still admitted | **0** |
| `ENV` routed `OUT_OF_SCOPE` | 1 / 1 |

### 6.2 Sole-blocker safety

45 of 157 blocking broken case-instances hang on a single blocker. **All 45 are preserved; 0 lost.**
No must-suppress defect is a sole blocker, so there is no safety conflict to trade off.
`security-03-broken` is the sharpest case: it is a sole blocker in **all 8 runs**, it is class `G`,
and only the purpose-grounding route keeps it.

### 6.3 Case level

| Metric | Baseline | With predicate | Δ |
|---|---|---|---|
| correct | 304 / 320 | **313 / 320** | +9 |
| `false_pass` | 2 | **2** | 0 |
| `false_unverified` | 14 | **5** | −9 |

Nine clean-case instances are fixed: `security-04-clean` in runs 48, 50, 51, 52, 53, 55, and
`edge_case-02-clean` in runs 48, 50, 55. No broken case changes verdict.

### 6.4 Residual failures — and what they are not

| Residual | Count | Cause | Reachable by this predicate? |
|---|---|---|---|
| `quality-04-broken` runs 52, 57 | 2 | threshold defect rated MEDIUM by every lens | **No** — severity, not grounding (§7F) |
| `security-02-clean` runs 48, 53 | 2 | schema failure → fail-closed | **No** |
| `security-04-clean` runs 54, 57 | 2 | schema failure → fail-closed | **No** |
| `security-03-clean` run 55 | 1 | `mypy` process crash | **No** — `ENV` |

**No credit is taken for any of these.** After this predicate the dominant remaining false-blocker
cause is the schema path, not severity: 16 of 17 v6 schema failures are the judge's prose verdict
disagreeing with its own severity labels. That is a separate problem and is not addressed here.

### 6.5 Ordering ablation — the table is not vacuous

| Variant | correct | `false_pass` | `false_unverified` | must-preserve lost | sole-blocker lost | bad still admitted |
|---|---|---|---|---|---|---|
| **Specified order (prohibitions → grounding)** | **313** | **2** | **5** | **0** | **0** | **0** |
| Grounding gate first | 304 | 2 | 14 | 0 | 0 | **28** |
| Mention-based contract gate (violates principle 1) | 310 | **5** | 5 | **12** | 0 | 0 |
| Drop the purpose-grounding route (gate 5 minus `stated_purpose`) | 304 | **11** | 5 | **17** | **8** | 0 |

Reading, in order of severity:

- **Grounding gate first** collapses to baseline. Every inadmissible defect claims *some* grounding
  route — the `edge_case-02-clean` out-of-contract blockers quote `"without raising"`, the
  `security-04-clean` families invoke the SSRF purpose — so all 28 bad blockers are readmitted and
  nothing is suppressed. This is the concrete measurement behind principle 6.
- **Mention-based contract gate** loses 12 genuine blockers (11 on `edge_case-02-broken`, 1 on
  `security-04-broken`) and turns 3 broken case-instances into false passes — `edge_case-02-broken`
  in runs 50, 53 and 54, each of which has only 2–3 blockers and loses all of them. This is why the
  minimal-trigger rule in §3 is normative rather than advisory.
- **Dropping purpose-grounding** loses 17 genuine blockers and 9 broken case-instances:
  `security-03-broken` in all 8 runs plus `security-01-broken` in run 57, where both of that case's
  blockers happen to be bare. `false_pass` rises from 2 to 11. Aggregate accuracy is unchanged at
  304 — it fixes 9 clean cases while breaking 9 broken ones — which is a clean demonstration that
  the accuracy column cannot be used to evaluate this predicate.

**Severity forcing is not scored here.** It requires non-blocking defects, which are out of the gold
set's scope. The prior offline analysis measured it at 311 correct versus 313 without forcing, with
`false_pass` 0 but 4 new false blockers on `security-04-clean` via the genuine CGNAT finding. That
figure is **carried over, not recomputed against the corrected labels**, and is recorded only as the
reason principle 7 exists.

### 6.6 Per configuration cluster

| Cluster | Runs | n | Baseline | With predicate | Δ | must-preserve lost |
|---|---|---|---|---|---|---|
| `eb7b4a7` | 48 | 40 | 37 | 39 | +2 | 0 |
| `16309b5` | 50–53 | 160 | 153 | 158 | +5 | 0 |
| `fd8f136` | 54, 55 | 80 | 76 | 78 | +2 | 0 |
| `9d20c33` | 57 | 40 | 38 | 38 | 0 | 0 |
| **All** | | **320** | **304** | **313** | **+9** | **0** |

Sign-consistent in every cluster; zero loss in every cluster. Run 57 is the rejected arm and moves
0 — its `security-04-clean` failure is schema-driven, not severity-driven.

---

## 7. Required stress tests

| | Test | Result |
|---|---|---|
| **A** | `edge_case-02-broken` — incidental out-of-contract language must not suppress a blocker whose minimal trigger is in-contract | **PASS.** All 19 blockers admissible, 0 lost. Between 11 and 12 of them mention non-dict input — the count moves with how "mentions" is operationalised, which is itself evidence that mention-matching is unsafe — and every one reaches gate 3 with `trigger_in_contract = true`, because `{}` and `{'profile': None}` are valid `dict` and trigger the same `KeyError`/`TypeError`. The mention-based ablation in §6.5 shows the cost of getting this wrong: 12 genuine blockers lost and 3 broken case-instances flipped to false passes. |
| **B** | `security-03-broken` — class `G` must survive with no explicit crypto sentence | **PASS.** All 8 preserved via `stated_purpose`. Gates 1–4 do not fire: the violation is present, no guarantee excludes it, there is no input to be out of contract, and the premise is true. |
| **C** | `security-04-clean` — re-resolution blockers must be suppressed | **PASS.** 17 suppressed at gate 2. The task guarantees the caller does not re-resolve. |
| **D** | `security-04-clean` — false mapped-IPv6 / 6to4 / NAT64 / ULA premises must be suppressed | **PASS.** 6 suppressed at gate 4, falsified on Python 3.14.5. |
| **E** | `security-04-clean` — real CGNAT / `fec0` concerns must remain visible | **PASS.** 8 non-blocking findings untouched (`non_blocking_annex`); 4 blocking defects that also mention them are suppressed on their *other*, load-bearing premise and carry the `MIXED` verification string. Nothing is erased. |
| **F** | `quality-04-broken` — admissibility must not be claimed as a fix | **PASS — by explicit non-claim.** All 9 blockers admissible; the predicate changes nothing. Runs 52 and 57 still false-pass because every lens rated the threshold defect MEDIUM. This is a compliance/rubric question, not a grounding one, and stays open. |
| **G** | `security-04-broken` — suppressing the rebinding-family defects must not make the broken case pass | **PASS.** Run 48: 7 blockers → 6 admissible. Run 50: 6 → 5. Both still block on the genuine no-validation `CRITICAL`. 0 sole-blocker conflicts. |

---

## 8. Known limitations

1. **Extraction is unvalidated.** §5. The scores bound an implementation from above.
2. **Single-rater labels.** The gold set is one reviewer's judgement with no inter-rater agreement
   measurement. Two labels were already corrected once (`meta.label_correction_note`).
3. **One disputed label, resolved by decision, not by evidence.** `run50 / security-04-broken /
   security / C3` was ruled class `D`; a reasonable reviewer could have read its trailing
   obfuscated-IP-literal clause as a second, genuine claim.
4. **Gate 1 is under-exercised.** Only a handful of corpus defects are purely hypothetical, so the
   presence gate is largely untested and may be redundant with gate 4.
5. **Ceiling is 313/320.** Even a perfect predicate leaves 2 severity false-passes, 4 schema
   false-blockers and 1 `ENV` artifact.
6. **Sonnet-only.** Every run here was judged by `claude-sonnet-5`. Nothing is claimed about
   `claude-haiku-4-5-20251001`, which produced runs 1–42.
7. **v6-only.** No claim crosses the v4/v5/v6 dataset boundaries.

---

## 9. Status and what would come next

**Not implemented. No run authorised. No efficacy claim.**

The offline bars set for this stage are met: zero must-preserve losses, zero sole-blocker losses,
all 28 known bad blockers suppressed, and no credit taken from schema or `ENV` fail-closed
behaviour. That is sufficient to justify *designing* an implementation — it is not sufficient to
justify spending.

Before any paid work, the unmeasured risk in limitation 1 is the thing to attack: the table is
validated, the extraction is not. The next step should establish whether the `S1`–`S6` facts can be
recovered from judge output at all, offline, on the frozen corpus — not whether the engine scores
better.

Any future live experiment must be pre-registered under `experiment-design`, must pass the
`git-safety` pre-run gate, and should use a per-case primary metric — `security-04-clean` passing,
which fails in 7 of 8 runs today — rather than the aggregate accuracy column, which cannot resolve
an effect this size at feasible N.
