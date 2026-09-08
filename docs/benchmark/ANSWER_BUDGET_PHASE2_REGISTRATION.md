# Pre-registration — Answer-Budget Phase 2: production retry-path implementation

**Status: PRE-REGISTERED. No production code changed. No paid call has been made under it.**

| | |
|---|---|
| Registered | 2026-09-08 |
| Branch | `feature/agent-capabilities-layer` |
| HEAD at registration | `c2a5af2adf33968346405e93a83ea5dd1c91bb84` |
| Judge model | `claude-sonnet-5` (unchanged, `config.DEFAULT_MODELS`) |
| Evidence basis | `ANSWER_BUDGET_PHASE1C_RESULT.md` (BENEFIT SHOWN) + stored runs 43-44 |
| Supersedes | nothing. Phase 1 and Phase 1B stay VOID; Phase 1C stands as written |
| Scope exclusion | R-a / off-lens blocking is **entirely out of scope**: not implemented, not scored, not referenced |

## 0. What Phase 1C authorizes, and what it does not

Phase 1C established one thing: on `security-04-clean × {correctness, security}`, a lens
call issued with `thinking={"type": "disabled"}` emits a schema-valid critic 8/8 where the
current configuration emits 0/8. It did **not** measure the production path, because its
harness deliberately did not invoke the production retry.

Phase 2 is the first change to `src/engine` in this line of work. It carries its own
acceptance and rejection criteria and must reach its own verdict.

> **Phase 1C's BENEFIT SHOWN is the reason to attempt Phase 2. It is not evidence that
> Phase 2 works, and it is explicitly not evidence about benchmark accuracy.** See section 2.

## 1. The production baseline, measured

`experiment-design` requires a measured rate at the current configuration, not an
assumption. Read from `.engine/state.db` (scratchpad copy, 2026-09-08).

**The Phase 9E retry has fired exactly five times in the entire measurement history** — all
in runs 43 and 44, the only two `claude-sonnet-5` runs. All 42 Haiku runs produced zero
at-cap judge calls and therefore zero retries.

| run | case | lens | attempt 1 | retry | retry emitted? |
|---|---|---|---|---|---|
| 43 | `security-02-clean` | security | `max_tokens`, think 1476, 317 chars | `max_tokens`, think 958, 1668 chars | **no** |
| 43 | `security-04-clean` | correctness | `max_tokens`, think 1599, 0 chars | `max_tokens`, think 1600, 0 chars | **no** |
| 43 | `security-04-clean` | security | `max_tokens`, think 1600, 0 chars | `max_tokens`, think 1599, 0 chars | **no** |
| 44 | `security-04-clean` | correctness | `max_tokens`, think 1600, 0 chars | `max_tokens`, think 1600, 0 chars | **no** |
| 44 | `security-04-clean` | security | `max_tokens`, think 1599, 0 chars | `max_tokens`, think 1598, 0 chars | **no** |

> **Registered baseline: the production retry emits a schema-valid critic in 0 of 5
> firings (0/4 on `security-04-clean`).**

This is the rate Phase 2's primary metric is measured against. It is consistent with — and
strictly more informative than — Phase 1C's registered `0/8`, which was drawn from the same
two runs and already included these four retry calls.

BASELINE.md line 80 records the mechanism: the Phase 9E premise that an identical resample
is "a fresh draw from a heavy-tailed distribution" **does not hold on this input**. Four of
four attempts across two lenses burned ~1600 thinking tokens and emitted nothing. The
outcome is effectively deterministic, and the current retry buys nothing for ~$0.064 per run.

## 2. The finding that governs this registration

**Rescuing these calls cannot improve benchmark accuracy, and the registration says so
before any run.**

`verdict.gate()` (`src/engine/verification/verdict.py:17-24`) returns `UNVERIFIED` for
*both* a schema error and a blocking defect:

```python
def gate(merged, automated_passed, schema_errors):
    if schema_errors:      return "UNVERIFIED"
    if not automated_passed: return "UNVERIFIED"
    if _has_blocking(merged): return "UNVERIFIED"
    return "OK"
```

