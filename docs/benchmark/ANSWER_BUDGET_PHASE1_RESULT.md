# Answer-Budget Hardening — Phase 1 result and forensic

**Status: VOID.** The registered contamination guardrail tripped. Phase 1 produced no
citable finding.

| | |
|---|---|
| Registration | `docs/benchmark/ANSWER_BUDGET_REGISTRATION.md` (unmodified) |
| HEAD at execution | `feaba281e12b396772323393b611eb2f8504c250` |
| Judge model | `claude-sonnet-5` |
| Stage 0 | ACCEPTED — `thinking={"type":"disabled"}` reachable; $0.002970, `end_turn`, 0 thinking tokens, schema-valid |
| Batch | 44/44 registered calls completed; no safety REJECT, no drift, no budget stop |
| Spend | **$0.392078** incl. Stage 0, against the registered $0.55 ceiling |
| Raw artifact | `experiments/answer_budget/phase1_batch.jsonl` (44 records, one per call) |
| Harness | `experiments/answer_budget/run_batch.py`, `stage0_probe.py` |
| Benchmark runs | **none.** `conn=None`, `run_id=None`; no row in `.engine/state.db`, no `BASELINE.md` row |

## 1. Why Phase 1 is VOID

Registered stop condition 5: *"More than 15% of Arm A calls returning schema errors outside
the target set voids the measurement."*

Observed: **3 of 16 non-target Arm A calls = 18.75%**, above the 15% threshold. The
measurement is void.

**The denominator must not be retroactively reinterpreted.** The registration's wording
admits a second reading — numerator over *all* 20 Arm A calls gives 3/20 = 15.0%, which is
not *more than* 15% and would not trip. The 3/16 reading was the one applied at execution.
Re-deriving the result under the other reading now would be precisely the retrofit
`experiment-design`'s anti-post-hoc rule forbids: *decision rules are written before results
are seen and are never edited afterward; a badly chosen rule is a lesson for the next
experiment, not a correction to this one.* The ambiguity is recorded here as a defect to fix
in the successor's wording, and for no other purpose.

**No BENEFIT SHOWN claim may be made from Phase 1**, notwithstanding that the section 8
inputs would otherwise have computed to it (zero REJECT events; 8/8 target Arm B emission
against a 5/8 threshold; both lenses 4/4 against a 2/4 threshold). The measurement is void;
those numbers are not findings.

## 2. What the numbers were — observational only

Recorded so the successor can size itself. **None of this is a finding, and none of it may
be cited as evidence for or against R-a, the answer-budget hypothesis, or any production
change.**

- **Target `security-04-clean`: Arm A 0/4 emission, Arm B 8/8 schema-valid.** Arm A
  reproduced the stored profile exactly — 4/4 at `max_tokens`, 1599/1600 thinking, 0 chars —
  so the drift check (stop condition 4) passed. Arm B emitted a schema-valid critic on every
  call, 4/4 on each lens.
- **Safety `quality-04-broken`: no REJECT.** Every Arm B replicate retained at least one
  CRITICAL/HIGH defect (margins 1, 1, 2, 2). Arm A margins were 1, **0**, 2, 2 — replicate 2
  carried zero blockers across the two tested lenses under *unmodified current behaviour*,
  which is baseline judge variance, not an effect of the intervention, and not a rule
  violation (the registered REJECT is Arm-B-only).
- **Control `security-02-clean`: no calibration loss.** Arm B produced a blocking defect on
  both lenses in all 4 replicates; Arm A truncated to schema failure on 2 of 4 security-lens
  calls. Run 44's specific `SECURITY/CRITICAL` + `CORRECTNESS/HIGH` signature did not recur
  under either arm — expected, since section 2 registered this case as stochastic.
- **Schema-failure rate by arm: Arm A 7/20 (35%), Arm B 0/24 (0%).** The intervention arm was
  cleaner than the baseline arm on the very metric that voided the batch.

