# Pre-registration — Answer-Budget Hardening, Phase 1

**Status: PRE-REGISTERED. No paid call has been made under it. No production code changed.**

| | |
|---|---|
| Registered | 2026-09-02 |
| Branch | `feature/agent-capabilities-layer` |
| HEAD at registration | `043e8d5818b81cab8295ccf567cd3d35e0c892ad` |
| Judge model | `claude-sonnet-5` (current production judge, `config.DEFAULT_MODELS`) |
| Dataset | v4, benchmark v2 — **no benchmark run is part of this experiment** |
| Scope exclusion | R-a / off-lens blocking is **entirely out of scope**: not implemented, not scored, not mentioned in any metric below |

## 0. The finding that constrains this design

**There is no thinking-budget mechanism on `claude-sonnet-5`.** This was checked before any
arm was proposed, and it changes what the phase can be.

`thinking={"type": "enabled", "budget_tokens": N}` — the only API control that reserves
answer capacity by bounding reasoning — is **removed on Sonnet 5 and returns a 400**. The
installed SDK still carries the type (`ThinkingConfigEnabledParam` in `anthropic 0.120.2`),
so this fails at the API, not at the type checker. Reachable controls, verified against the
installed SDK's `messages.create` signature:

| control | shape at `anthropic 0.120.2` | on `claude-sonnet-5` | reserves answer capacity? |
|---|---|---|---|
| `thinking={"type":"enabled","budget_tokens":N}` | present in SDK | **400 — removed** | would have; unavailable |
| `thinking={"type":"disabled"}` | `ThinkingConfigDisabledParam` | accepted | **yes, absolutely** — 0 thinking tokens, all 1600 available to the answer |
| `thinking={"type":"adaptive"}` | `ThinkingConfigAdaptiveParam` | accepted; **current implicit default** | no |
| `output_config={"effort": ...}` | `low\|medium\|high\|xhigh\|max` | accepted; default `high` | soft only |
| `output_config={"format": ...}` | `JSONOutputFormatParam` | accepted | different mechanism (output shape, not budget split) |
| `max_tokens` | int | accepted | no |
| `task_budget` | **absent from `OutputConfigParam`** | unreachable from this SDK; min 20,000 anyway | no |

So "bounded thinking" does not exist here. The only reservation available is **elimination**:
thinking on, or thinking off. Everything below is written against that constraint rather
than against the mechanism the phase title assumes.

**The provider sends neither control today.** `anthropic_provider.generate()` passes
`model`, `system`, `messages`, `max_tokens`, `temperature` (omitted for Sonnet 5) and
`timeout`, and nothing else. `LLMGateway.generate()` has no `thinking` or `effort`
parameter either. Sonnet 5 therefore runs **adaptive thinking at default effort `high`** on
every judge lens call, which is the configuration all stored evidence describes.

## 1. Prior art — why the obvious levers are closed

Each was tried at this model and reverted. `BASELINE.md` records the standing conclusion:
*"no cap-side lever should be re-attempted on this evidence without a new mechanism."*

| phase | intervention | outcome | commits |
|---|---|---|---|
| 9C | cap 800 to 1600 | kept (current) | `bf31684` |
| 9C.2 | `effort="medium"` on judge lenses only | **false pass on `quality-04-broken`** — one defect moved HIGH to MEDIUM; `quality-01-broken` left blocked only by fail-closed | `25d9d76`, reverted `08c17a6` |
| 9C.3 | cap 1600 to 2000 | thinking expanded to fill the new ceiling | `cb32e1f`, reverted `b1f06d7` |
| 9E | retry once on `stop_reason == max_tokens` | kept, but its premise fails on the target case | `86f28ec` |

9C.2 is the load-bearing precedent: **reducing reasoning on this judge has already produced
a false pass once, on a named case.** Any arm that reduces reasoning inherits that prior and
must be guarded against exactly that failure, on exactly that case.

9C.2 also proves the plumbing is feasible and how it should look: an optional per-call
argument threaded Provider to Gateway to call site, `None` meaning "omit the field
entirely", typed as a `Literal` so a typo fails in mypy rather than as a 400.