In run 44, `security-04-clean` is `expected=OK, actual=UNVERIFIED` via the **first** branch:
`correctness` and `security` both `schema_valid = 0`. It is the only case in run 44 whose
failure is caused by truncation.

All **8 of 8** Phase 1C target Arm B calls returned `verdict: FAIL` carrying at least one
CRITICAL/HIGH defect:

| replicate | lens | verdict | blocking defects |
|---|---|---|---|
| 1 | security / correctness | FAIL / FAIL | 2 / 2 |
| 2 | security / correctness | FAIL / FAIL | 2 / 1 |
| 3 | security / correctness | FAIL / FAIL | 3 / 1 |
| 4 | security / correctness | FAIL / FAIL | 2 / 2 |

So a successful Phase 2 rescue moves `security-04-clean` from *UNVERIFIED-by-schema-error*
to *UNVERIFIED-by-blocking-defect*. **Same verdict. `correct_verdicts` stays 36/40.**

### 2.1 What Phase 2 is actually for

The value is diagnostic, not numeric: the reviewer currently receives a truncation and zero
information; afterwards they receive an auditable defect list. That is a real product
improvement and it is the honest justification for the change. It is **not** an accuracy
improvement and must never be reported as one.

### 2.2 Verdict monotonicity — a structural safety property

A case carrying a schema error is already `UNVERIFIED`, so removing that error can only move
it toward `OK`:

- **expected-OK case:** `UNVERIFIED → OK` (accuracy +1) or `UNVERIFIED → UNVERIFIED` (no change).
- **expected-UNVERIFIED (broken) case:** `UNVERIFIED → OK` is a **`false_pass`**, or no change.

**Phase 2 can never turn a passing case into a failing one.** It is provable offline
(test P8, section 6) and it reduces the entire risk surface to exactly one event: a
rescued retry on a *broken* case whose critic carries no blocking defect. That single event
is the hard REJECT of section 8.

No broken case has ever truncated in any stored run — the only two cases that have are
`security-02-clean` and `security-04-clean`, both clean. The risk is therefore unrealized,
not absent, and it is guarded rather than argued away.

## 3. Hypothesis

> **H2.** In the production judge path, when a lens call terminates with
> `stop_reason = max_tokens` and an unparseable response, a retry issued with
> `thinking={"type": "disabled"}` and every other request field unchanged emits a
> schema-valid critic, where the current identical-resample retry emits none.

Baseline: **0/5** (section 1). Falsifiable: section 10.

**H2 is a statement about answer emission on the retry path only.** It makes no claim about
`correct_verdicts`, and section 2 registers in advance that the expected accuracy change is
**zero**.

## 4. Implementation plan

One request field, one call site. `thinking_disabled: bool = False` is threaded from the
judge's retry down to the Anthropic request; every other call in the engine keeps the
default and its request shape is byte-identical to today's.

### 4.1 Layer by layer

**(1) `src/engine/providers/anthropic_provider.py` — the only place the wire format exists**

```python
def generate(self, messages, model, system=None, max_tokens=4096,
             temperature=0.0, timeout_seconds=None,
             thinking_disabled: bool = False) -> GenerationResult:
    response = self._client.messages.create(
        ...,
        thinking={"type": "disabled"} if thinking_disabled else omit,
    )
```

`omit` — not `None`, not `NOT_GIVEN` — is the SDK's own default for `thinking`
(`ThinkingConfigParam | Omit`, SDK 0.120.2, verified). Passing `omit` when the flag is
False sends **no `thinking` field at all**, which is exactly Phase 1C's Arm A definition and
exactly today's request. Confirmed: `ThinkingConfigDisabledParam` is
`{"type": Required[Literal["disabled"]]}` — the registered literal, nothing else.

**(2) `src/engine/providers/base.py` — the `Provider` protocol**

Same keyword with the same default. Required or `mypy` rejects the Gateway's call.

**(3) `src/engine/providers/{openai,google,ollama}_provider.py`**

Signature only. All three are `raise NotImplementedError` placeholders for M2; no body changes.

**(4) `src/engine/runtime/gateway.py` — MEASURED PATH**

`generate()` gains `thinking_disabled: bool = False` and forwards it unconditionally.
Budget, timeout, metric recording, and error handling are untouched.