## 3. Forensic — the three non-target Arm A failures

**None matches the `security-04-clean` zero-answer mechanism.** That signature is
`stop_reason=max_tokens`, thinking ≈ 100% of a 1600-token cap, and **zero** characters of
answer — reproduced 4/4 in this batch's drift check.

| # | call | stop_reason | output / thinking | answer text | class | security-04 mechanism? |
|---|---|---|---|---|---|---|
| 1 | `security-02-clean` × security, A rep 3 | `max_tokens` | 1600 / 872 (54%) | present, 1886 chars | PARSE (`response did not contain a JSON object`) | **No** |
| 2 | `security-02-clean` × security, A rep 4 | `max_tokens` | 1600 / 1322 (83%) | present, 618 chars | PARSE (same error) | **No** |
| 3 | `quality-04-broken` × code-quality, A rep 1 | `end_turn` | 271 / **0** (0%) | present, 631 chars | SEMANTIC (`verdict: is 'FAIL' but expected 'OK' given the defects`) | **No** |

**Rows 1-2 — the registered control case behaving as registered.** These emitted substantial
answer text and spent 54%/83% of budget thinking; the failure is "answer started, ran out of
room", not "thinking consumed everything". Stored precedent is exact: run 43's
`security-02-clean × security` produced the byte-identical error string at 317 chars /
`max_tokens`. Pooling first attempts at this configuration — run 43 fail, run 44 pass, batch
reps 1-4 pass/pass/fail/fail — gives **3/6 = 50%**. Section 2 of the registration selected
this case *because* it truncates stochastically and printed that run-43 row in its own table.

**Row 3 — the dominant historical failure class, unrelated to answer budget.** `end_turn`,
zero thinking, complete response; the model declared `FAIL` while its defects were all below
blocking severity. **25 of 40** schema failures in the entire stored history are verdict
inconsistencies (only 6 are missing-JSON). Run 44 carried the identical error string on
`quality-05-broken × security`. One event in 4 calls against a ~2.5% Sonnet base rate
(3/122 in run 44) is unremarkable.

**Classification: ordinary, already-documented stochasticity. No distinct systematic issue
in the data.**

## 4. Root cause — the guardrail, not the data

The contamination numerator counted the control case's own registered, expected failure mode.
Expected failures in the rule's 16-call denominator:

| cell | calls | p(schema failure) | expected |
|---|---|---|---|
| `security-02-clean` × security | 4 | ~0.50 (documented) | 2.00 |
| other non-target Arm A cells | 12 | ~0.025 (Sonnet base rate) | 0.30 |
| | | **total** | **2.30 / 16 = 14.4%** |

The rule sat essentially **on its own trip point before anything anomalous occurred**;
3 failures (18.75%) crosses it, and that had roughly a 40% prior probability on a completely
healthy batch. This is a specification defect discovered by execution, and it is the sole
reason Phase 1 is void.

Forensic limitation, recorded so the successor fixes it: the harness did **not** persist raw
response text. Rows 1-2 are classified as mid-object truncation by inference — text present,
`max_tokens`, and `_extract_json_objects` finding no *balanced* object — which is sound but
was not directly inspected.

## 5. Measured cost basis (for sizing the successor)

Rates: input **$2.00/MTok**, output **$10.00/MTok**. Mean input tokens recovered from stored
spend and output tokens. Worst case assumes every call reaches the 1600-token cap.

