# Pre-registration — Structured Grounding Contract on the Critic Schema

**Status: PRE-REGISTERED. OFFLINE IMPLEMENTATION AUTHORIZED. NO LIVE RUN AUTHORIZED.**

| Record | Value |
|---|---|
| Date | 2026-09-08 |
| Branch | `feature/agent-capabilities-layer` |
| Verified HEAD at registration | `70e88428d75d57e10f4d3d69c2b5cbfdebd60f6d` |
| Working tree at registration | Clean |
| Dataset | v6 (frozen — `DATASET_V6_AMENDMENT.md`) — **not modified by this phase** |
| Judge model | `claude-sonnet-5` (unchanged) |
| Supersedes | `GROUNDED_SEVERITY_EXPERIMENT_REGISTRATION.md` §3 (prose ceiling) |
| Authorized work now | Offline implementation and offline tests only |

## 0. Closure of the preceding experiment

The grounded-severity ceiling experiment (`GROUNDED_SEVERITY_EXPERIMENT_REGISTRATION.md`,
intervention commit `fd8f136`) is **formally closed as INCOMPLETE / INCONCLUSIVE.**

- It stopped because the Anthropic account reached zero credit partway through
  intervention run 3, **not** because any pre-registered decision rule fired.
- Valid evidence: baseline runs **#50-53** (N=4, SHA `16309b5`), intervention runs
  **#54-55** (N=2, SHA `fd8f136`). Preserved as partial evidence.
- Run **#56 is VOID** — 11 `eval_case_results.error` rows from credit exhaustion,
  excluded per that registration's §8.4, and never averaged or scored.
- Its Stage 1 rules required N=4 per arm and were **never evaluated**. No ACCEPT,
  REJECT, or registered-INCONCLUSIVE verdict was reached, and none may be claimed.

Its §3 prose block is superseded by §2 below. Runs #50-55 remain valid measurements
**of their own SHAs** and are not re-interpreted by this document.

## 1. The measured failure this addresses

From the offline forensic analysis of the two surviving intervention-arm blockers
(recorded in `BASELINE.md`; all figures read from `.engine/state.db`):

**The model performs the grounding test and fails to propagate its conclusion into
`severity`.** The controlled comparison is a single intervention run containing both
outcomes for the same claim family:

- one defect: *"this is actually handled correctly ... not a real defect against the
  stated requirement; downgrading concern"* → **MEDIUM** (propagated)
- another defect: *"this is fine as written ... No fix needed ... downgrade concern"* →
  **HIGH** (not propagated)

The same run also assigned the identical claim MEDIUM under one lens and HIGH under
another.

**Root cause.** The prose ceiling asks the model to *name* a grounding before assigning
CRITICAL or HIGH, but the output schema has **no slot for that naming**. Compliance
occurs in free prose inside `fix`, where it is unobservable and unenforceable. A model
can complete the test, write the correct conclusion, and still emit HIGH, with nothing
able to detect the contradiction.

**Why a bare non-empty string is insufficient** (the rejected alternative): a required
free-text `grounding` field would be satisfied by any characters at all. It would not
make the *classification* machine-checkable, and would not let the schema detect the
contradiction above. The constraint has to be a closed enum cross-checked against
severity, or it adds a field without adding a check.

## 2. The intervention

Two coupled parts. **No dataset, rubric severity set, gate, merge, retry, provider, or
model-configuration change.**

### 2.1 Schema (`rubric.py`, `schema.py`)

Every defect carries a closed-enum `grounding_status`:

| Status | Meaning |
|---|---|
| `in_contract_reachable` | Reachable under the interface and guarantees the task states |
| `out_of_contract` | Rests on usage the declared interface or task scope excludes |
| `contradicts_explicit_guarantee` | Rests on a premise the task text explicitly rules out |
| `factually_unverified` | Rests on library/platform behavior not demonstrated from the supplied code |

A **CRITICAL or HIGH** defect additionally requires **all** of:

1. `grounding_status == "in_contract_reachable"`;
2. `violated_requirement` — the exact task requirement not met;
3. `code_path` — the concrete path in the supplied code;
4. `trigger` — the concrete input or reachable execution condition;

each present and **non-empty after stripping whitespace**. Requirement 5 of the design
brief, "non-empty grounding evidence", is implemented as this non-emptiness rule over
(2)-(4) rather than as a fifth free-text field: a separate `evidence` string would be
satisfiable by any characters and would add schema-failure surface without adding a
check. **This interpretation is registered here so it is not a silent narrowing.**

### 2.2 Judge instruction (`judge.py` `RESPONSE_INSTRUCTION`)

The §3 prose block is replaced by a structured block that states the JSON contract, the
enum meanings, the pairing rule, and — the point of the change — that the status,
severity, explanation and fix **must not contradict each other**. Wording stays general
across all tasks and all three lenses; no case name, library, IP range, type name, or
API appears in it.

## 3. Safety invariants — all enforced by offline test

