# AgentGate — Final Project Status

Release candidate. Accuracy optimization is closed. The historical
verifier-hardening thread (§3 below) is **CLOSED**; see §3a for the current
closure record and `docs/benchmark/BASELINE.md` for the full evidence.

---

## 1. Release candidate

| | |
| --- | --- |
| Benchmark | `engine-review-benchmark` |
| `BENCHMARK_VERSION` / `DATASET_VERSION` (current) | **v2 / v6** |
| Judge model (current) | `claude-sonnet-5` (Anthropic) |
| Runtime verdict path | byte-identical to the proven safe engine `53d8a42` at the historical `f79353c65099561854e63ed2a8b8e23aaa2c58ce` checkpoint; see `docs/benchmark/BASELINE.md` for every configuration since |

The dataset/judge pairing below in §2 (v2/v4, `claude-haiku-4-5-20251001`) is
**historical** — the release-candidate configuration this section originally
described. It is preserved for provenance and is superseded by the current
v6/`claude-sonnet-5` runs in §3a and `docs/benchmark/BASELINE.md`.

---

## 2. Historical validated benchmark result (v2 / v4, superseded)

Five runs at one commit, dataset frozen, no configuration change between runs:

| | |
| --- | --- |
| Scores | **36, 35, 35, 35, 35** |
| Mean | **35.2 / 40 = 88.0%** |
| Sample SD | **0.447** |
| False passes | **0 / 100** broken-case observations |
| Deterministic cases | 39 of 40 |
| Cost | $0.643 for the five runs |

Recorded in `.engine/experiments/phase8d0-stability/`. **This result is
historical, at the v4/Haiku configuration, and is not the current benchmark
state** — see §3a for the current (dataset v6, `claude-sonnet-5`) result.

---

## 3. Historical remaining known failures (v2 / v4, superseded)

At the v4/Haiku configuration above, four clean cases failed in every stored
observation, capping that configuration at 36/40:

| Case | Rate | Why the judge blocked it |
| --- | --- | --- |
| `correctness-02-clean` | 0/5 | Rated `abs(a - b) < 0.01` HIGH and asked for `decimal`, though the code *is* the stated predicate — an implementation preference |
| `edge_case-03-clean` | 0/5 | Two lenses claimed `str` slicing splits multi-byte UTF-8. It cannot: `str` slices code points. The fix it prescribed was that task's own broken fixture |
| `security-02-clean` | 0/5 | Two blockers alleged shell injection against `subprocess.run([...])` with no shell, each conceding non-exploitability in its own text; a third (uncaught `FileNotFoundError`) was factually true but not required by the task |
| `security-04-clean` | 0/5 | Claims contradicted by the supplied code (an `all()` check) or excluded by the task's own wording; claim content varied run to run |

`edge_case-04-clean` was variable (1/5) at that configuration and was the sole
source of score variance there. **These are the v4/Haiku-configuration
observations; they do not describe the current dataset v6 configuration** — see
§3a.

## 3a. Current closure record (dataset v6, `claude-sonnet-5`)

The four *original* historical clean cases (a distinct, later case set from §3's
v4-era list; case identities are dataset-version-specific) were closed in Run 67
(`docs/benchmark/BASELINE.md`, "Run 67 — final closure validation"):

| Case | Closure status |
| --- | --- |
| `correctness-02-clean` | **CLOSED / FIXED** — dataset v5 amendment A-4 |
| `security-02-clean` | **CLOSED / FIXED** — dataset/spec amendments v5/v6 |
| `edge_case-02-clean` | **CLOSED / RESOLVED for known historical false-blocker families** — live-validated Route A/B contract-evidence adjudication, Run 66; not a claim of universal future coverage |
| `security-04-clean` | **CLOSED BY ADJUDICATION / v6 dataset-spec limitation** — not fixed; deferred to a possible future v7 dataset revision; its MEDIUM CGNAT concern remains visible and unsuppressed |

**Run 68** (post-closure full 40-case health check, standard run, no
`--adjudicate`/`--shadow-adjudicate`, dataset v6, judge `claude-sonnet-5`):
**38/40 (95.0%)**, `false_pass = 0`, `false_unverified = 2`
(`security-02-clean`, `security-04-clean` — both schema-noise / already-catalogued
adjudication buckets, neither reopening its closure). Category accuracy:
correctness 100%, quality 100%, edge_case 100%, security 80%. Interpretation per
`docs/benchmark/BASELINE.md`: **healthy, no new regression.**

This does not claim universal correctness, production safety, or that
adjudication is authoritative beyond its documented scope. Full detail, including
every intermediate run between the v4 configuration and this one, is in
`docs/benchmark/BASELINE.md`.

---

## 4. Accepted infrastructure fixes

| Fix | Status |
| --- | --- |
| `automated.py` — empty-output gate failure no longer records the ambiguous `"ok"` sentinel (DF-1) | Applied, Phase 8A, 7 tests |
| `db.py` — unpaired UTF-16 surrogates in model text no longer raise `UnicodeEncodeError` during persistence | Applied, Phase 8D.1, 3 tests |

The surrogate fix is general (every model-supplied column), write-side only (no
verdict it can reach is affected), and preserves valid Unicode — astral characters
round-trip byte for byte. It was found the hard way: an emoji in a judge's text
aborted a 40-case run at case 36 and discarded 35 computed results.

---

## 5. Rejected experimental directions