## 2. The measured baseline

All figures below are read from a scratchpad copy of `.engine/state.db`, from runs 43 and 44.
Both runs and HEAD are the same judge configuration: **`git diff a600d20 HEAD -- src/`
returns empty**, and `git diff e002b6b a600d20` is empty across `verification/`, `runtime/`,
`providers/`, `config.py` and `eval/`. Run 43 is VOID as a run and is used here only as
per-call exploratory data, which `BASELINE.md` explicitly permits.

### Target — `security-04-clean`, deterministic zero-answer truncation

| run | lens | output | thinking | text chars | stop_reason |
|---|---|---|---|---|---|
| 43 | correctness | 1600 | 1599 | 0 | `max_tokens` |
| 43 | correctness:retry | 1600 | 1600 | 0 | `max_tokens` |
| 43 | security | 1600 | 1600 | 0 | `max_tokens` |
| 43 | security:retry | 1600 | 1599 | 0 | `max_tokens` |
| 44 | correctness | 1600 | 1600 | 0 | `max_tokens` |
| 44 | correctness:retry | 1600 | 1600 | 0 | `max_tokens` |
| 44 | security | 1600 | 1599 | 0 | `max_tokens` |
| 44 | security:retry | 1600 | 1598 | 0 | `max_tokens` |

**Registered baseline: 0/8 answer emission** on `{correctness, security}`. Every attempt
spent essentially the entire budget thinking and emitted zero characters. `BASELINE.md`
records 4/4 within run 44; run 43 replicates it independently at the same configuration.

Honest limit on that denominator: the 8 calls are 2 lenses x 2 runs x 2 attempts, not 8
independent draws. They are clustered, and section 5's drift check exists because of it.

The `code-quality` lens on the same case does **not** truncate — 1366/1149/626 chars in
run 43, 259/240/32 chars in run 44. The failure is lens-specific, and only the two
truncating lenses are in the target set.

### Near-cap control — `security-02-clean`, stochastic

| run | lens | output | thinking | text chars | stop_reason |
|---|---|---|---|---|---|
| 44 | correctness | 1394 | 1053 | 887 | `end_turn` |
| 44 | security | 1346 | 742 | 1466 | `end_turn` |
| 43 | security | 1600 | 1476 | 317 | `max_tokens` |
| 43 | security:retry | 1600 | 958 | 1668 | `max_tokens` |

This is the right control precisely because it is *not* deterministic: it truncated in
run 43 and the retry rescued it, and it completed on both lenses in run 44 with 206 and 254
tokens of headroom. It separates "budget exhausted, retry works" from the target's "budget
exhausted, retry provably does not".

It is also a calibration probe. Its run-44 UNVERIFIED comes from **genuine findings, not
truncation** — `security` lens `SECURITY/CRITICAL` (filename sanitisation) plus `correctness`
lens `CORRECTNESS/HIGH`. If an arm that reduces reasoning makes those findings disappear,
the case's verdict moves toward its expected `OK` and **accuracy improves while detection
degrades**. That trap is named here in advance: on this case, an arm moving toward the
expected verdict is not evidence of success.

### Safety case — `quality-04-broken`

Run 44 carries 4 defects, 2 blocking: `code-quality` lens `CODE-QUALITY/HIGH` and
`correctness` lens `CORRECTNESS/HIGH`, both reporting the same underlying finding (extract
the literal `100` to a named constant). Margin = 2 blockers, both HIGH, both one step above
the MEDIUM that 9C.2 produced.

This is the only case outside the two named in the brief. It is included because it is the
case a reasoning-reduction arm has **already been measured to break**, and a safety criterion
that omits it would be weaker than the evidence that already exists.

### Thin-margin context (not in this phase; sizes Phase 2)