**(5) `src/engine/verification/judge.py` — MEASURED PATH**

The whole behavioural change, three lines:

```python
def ask(agent_name: str, *, thinking_disabled: bool = False,
        lens_system: str = lens_system) -> GenerationResult:
    return gateway.generate(..., thinking_disabled=thinking_disabled)

response = ask(f"judge:{lens_name}")                                # default False
retried  = ask(f"judge:{lens_name}:retry", thinking_disabled=True)  # only True call site
```

The retry trigger — `if errors and response.stop_reason == _BUDGET_EXHAUSTED` — and
`MAX_JUDGE_RETRIES = 1` are **not touched**.

### 4.2 Two rejected alternatives, recorded

- **Pass the Anthropic dict through (`thinking: ThinkingConfigParam | None`).** Rejected:
  it leaks a provider wire format into a provider-neutral Protocol and creates a
  configuration knob (`{"type": "enabled", "budget_tokens": N}`) for a use case that does
  not exist. CLAUDE.md forbids exactly that. A boolean admits one behaviour and no more.
- **Have the judge call the provider directly and leave the Gateway alone.** Rejected: it
  violates architecture Rule B (only `runtime/gateway.py` may import `providers/`) and
  bypasses budget enforcement and metric recording.

**Forward unconditionally rather than only when True.** A conditional would spare ~14
mechanical test-stub signature updates, but it adds a behavioural branch to a measured-path
file. Per CLAUDE.md, a branch in the engine widens the variance surface; a parameter with a
constant default does not. The test-stub edits are off the measured path and fail loudly
(`TypeError`) rather than silently.

## 5. Files to touch

**Measured path — require explicit per-turn approval under `git-safety`:**

| file | change |
|---|---|
| `src/engine/verification/judge.py` | `ask()` keyword + one `thinking_disabled=True` at the retry call site |
| `src/engine/runtime/gateway.py` | `generate()` keyword, forwarded to the provider |

**Off the measured path:**

| file | change |
|---|---|
| `src/engine/providers/anthropic_provider.py` | wire-format translation (see §5.1) |
| `src/engine/providers/base.py` | `Provider` protocol signature |
| `src/engine/providers/openai_provider.py` | signature only |
| `src/engine/providers/google_provider.py` | signature only |
| `src/engine/providers/ollama_provider.py` | signature only |
| `tests/test_verification.py` | 4 stubs + amended/new tests (§6) |
| `tests/test_gateway.py` | 1 stub + new wire test |
| `tests/codeagent_harness.py` | 3 stubs |
| `tests/test_orchestrator.py` | 2 stubs |
| `tests/test_agents.py`, `test_codeagent_verify.py`, `test_manager.py` | 1 stub each |
| `tests/test_eval_runner.py` | 1 untyped stub (line 599) |

14 stub signatures across 8 test files. The four stubs using `*args, **kwargs`
(`test_api.py`, `test_codeagent_app.py`, `test_debugagent_rootcause.py`,
`test_eval_runner.py:29`) need no change.

**Explicitly not touched:** `dataset.py`, `runner.py`, `pipeline.py`, `rubric.py`,
`schema.py`, `verdict.py`, `budget.py`, `config.py`, `LENSES`, `RESPONSE_INSTRUCTION`,
`max_tokens = 1600`, and the `.engine/state.db` schema.

### 5.1 Governance finding — registered, not silently acted on

`src/engine/providers/anthropic_provider.py` decides what request is actually sent to the
judge model. That is as decisive for the measured configuration as `judge.py`, yet the file
is **not** on the `git-safety` measured-path list. This is the same gap `config.py` had
before 2026-09-02, when `83a4000` changed the judge model without tripping any approval gate.

**Recommendation: add `providers/anthropic_provider.py` to the measured-path list.** It is a
change to `.claude/skills/git-safety/SKILL.md`, requires its own approval, and is **not**
bundled into the Phase 2 implementation commit.

## 6. Offline test plan

Zero-cost. Every hard invariant gets a test that fails if it breaks.