| set | lens | arm | n | mean in | mean out | mean $/call | cell total | worst $/call |
|---|---|---|---|---|---|---|---|---|
| target | correctness | A | 2 | 748 | 1600 | 0.017496 | 0.034992 | 0.017496 |
| target | correctness | B | 4 | 748 | 823 | 0.009728 | 0.038914 | 0.017496 |
| target | security | A | 2 | 753 | 1600 | 0.017506 | 0.035012 | 0.017506 |
| target | security | B | 4 | 753 | 1247 | 0.013974 | 0.055894 | 0.017506 |
| control | correctness | A | 4 | 545 | 1202 | 0.013110 | 0.052440 | 0.017090 |
| control | correctness | B | 4 | 545 | 417 | 0.005258 | 0.021030 | 0.017090 |
| control | security | A | 4 | 550 | 1434 | 0.015440 | 0.061760 | 0.017100 |
| control | security | B | 4 | 550 | 581 | 0.006912 | 0.027650 | 0.017100 |
| safety | correctness | A | 4 | 735 | 138 | 0.002852 | 0.011410 | 0.017470 |
| safety | correctness | B | 4 | 735 | 149 | 0.002958 | 0.011830 | 0.017470 |
| safety | code-quality | A | 4 | 896 | 326 | 0.005047 | 0.020188 | 0.017792 |
| safety | code-quality | B | 4 | 896 | 270 | 0.004497 | 0.017988 | 0.017792 |

Set totals: **target 12 calls $0.164812**, **safety 16 calls $0.061416**, **control 16 calls
$0.162880**. Sum = $0.389108 = the batch's measured actual, exactly.

The registration's section 10 model predicted ~$0.40 expected against a $0.55 ceiling; actual
was $0.392078. **The cost model was accurate** — unlike Phase 4C's, which under-ran by 1.70x
because it was carried from a different corpus.

## 6. Candidate successor designs — NOT REGISTERED

Recorded for sizing only. Phase 1B is **not registered** by this document and no successor
call is authorised.

| design | calls | expected | worst realistic | absolute worst |
|---|---|---|---|---|
| target only | 12 | $0.1648 | $0.1711 | $0.2100 |
| target + safety | 28 | $0.2262 | $0.3428 | $0.4921 |
| target + safety + control | 44 | $0.3891 | $0.5347 | $0.7656 |

"Worst realistic" holds Arm A at the cap (it truncates by construction) and Arm B at its
observed per-cell maximum. Increments are additive: 12 → 28 adds the safety set (+$0.0614);
28 → 44 adds the control set (+$0.1629).

Whatever scope is chosen, two fixes are mandatory, and both are free:

1. **Respecify the contamination guardrail against pre-declared per-cell expected rates**
   rather than one pooled percentage over heterogeneous cells. A flat threshold cannot work
   on a set containing a documented ~50%-truncation cell. Fix the denominator wording at the
   same time.
2. **Persist raw response text and auto-classify parse vs semantic per call**, so no future
   forensic has to infer a truncation point indirectly.

Stage 0 need not be repeated: `thinking={"type":"disabled"}` acceptance on `claude-sonnet-5`
is now measured.

## 7. Provenance of the preserved harness

**`run_batch.py` and `stage0_probe.py` are not byte-identical to the scripts that executed.**
They are copies, made from the session scratchpad after the batch had already run and the
artifact already written, then edited to pass `ruff check .` on the tracked tree. The
committed files are the *post-execution, lint-edited* copies, not the executed originals —
those originals never entered version control and exist only as the scratchpad files this
copy was diffed against.

`diff` against the pre-copy originals shows exactly three classes of edit, all lint-driven,
none touching program behaviour:

1. seven `# noqa: E402` comments removed (ruff's own scope did not flag the import-order
   violation they were suppressing, making the directives themselves the lint hit — `RUF100`)
2. one `kwargs = dict(...)` call rewritten as an equivalent `{...}` dict literal (`C408`)
3. one `f"API ACCEPTED"` narrowed to `"API ACCEPTED"` — an f-string with no placeholder (`F541`)

No line constructing a request, defining an arm, or scoring a response was touched; the A/B
distinction (`if arm == "B": kwargs["thinking"] = {"type": "disabled"}`) is character-for-
character what ran. The full diffs are reproducible from this session's scratchpad and are
not re-included here; the claim rests on inspection of the diff, not on the copy operation
being trusted to have preserved behaviour.