| # | Invariant | Rationale |
|---|---|---|
| S1 | Every new validation failure yields a schema error → `verdict.gate` → **UNVERIFIED** | Fail-closed; a schema error can never produce a pass |
| S2 | **No automatic demotion** of a malformed blocking defect | Auto-demotion converts missing justification into a pass-enabler; ~12 of 20 broken cases rest on a single blocker in at least one run, ~7 of them on a HIGH with zero CRITICALs |
| S3 | A model-reported `verdict: OK` alongside a blocking defect still fails validation | Pre-existing protection, must survive |
| S4 | A properly grounded single HIGH still blocks | The intervention must not weaken genuine detection |
| S5 | Automated-gate defects remain independent of judge grounding fields | `automated_defects()` hardcodes `severity="HIGH"` and never passes through `enforce_critic_schema` |
| S6 | MEDIUM/LOW findings remain reported and non-blocking | Preserves the report-don't-suppress property |
| S7 | Retry attribution unchanged | `MAX_JUDGE_RETRIES = 1`, `max_tokens`-only trigger, frozen |

## 4. Offline test matrix (required, deterministic, no provider call)

1. A defect contradicting an explicit task guarantee cannot be schema-valid at HIGH/CRITICAL.
2. A factually refuted claim cannot be schema-valid at HIGH/CRITICAL.
3. A genuine reachable security defect with a concrete trigger remains HIGH/CRITICAL and blocking.
4. A broken-case shape resting on one properly grounded HIGH remains UNVERIFIED.
5. Missing or empty grounding on a blocking defect fails closed.
6. Invalid grounding-status/severity combinations fail closed.
7. Verdict/severity inconsistency fails closed.
8. MEDIUM/LOW findings remain reported and non-blocking.
9. Automated-gate HIGH defects remain blocking without grounding fields.
10. Schema-failure retry attribution remains correct.

Fixtures are derived from the recorded finding families of the forensic analysis, but
**no case name, IP range, or dataset-specific value appears in production logic.**

## 5. What this can and cannot establish

**Offline validation can establish** that the contradiction is now *structurally
expressible and machine-checkable*: a model that classifies a finding as
out-of-contract, guarantee-contradicting, or factually unverified can no longer pair
that classification with a blocking severity, and a blocking severity with absent or
empty grounding fails closed.

**Offline validation cannot establish** that a live judge will classify honestly. Code
cannot verify that a `violated_requirement` string is a real quotation from the task, or
that a `trigger` is genuinely reachable. A model may still assert
`in_contract_reachable` and fabricate the three fields. What changes is the **cost and
observability** of doing so — from vague prose to three specific, falsifiable, recorded
assertions — not the possibility.

**Registered adverse risk, unmeasurable offline.** A model may avoid the grounding
burden by systematically assigning MEDIUM where it previously assigned HIGH. On a broken
case that is a **false pass**. This is the primary hazard of this design, it is the
inverse of the failure it fixes, and only a live run can measure it. It is registered
here **before** any run so it cannot be discovered post hoc and rationalized.

## 6. Future live validation — required before any acceptance claim

Not authorized by this document. The minimum scope that could support an acceptance
claim:

| Stage | Vehicle | N | Purpose |
|---|---|---|---|
| L0 | `engine bench` full 40-case | 1 | Smoke: schema-failure count did not explode; the contract is answerable at all |
| L1 | Baseline arm at the pre-change SHA | 4 | This is a **new configuration cluster** — no prior run baselines it |
| L1 | Intervention arm at the post-change SHA | 4 | Paired, concurrent, same session |
| L2 | Extension to N=8 per arm | +8 | Only if L1 clears the futility rule |

**Primary metric:** false-pass count on broken cases (guardrail G1, zero tolerance) —
because §5's registered adverse risk, not the aggregate score, is what this change most
plausibly breaks. **Secondary:** schema-failure rate per run; blocking-defect mass on
clean cases. **Aggregate accuracy decides nothing**, per `CLAUDE.md`.

Cost estimate at recent Sonnet full-run rates (~$0.53-0.73/run): L0 ≈ $0.7, L1 ≈ $5.0,
L2 ≈ $5.0. **No run may be started while Stage 1 of the preceding experiment remains
incomplete unless that experiment is first formally abandoned** — otherwise a third
variable lands inside an unfinished comparison.

## 7. Frozen — must not change under this registration

`eval/dataset.py` (**v6**); `rubric.SEVERITIES`; `rubric.BLOCKING`; `rubric.DIMENSIONS`;
`verdict.merge`; `verdict.gate`; `pipeline.py`; `eval/runner.py`; `runtime/gateway.py`;
`budget.py`; `config.py` `DEFAULT_MODELS`; all three `LENSES` system prompts;
`MAX_JUDGE_RETRIES = 1`; the `max_tokens` cap and retry trigger; `automated.py`;
fail-closed semantics.

The only production diff authorized is: `rubric.py` (additive constants + `DEFECT_KEYS`),
`schema.py` (added validation rules), and `judge.py` `RESPONSE_INSTRUCTION`.

## 8. Compatibility impact

- `codeagent/verify.py` `DEFECT_REPORT_KEYS` derives from `DEFECT_KEYS`, so
  `grounding_status` reaches reports automatically; the three blocking-only fields do
  **not**, preserving the existing prose-filtering intent.
- `state/db.py record_eval_case_defects` reads fixed columns via `.get()`. Extra keys are
  ignored — **no database migration, and grounding fields are not persisted.** Measuring
  the live distribution of `grounding_status` would require a schema migration on
  `.engine/state.db`, which is unbacked-up; that is deliberately **not** done here and is
  recorded as future work.
- Existing test fixtures that construct critic defects require the new required key.
  Fixtures exercising `verdict.merge`/`gate` only are unaffected.