| # | invariant | test | status |
|---|---|---|---|
| P1 | first attempt unchanged | initial gateway call carries `thinking_disabled=False`; provider receives `thinking=omit` | **new** |
| P2 | valid initial never retried or replaced | `test_a`, `test_g`, `test_h` | existing, must pass unchanged |
| P3 | retry only on the truncation condition | `test_unparseable_response_that_completed_normally_is_not_retried` | existing, unchanged |
| P4 | only the retry gets the flag | retry call `thinking_disabled=True`, initial `False`, asserted in one test | **new** |
| P5 | `max_tokens` unchanged | `test_retry_reuses_the_same_prompt_and_cap_as_the_first_attempt` | existing, unchanged |
| P6 | everything else identical between attempts | `test_i_retry_repeats_every_call_argument_except_the_agent_label` | **AMENDED — see §6.1** |
| P7 | fail-closed unchanged | `test_d`, `test_e`, `test_f` | existing, must pass unchanged |
| P8 | verdict monotonicity (§2.2) | a rescued lens moves a case `UNVERIFIED → {UNVERIFIED, OK}` and never the reverse | **new** |
| P9 | exact wire format | `AnthropicProvider` sends `{"type": "disabled"}` when True and omits the field when False | **new**, against a fake SDK client |
| P10 | never a second retry | `test_i_retry_count_never_exceeds_one_per_lens`, `test_l_a_retry_is_never_itself_retried` | existing, unchanged |
| P11 | architecture rules intact | `tests/test_architecture.py` | existing, must pass unchanged |

### 6.1 The one amended test, and why that is not a weakened invariant

`test_i_retry_repeats_every_call_argument_except_the_agent_label`
(`tests/test_verification.py:930`) currently asserts:

```python
differing = {k for k in initial if initial[k] != retry[k]}
assert differing == {"agent_name"}
```

**This is the test that exists to catch exactly this change, and Phase 2 changes it.** It
becomes:

```python
assert differing == {"agent_name", "thinking_disabled"}
assert initial["thinking_disabled"] is False
assert retry["thinking_disabled"] is True
```

The assertion stays exhaustive — it is still an exact set equality over the full gateway
keyword set, so an edit that also varied the model, prompt, cap, timeout or attribution on
the second attempt still fails. Two named fields may differ instead of one, and the new
field's value is pinned in both directions. **No assertion is deleted, relaxed to a subset
check, or replaced by a weaker comparison.** Recording this here, before the edit, is the
point: an amendment made silently during implementation would be indistinguishable from
removing the guard.

### 6.2 Gates

`ruff check .`, `mypy src/engine`, `pytest` — all three must pass. **The gates are the sole
success criterion for the code change.** Per CLAUDE.md, benchmark accuracy is never a
success criterion for a code change, and the live validation of section 7 verifies the
hypothesis, not the code.

## 7. Live validation plan

Runs only after the offline gates pass and the implementation is committed.

**Preconditions (`git-safety`):** `git status --porcelain` empty; `git rev-parse HEAD`
recorded; SHA matches the Phase 2 implementation commit. Explicit user approval in the turn
the run happens — this registration authorizes nothing on its own.

### 7.1 The vehicle: `engine bench --category security`

Two full 40-case runs are the wrong instrument for this hypothesis. Phase 2 changes one
request field on one call site that fires only after a truncated judge call, and **every
retry firing in the entire measurement history — 5 of 5 — occurred inside the `security`
category** (`security-02-clean`, `security-04-clean`). The other 165 initial Sonnet lens
calls on record, spanning the three other categories, produced zero `max_tokens`
terminations and therefore zero retries.

`cli.py`'s `bench --category security` selects exactly those 10 cases via
`runner.select_cases` and changes nothing else: same `LLMGateway.from_config`, same
`BudgetController`, same `DEFAULT_MODELS["anthropic"]["judge"]`, same `run_verification` →
`run_judge_gates` → `gateway.generate` → `AnthropicProvider.generate` chain, same lens
prompts, same `max_tokens = 1600`, same DB writes. Per call the request is byte-identical
to a full run; only the case list is shorter. It is the **smallest production-path unit the
CLI exposes** — there is no `--case` flag, and adding one would be a production code change
this registration forbids.