Every one of these raised or promised to raise the score and was reverted on
measured evidence.

| Phase | Intervention | Measured outcome |
| --- | --- | --- |
| 4 | Source-verification + task-scope prompt | Not supported, n=8 vs n=8: mean 33.00 → 32.63 |
| 8C | Emit severity after the fix analysis | 35 → 38, but schema failures 0 → 7 and the mechanism erodes blocking margin |
| 8C.1 | Verdict normalization | **2 false passes in one run** |
| 8D.1 | Demonstrability prompt | Model fabricated a concrete trigger that was false; run crashed before evaluation |
| 8D.2 | Executed-witness verification | **26 false passes / 100**, −7.4 cases; all 26 attributed to witness demotion |

Common failure: each worked by changing what the model produces or how its output
is re-scored. The mechanism that changed behaviour most decisively also broke
safety most decisively.

The 8D.2 root cause is worth keeping: the witness contract never said whose
behaviour `expect` described. Reviewers write the **required** behaviour; the
classifier read it as the **observed** behaviour. On broken code those differ by
definition, so every correct diagnosis was refuted and demoted. The prototype's own
tests missed it because the implementer wrote the witnesses and the model did not.

---

## 6. Active architecture

- **Orchestrator** — `task_analyzer` classifies, `execution_plan` produces a
  validated plan with token/spend/agent limits, `manager` executes it. Agents never
  talk to each other.
- **Gateway** — every LLM call routes through `runtime/gateway.py`, which enforces
  the budget before the call and records usage after it. Three architecture tests
  make the boundary unbypassable.
- **Verification** — three judge lenses (correctness, security, code-quality) return
  structured defects validated against a fixed schema; a pure Python
  `merge`/`gate` is the only code allowed to decide `OK` / `UNVERIFIED`. Any
  CRITICAL/HIGH defect blocks, a malformed response blocks, a failed automated gate
  blocks.
- **Persistence** — SQLite run history, per-call metrics, per-case eval results,
  defects, lens results, gate results and schema failures.

No LLM decides pass/fail anywhere in this system.

---

## 7. Known limitations

- The benchmark is **project-specific**, not an industry-standard external suite.
  It makes changes to this engine falsifiable; it does not rank this engine
  against others.
- **36/40 was the ceiling at the historical v4/Haiku configuration in §2-3, and
  does not describe the current configuration.** The four v4-era cases in §3 are
  a different, dataset-version-specific case set from the four cases closed in
  §3a; `security-04-clean` remains a genuine current limitation (closed by
  adjudication, not fixed — see §3a and `docs/benchmark/BASELINE.md`).
- Judge lens calls are capped at `max_tokens=1600` (current). The largest fixture
  can still occasionally truncate, which fails closed to `UNVERIFIED`. Raising it
  further trades cost and cross-run comparability for an unmeasured gain.
- Single provider (Anthropic), sequential sub-agent execution.
- The n8n `/review` webhook runs `pytest` on submitted files inside the container
  with no sandboxing beyond the container boundary. Do not expose it publicly.
- The five-run stability sample in §2 was small (SD 0.447 at the v4/Haiku
  configuration); the current dataset v6 configuration cluster has since
  accumulated many more runs — see `docs/benchmark/BASELINE.md` for the full
  run-by-run and per-case stability record.

---

## 8. Intentionally deferred

| Item | Why |
| --- | --- |
| **DF-3** — a failing judge lens discards critics already collected | Never fired in 4,680 recorded lens calls. Repair would change what `gate()` sees when a lens fails — a verdict-semantics decision, and the current behaviour is the fail-closed direction. Needs its own pre-registered phase (`DEFERRED_FIXES.md`) |
| `max_tokens` tuning | Cost and comparability trade-off; needs its own pre-registration |
| Multi-provider routing, parallel sub-agents, merge control, long-term memory | Planned milestones, never started |

---

## 9. Why score chasing was stopped

Phase 8E.0 was a read-only gate that asked whether any of the four stable failures
could be fixed **without** weakening HIGH/CRITICAL, changing verdict authority or
schema semantics, adding an LLM call, asking the model for new evidence fields,
matching case IDs or fixtures, broad prompt calibration, or executing generated
code. It returned **`NO_SAFE_TARGET`**, on measurement rather than opinion:

- `verdict.gate` decides on severities alone, so changing a verdict requires
  changing the severity set — and within the permitted fix types the only route is
  a deterministic filter over existing data.
- The one such filter available (lens/category disagreement) leaves **all four
  targets still blocking in all six stored observations**, while touching 45.7% of
  the blocking defects on broken cases. Zero upside, large blast radius.
- For three of the four, the false blocker on the clean case and a genuine blocker
  on its **broken twin** are substantially the same claim (word overlap 0.29 /
  0.16 / 0.14 against an unrelated-task baseline of 0.02). The only separator is a
  fact about the code, and reading that deterministically means executing it —
  already rejected at 26 false passes — or asking a model, which is excluded.
  **Any filter strong enough to clear the clean case clears its broken twin.**

Five interventions, five reversions, and a measured impossibility argument for the
remainder. Stopping is the finding, not a failure to try: at the v4/Haiku
configuration this section describes, the engine shipped at 88.0% with zero false
passes rather than at a higher number bought with silent acceptance of broken
code. The current dataset v6 / `claude-sonnet-5` configuration (§3a) holds to the
same zero-false-pass discipline — Run 68 measured `false_pass = 0` at 95.0%.