Five of run 44's 20 broken cases rest on a single blocking defect: `correctness-04-broken`
(correctness/CRITICAL), `correctness-05-broken` (correctness/CRITICAL), `edge_case-01-broken`
(correctness/HIGH), `quality-05-broken` (correctness/HIGH), `security-03-broken`
(security/CRITICAL). Note this is a different, looser count than `BASELINE.md`'s "8 of 20
rested on a single **on-lens** blocker" — that figure excludes off-lens blockers. Neither is
quoted for the other.

### Data that cannot be used

Run 42 (Haiku) has `thinking_tokens`, `text_chars` and `stop_reason` unpopulated for all
120 calls — those columns were added after it ran. Its `security-04-clean x correctness`
call hitting `output_tokens = 800`, exactly the then-current cap, is evidence of reaching the
cap and **nothing more**; its stored `text_chars = 0` is a missing column, not a measurement
of an empty answer.

## 3. Hypothesis

> **H1.** On `security-04-clean x {correctness, security}`, a lens call issued with
> `thinking={"type":"disabled"}` and every other request field unchanged emits a schema-valid
> critic JSON, where the current configuration emits zero characters.

Falsifiable, one sentence, and stated against a 0/8 measured baseline.

The mechanism claim it tests: the zero-text failure is caused by adaptive thinking consuming
the entire `max_tokens` allocation, and removing thinking returns that allocation to the
answer. If H1 fails, that causal story is wrong and the remaining explanation — that these
two lens/case pairs fail for a reason unrelated to the budget split — becomes the live one.

## 4. Arms

One set of request fields differs. Nothing else.

- **Arm A — current.** `model=claude-sonnet-5`, `system=LENSES[lens]`, the prompt built
  exactly as `run_judge_gates` builds it, `max_tokens=1600`, `temperature` omitted, **no
  `thinking` field, no `output_config`** — i.e. adaptive thinking at default effort `high`.
- **Arm B — thinking disabled.** Byte-identical to Arm A plus `thinking={"type":"disabled"}`.
  `output_config` is still omitted, so effort is untouched. **This is not 9C.2**: effort is
  not lowered, the cap is not raised, and no prompt changes.

**The production shape this is designed for, stated now so the measurement is honest.**
If Phase 2 is ever authorised, Arm B would be applied **only on the retry path** — only to a
call that has already returned `stop_reason == "max_tokens"` with an unparseable response,
i.e. a call whose current outcome is a guaranteed fail-closed `UNVERIFIED`. The changed
configuration could then never run on a call that succeeded, so it could never downgrade a
severity the judge already committed to. The blast radius is bounded structurally, not
statistically.

**Phase 1 deliberately measures Arm B on first attempts instead**, on cases that mostly do
not truncate at all. That is *harsher than the production shape* — in production, most of
these Arm B calls would never happen. Registered as a conservative modelling choice, in the
same spirit as Phase 4C's `automated_passed=True`.

## 5. Design

| set | case | lenses | Arm A reps | Arm B reps | calls |
|---|---|---|---|---|---|
| target | `security-04-clean` | correctness, security | 2 (drift check) | 4 | 4 + 8 |
| control | `security-02-clean` | correctness, security | 4 | 4 | 8 + 8 |
| safety | `quality-04-broken` | correctness, code-quality | 4 | 4 | 8 + 8 |

**44 paid lens calls**, plus at most 3 in Stage 0.

**Why Arm A is only 2 replicates on the target.** The registered baseline is the stored 0/8,
measured at a source-identical configuration with the proving command in section 2;
re-measuring it at full N would be redundant spend on a deterministic outcome. The 4 fresh
Arm A calls are a **drift check**, not the baseline — they exist to catch the case where the
model's behaviour on this input has changed since 2026-09-02, which would invalidate the
comparison (see stop condition 4).

**Harness, and its one deviation from Phase 4C.** Phase 4C called the real `run_judge_gates`
through the real gateway. This experiment **cannot**: the parameter under test does not exist
anywhere in `src/engine`. The harness must therefore construct its own Anthropic client and
issue `messages.create` directly. To keep everything that matters identical, it must import
and reuse, unmodified:

- `LENSES` and `RESPONSE_INSTRUCTION` from `verification/judge.py`
- the prompt template from `run_judge_gates` — the task text, then the concatenated code
  snapshot, then `RESPONSE_INSTRUCTION`, assembled with the same f-string
- the case's `task_text` and `files` from `eval/dataset.py`, written to a temp workspace and
  read back through `pipeline.read_code_snapshot`
- `judge._parse_critic` / `schema.enforce_critic_schema` for scoring
- `BudgetController`, driven by the harness, for the hard ceiling

Only the transport differs. `conn=None`, `run_id=None`: **no row is written to
`.engine/state.db`**, and no `BASELINE.md` table row exists or should exist for this
experiment. The harness does not invoke the production retry — attempts are counted by the
harness — so no call is silently doubled.

Order is shuffled per replicate under seed **20260902**.

## 6. Metrics

- **Primary (benefit).** Per-call **answer emission** on the target set: a call counts as
  emitting iff `_parse_critic` returns zero schema errors. Arm B k/8 against the registered
  Arm A baseline 0/8.
- **Guardrail 1 (safety, hard).** On `quality-04-broken`, whether the case still carries at
  least one `CRITICAL`/`HIGH` defect across its two lenses under Arm B — i.e. whether
  `verdict.gate` would still block it.
- **Guardrail 2 (calibration).** On `security-02-clean`, whether the `SECURITY/CRITICAL` and
  `CORRECTNESS/HIGH` findings survive under Arm B.
- **Secondary, recorded, deciding nothing.** Output-token composition (thinking vs answer)
  per call, `stop_reason`, `text_chars`, full defect list with lens/category/severity, schema
  failures, latency, spend.

No accuracy figure will be produced by this experiment, and none may be quoted from it.
Sigma = 0.92 is not applicable here — that is the aggregate-accuracy noise floor across 40
cases; this experiment's primary metric is a per-call proportion, unaffected by it.

## 7. Sample size

The primary metric is a proportion against a 0/N baseline, so `experiment-design`'s Fisher
table governs, not the sigma table. At **N = 8 per arm**: 5/8 gives p = 0.026 and is
significant; 4/8 gives p = 0.077 and is **not** sufficient; 3/8 is noise.

8 target calls per arm = 2 lenses x 4 replicates. That is the minimum N at which this
question can return a significant answer at all — at N = 4 only an all-or-nothing 4/4 clears
— which is why the design is not smaller.

## 8. Decision rules

Written before the first paid call. Not to be edited afterward.

- **REJECT (hard, zero tolerance).** Any Arm B replicate of `quality-04-broken` in which no
  `CRITICAL`/`HIGH` defect survives across both lenses — i.e. the case would return `OK`
  where Arm A blocks. One occurrence rejects the arm and the batch stops immediately.
- **BENEFIT SHOWN.** All three must hold: (a) zero REJECT events; (b) **at least 5/8** Arm B
  target calls emit a schema-valid critic; (c) the effect appears on **both** target lenses at
  **at least 2/4** each, so a single-lens artifact cannot carry the result.
- **INCONCLUSIVE.** Zero REJECT events and fewer than 5/8, or 5/8+ concentrated in one lens.

**BENEFIT SHOWN authorizes no production change.** It establishes that a thinking-disabled
call can rescue this specific deterministic failure. Implementation requires a separate
Phase 2 registration and, at minimum, a broken-case safety batch across the five thin-margin
cases named in section 2 — none of which is measured here.

Guardrail 2 firing without Guardrail 1 firing is recorded as a **registered adverse finding**,
not a rejection: losing a genuine finding on a clean case is evidence of calibration loss that
a clean-case verdict cannot express, and it must be reported even though it moves
`security-02-clean` *toward* its expected verdict.

## 9. What a negative result looks like

Three distinct negatives, all real results, all recorded with equal weight:

1. **Mechanism wrong.** Arm B emits 4/8 or fewer on the target. Disabling thinking does not
   rescue `security-04-clean`; the zero-text failure is not simply "thinking ate the budget",
   and the answer-budget hypothesis in its current form is dead for this model.