| | full run | `--category security` |
|---|---|---|
| cases | 40 | 10 |
| initial judge calls | 120 | 30 |
| retry firings observed | 3 (run 43), 2 (run 44) | 3 (run 43), 2 (run 44) — **all of them** |
| initial calls with `thinking_tokens > 0` | 47/105, 55/120 | **20/30 in both runs** |
| judge spend | $0.5455 | $0.24096 / $0.22401 |
| wall time | ~11.9 min | **~4.2-4.8 min** |

The trigger population is retained in full; the ~75% of calls that have never fired the
trigger are not paid for.

**Operational consequence.** Run 43 was VOIDed by a ~10-minute external harness timeout at
full spend. A ~5-minute run fits inside that window with margin, so the dominant VOID risk
of the superseded design is removed rather than budgeted for.

### 7.2 Stages

**Stage 0 — free.** `engine bench --category security --dry-run`: zero LLM calls, validates
the dataset and budget and prints the plan. A non-zero exit stops the sequence at $0.00.

**Stage 1 — one run, the invariant gate.** Every deterministic invariant below (I1-I7) is
decidable from this single run. A breach is a REJECT on its own and the sequence stops
there, having spent ~$0.22 rather than ~$1.07.

**Stage 2 — one run, the endpoint.** Runs only if Stage 1 is clean. Its purpose is to
accumulate retry firings to *n* ≥ 3, the point at which §8.1's primary metric becomes
evaluable at all. Expected cumulative firings after Stage 2: **4-6**.

**Extension (pre-registered, carried over unchanged).** If cumulative firings are still
fewer than 3, run up to 2 more, capped at **4 runs total**. It fires on the *count of
trigger firings*, never on how close a result came to a threshold.

**Both stopping rules are independent of the endpoint.** Stage 1 → Stage 2 is gated on
invariant breaches; the extension on firing count. Neither reads *k*, the number of retries
that emitted, so the primary metric is evaluated exactly once, on the pooled firings, after
the sequence stops. This is a fixed-information design, not optional stopping.

### 7.3 Observations

Every observation comes from tables that already exist. No schema change, no new
persistence. Per run: 10 cases, 30 initial judge calls, 30 lens rows, 30 automated-gate rows.

**Invariants — deterministic, decidable in Stage 1 alone. Each is a REJECT if it fails.**

| # | proves | source | required |
|---|---|---|---|
| I1 | **first attempt unchanged (paired)** | for every `judge:<lens>:retry` row, its sibling `judge:<lens>` row at the same `(run_id, task_id)` | `thinking_tokens > 0` on **every** such initial call (baseline 1476-1600 on 5/5) |
| I2 | **first attempt unchanged (aggregate)** | initial judge calls with `thinking_tokens > 0` | **≥ 10 of 30 per run** — baseline 20/30 and 20/30; P(≤10) = 1.9 × 10⁻⁴ under unchanged behaviour, and a leaked flag gives 0 |
| I3 | **no disabled signature on a first attempt** | initial calls with `thinking_tokens = 0` **and** `stop_reason = 'max_tokens'` **and** `text_chars = 0` | **0** |
| I4 | **flag only on a truncation retry** | every `judge:%:retry` row's sibling initial call | `stop_reason = 'max_tokens'`, no exceptions |
| I5 | **a valid initial is never retried** | initial calls with `stop_reason != 'max_tokens'` that carry a retry row | **0** (27-28 observations per run) |
| I6 | **retry thinking disabled at the wire** | `judge:%:retry` rows → `thinking_tokens`, which `AnthropicProvider` reads from `usage.output_tokens_details` | **0 on every retry** (baseline 958-1600) |
| I7 | **fail-closed intact** | any lens still `schema_valid = 0` after its retry → that case's `actual_verdict` | `UNVERIFIED`, always |

I1 is the sharpest of the three leak detectors: same case, same lens, same run, the two
attempts differing only by the flag. I6 is a wire-level reading, not an inference — the
provider reports the thinking split from the API's own usage payload.

**Endpoint and guardrails.**

| # | measures | source | expected |
|---|---|---|---|
| E1 | **primary metric** — retry emission | for each `(task_id, lens)` carrying a retry row, that lens's `eval_case_lens_results.schema_valid` | *k*/*n* judged against §8.1; baseline 0/5 |
| G1 | **hard guardrail** | `eval_runs.false_pass`, plus the §8.2 attribution query on any non-zero value | **0** |
| G2 | integrity | `status = 'error'` rows; `call_status`; automated gates | 0 errors; 30/30 `ok`; 30/30 gates pass |
| G3 | truncation failures | `eval_case_schema_failures` with `error_detail = 'response did not contain a JSON object'` | 2 → 0 |

E1 requires `schema_valid`, not merely `text_chars > 0`. Run 43's `security-02-clean ×
security` retry emitted 1668 characters and still failed the schema — text is not emission.

**Recorded only, deciding nothing (§8.3):** `correct_verdicts` (expected **8/10**, the
security-category figure in both runs 43 and 44), `false_unverified` (expected 2),
`total_cost`, wall time.

### 7.4 Two limits of the targeted design, registered in advance

**(a) The inference is conditioned on the `security` category.** It covers 5 of 5 firings
ever observed and 0 of 0 firings elsewhere, but a hypothetical out-of-category firing cannot
be seen by this design. What Phase 2 may claim on the strength of it is therefore "the
production retry population *as it has ever been realized*", not "every retry the engine
could conceivably issue". A full run remains available later if the trigger is ever observed
outside `security`.

**(b) The `errors` half of the retry condition is not live-observable.** The trigger is
`errors and response.stop_reason == _BUDGET_EXHAUSTED`. Across 225 initial Sonnet lens calls
every `max_tokens` termination was also unparseable (5 of 5), so a *parseable* `max_tokens`
response — the one observation that would demonstrate the `errors` conjunct live — has never
occurred and cannot be planned for. I5 proves the `stop_reason` conjunct on 27-28
observations per run; the `errors` conjunct is proven offline by P2 and P3. Should a
parseable `max_tokens` response occur during validation, it is recorded as an opportunistic
confirmation and must carry no retry row.

### 7.5 Required data-hygiene action

A `--category` run writes an `eval_runs` row with `total_cases = 10`. **All 43 completed
rows in the history are 40-case runs; these would be the first that are not**, and their
`correct_verdicts` and `category_accuracy` sit on a different denominator. When each run is
recorded, log it in `BASELINE.md` as a **targeted Phase 2 validation run, excluded from every
accuracy, variance and stability pool**. Under `baseline-evidence` this is part of the run,
not a follow-up to it.

## 8. Decision rules

Written before the first paid call. Not to be edited afterward.

### 8.1 Primary metric

Retry emission rate: schema-valid critics produced by `judge:*:retry` calls, over retry
calls issued. Baseline **0/5**. The endpoint is **evaluable only at n ≥ 3 firings** — at
n = 2 the metric can register nothing but an all-or-nothing 2/2.

Thresholds are Fisher's exact, two-sided, against the 0/5 baseline:

| firings *n* | emissions *k* required | p |
|---|---|---|
| 3 | 3 | 0.018 |
| 4 | 3 | 0.048 |
| 5 | 4 | 0.048 |
| 6 | 5 | 0.015 |

### 8.2 Outcomes

- **ACCEPT.** All of:

  | | condition |
  |---|---|
  | (a) | offline gates pass — `ruff`, `mypy`, `pytest`, including every test in §6 |
  | (b) | **I1-I7 hold in every run** (§7.3) |
  | (c) | E1: the primary metric clears §8.1 at n ≥ 3 |
  | (d) | G1: `false_pass = 0` in every run |
  | (e) | G2: integrity clean in every run |

- **REJECT (hard, zero tolerance).** Any one of:
  1. **`false_pass > 0` traceable to a rescued retry.** Attribution query, fixed here: for
     the false-passing case, does a `judge:%:retry` row exist at its `task_id`?
     **Yes → the §2.2 risk realized → stop and revert.**
     **No → not attributable to Phase 2** — a case with no retry has a byte-identical request
     sequence to baseline (§2.2, offline P1/P4) — so it is recorded as pre-existing judge
     variance and does not reject the change. Baseline: no security-category broken case has
     false-passed in any run on record.
  2. **I6 fails** — a retry recorded with `thinking_tokens > 0`. The flag did not reach the request.
  3. **I1, I2 or I3 fails** — the flag reached the first attempt. **This is an invariant
     breach, not a result**, and it is decidable in Stage 1 alone.
  4. **I4 or I5 fails** — a retry was issued outside the truncation condition.
  5. **I7 fails** — a lens left without a valid critic did not fail closed.

- **VOID.** Run aborted or timed out; G2 integrity check fails; tree dirty at run time; SHA mismatch.

- **INCONCLUSIVE.** Gates pass, no REJECT, but fewer than 3 firings after the extension rule.

### 8.3 What does *not* decide anything

- **`correct_verdicts` cannot ACCEPT or REJECT Phase 2.** Section 2 registers the expected
  change as zero, and §7.5 registers that a `--category` run's accuracy sits on a 10-case
  denominator that is **not comparable to any run in the 40-case history**. The
  security-category figure was 8/10 in both runs 43 and 44; a validation run at 7/10 or 9/10
  is one case, well inside σ ≈ 0.92 (carried over from the c0515eb/be990c7 v3 clusters; the
  Sonnet/v4 cluster holds n = 1 and has no dispersion estimate of its own). The accuracy
  column is uninterpretable here by construction and is recorded as an observation only.
- **`false_unverified` likewise.** `security-04-clean` stays `UNVERIFIED` either way.
- Cost and latency are budget parameters, not endpoints.

## 9. Cost

Sonnet 5: input $2/M, output $10/M (`runtime/budget.py` `PRICE_TABLE`).

Phase 2 makes retries **cheaper**: a retry currently burns the full 1600-token cap, at a
measured spend of $0.01750 each, while Phase 1C's thinking-disabled calls on this case used
827-1195 output tokens → ~$0.0094-$0.0131 with input. Saving ≈ $0.005 per retry.

Measured security-category judge spend, read from `.engine/state.db`: **$0.24096** (run 43,
33 calls, 3 retries) and **$0.22401** (run 44, 32 calls, 2 retries). Subtracting the
full-price retries leaves $0.18846-$0.18901 for the 30 initial calls, which Phase 2 does not
touch.

| stage | LLM calls | cost |
|---|---|---|
| Stage 0 — `--dry-run` | 0 | **$0.00** |
| Stage 1 — one run | 32-33 | $0.21 - $0.23 |
| Stage 2 — one run | 32-33 | $0.21 - $0.23 |
| **Planned total, N = 2** | **64 - 66** | **~$0.44** |
| **Registered ceiling, N = 2** | ≤ 70 | **$0.60** |
| Ceiling if the §7.2 extension fires (N = 4) | ≤ 140 | **$1.20** |
| Offline gates (§6) | 0 | $0.00 |
| Stage 1 REJECT — sequence stops after one run | 32-33 | ~$0.22 |

The $0.30-per-run ceiling absorbs a run in which the flag never takes effect (REJECT 2,
still billed at the baseline $0.241) plus two extra full-price retries. It no longer has to
absorb a timed-out run at full spend, because §7.1 removes that failure mode.

**Superseded design, for the record.** N = 2 full 40-case runs: 240-244 calls, ~$1.07
expected, $1.40 ceiling, $2.80 with the extension. The targeted design is **73% fewer calls,
59% less expected spend and a 57% lower ceiling**, and retains 100% of the retry firings
ever observed.

## 10. What a negative result looks like

1. **Mechanism does not reach the wire.** Retries still show `thinking_tokens` ≈ 1600 (I6 fails). Implementation defect → REJECT condition 2.
2. **Mechanism reaches the wire, does not rescue.** `thinking_tokens = 0` but the retry still fails to emit (k/n below §8.1). Phase 1C's effect does not transfer to the retry population. H2 unsupported.
3. **Rescue works, safety cost.** A broken case rescued into `OK` → `false_pass` → hard REJECT, revert.
4. **Invariant breach.** I1, I2 or I3 fails — the flag leaked onto the first attempt. REJECT condition 3, decidable in Stage 1, regardless of every other number.
5. **Trigger does not fire.** Fewer than 3 firings after the extension → INCONCLUSIVE.
6. **Integrity failure.** Abort, timeout, error rows, or a failed gate → VOID.

All six are recorded with the weight of a positive result. Outcome 2 is the most likely
genuine negative and is the one the design exists to detect.

## 11. Frozen — must not change

`LENSES`, `RESPONSE_INSTRUCTION`, `_parse_critic`, `_extract_json_objects`,
`enforce_critic_schema`, `rubric.BLOCKING`, `verdict.merge`, `verdict.gate`,
`verification/pipeline.py`, `eval/dataset.py`, `eval/runner.py`, `runtime/budget.py`,
`config.DEFAULT_MODELS` (judge stays `claude-sonnet-5`), `max_tokens = 1600`,
`MAX_JUDGE_RETRIES = 1`, the retry trigger condition, and the dataset.

R-a and off-lens blocking are out of scope. The `.engine/state.db` schema is unchanged.

## 12. Post-hoc leakage audit

| check | result |
|---|---|
| Is the baseline a measured rate at the current configuration? | **Yes.** 0/5 production retry firings, read from `.engine/state.db` runs 43-44. Not inherited, not assumed, not taken from a void batch. |
| Does void Phase 1 / Phase 1B data influence anything? | **No.** Both remain VOID. Neither contributes to the baseline, a threshold, or a decision rule. |
| Was a threshold chosen after seeing an outcome? | **No.** No Phase 2 call exists. Thresholds are Fisher p ≤ 0.05 against the stated baseline, tabulated in advance for every reachable *n*. |
| Is the primary metric the one the intervention targets? | **Yes** — retry emission. Accuracy is explicitly demoted to a recorded observation with a pre-registered expected change of zero. |
| Is a favourable-looking secondary available to rescue a negative primary? | **No.** §8.3 removes `correct_verdicts`, `false_unverified`, cost and latency from every decision rule, *before* any run. |
| Was an inconvenient result predicted away? | **The opposite.** §2 registers, before any run, that the change cannot improve accuracy — the least flattering true statement available about it. |
| Is one change bundled with another? | **No.** One request field on one call site. The `git-safety` list amendment (§5.1) is deliberately a separate commit. |
| Is an existing test weakened? | **One is amended, disclosed in full in §6.1.** It stays an exact set equality and gains two-directional value assertions. Nothing is deleted or relaxed to a subset check. |
| Can the change silently affect the first attempt? | **Guarded four ways** — offline P1/P4/P6, and live I1 (paired, same case/lens/run), I2 (aggregate, p = 1.9 × 10⁻⁴) and I3 (structural). Each is a REJECT condition on its own, and all three are decidable in Stage 1. |
| Is the extension rule outcome-driven? | **No.** It fires on fewer than 3 *trigger firings* (observability of the endpoint), never on a near-miss result. |
| Is the staged design optional stopping? | **No.** Stage 1 → Stage 2 is gated on invariant breaches and the extension on firing count; neither rule reads *k*. The primary metric is evaluated once, on the pooled firings, after the sequence stops (§7.2). |
| Did narrowing to one category shrink the evidence? | **It narrows the population, and §7.4(a) says so.** The `security` category holds 5 of 5 firings ever observed and 0 of 0 elsewhere in 165 non-security initial calls, so no observed trigger is lost — but an out-of-category firing cannot be seen, and Phase 2 may not claim otherwise. |
| Were the §8.1 thresholds relaxed to suit the cheaper design? | **No.** The Fisher table and the 0/5 baseline are unchanged; only the vehicle that generates the firings changed. Expected firings rise (4-6 vs ~4) rather than fall. |
| Does the plan authorize the run it describes? | **No.** Live validation needs the `git-safety` pre-run gate and explicit approval in the turn it happens. |

**Residual risk, stated plainly.** The trigger population Phase 2 acts on (retries after a
truncated first attempt) is not the population Phase 1C measured (first calls). The two
coincide on `security-04-clean`, where the first attempt is effectively deterministic, but
Phase 1C provides no evidence about a thinking-disabled retry following a *partial* answer —
the `security-02-clean × security` shape seen once in run 43. If that shape fires during
validation it **does** enter the primary metric — E1 is defined over *all* firings, without
regard to which shape produced them, and no firing may be excluded after the fact — and the
shape is additionally recorded alongside it so a partial-answer retry stays distinguishable
from a zero-text one in the write-up.