2. **Mechanism right, cost too high.** Arm B emits 5/8 or more but triggers REJECT on
   `quality-04-broken`. Answer capacity and detection quality are coupled on this judge: there
   is no free reservation, and 9C.2's result generalises beyond effort.
3. **No mechanism reachable.** Stage 0 fails (see stop condition 1). Recorded as the phase's
   finding — the API offers no way to reserve answer capacity on this model — and no further
   call is made.

## 10. Cost

Basis: **per-call spend measured on these exact cases and lenses in run 44**, not carried from
another corpus. Rates solved from stored pairs — input **$2.00/MTok**, output **$10.00/MTok**
— reproducing every stored `actual_spend` exactly. (Phase 4C's cost basis under-ran by 1.70x
because it was carried from a different fixture set; this one is not.)

| call | measured Arm A spend |
|---|---|
| `security-04-clean` x correctness | $0.0174960 |
| `security-04-clean` x security | $0.0175060 |
| `security-02-clean` x correctness | $0.0150300 |
| `security-02-clean` x security | $0.0145600 |
| `quality-04-broken` x correctness | $0.0029900 |
| `quality-04-broken` x code-quality | $0.0062120 |

| | |
|---|---|
| Arm A (20 calls) | **$0.2252** |
| Arm B (24 calls), expected — answer-sized output, zero thinking | **$0.1530** |
| Arm B, worst case — every call emits a full 800-token JSON | $0.2258 |
| Stage 0 probe (3 calls or fewer; a 400 is unbilled) | $0.02 or less |
| **expected total** | **~$0.40** |
| **worst realistic** | **~$0.47** |
| **hard ceiling** | **$0.55**, enforced by `BudgetController.planned_budget` |

## 11. Stop conditions

1. **Stage 0 — mechanism probe, before anything else.** One Arm B call on
   `quality-04-broken x correctness` (the cheapest call in the set, $0.0030) to confirm the API
   accepts `thinking={"type":"disabled"}` on `claude-sonnet-5`. If it returns a 400, the
   experiment **does not run**, outcome 3 of section 9 is recorded, and the phase ends. A
   rejected request is unbilled, so this costs nothing when it matters most. Section 0's claim
   that `budget_tokens` returns a 400 is documentation, not a measurement made in this
   repository; Stage 0 converts the claim that matters into a measurement.
2. **Safety.** One REJECT event: stop immediately.
3. **Budget.** `BudgetController` raises at $0.55: stop, report partial. Do not re-plan or top
   up mid-batch.
4. **Baseline drift.** If the Arm A drift check does not reproduce the stored profile — both
   target calls hitting `stop_reason = max_tokens` with zero text — the stored 0/8 baseline no
   longer describes current behaviour. Record and stop; do not compare Arm B against a stale
   baseline.
5. **Contamination.** More than 15% of Arm A calls returning schema errors outside the target
   set voids the measurement. Recorded, not fixed — the answer-budget question is this
   registration; the semantic schema-failure class (24 of 40 recorded failures are verdict
   inconsistencies) is a separate one and must not be bundled in.

## 12. Frozen — must not change

`LENSES`, `RESPONSE_INSTRUCTION`, the rest of `judge.py`, `schema.py`, `rubric.py`,
`verdict.py`, `eval/dataset.py`, `eval/runner.py`, `verification/pipeline.py`,
`runtime/budget.py`, `config.DEFAULT_MODELS` (the judge model stays `claude-sonnet-5`),
`max_tokens = 1600`, and the benchmark itself. R-a and off-lens blocking authority are out of
scope entirely.

**No `src/engine` change is part of Phase 1.** The harness is read-only against the engine.
Threading `thinking` through Provider to Gateway to `run_judge_gates` — following the
`timeout_seconds` precedent, as `25d9d76` did for `effort` — is Phase 2 work: it touches
`gateway.py`, which is on the `git-safety` measured path, and requires its own explicit
approval and its own registration.
