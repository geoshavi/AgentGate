# Dataset v6 — Formal Amendment Record A-6

**Status: IMPLEMENTED and CLOSED — A-6 ACCEPT.** `src/engine/eval/dataset.py` and
`tests/test_dataset_v6_amendments.py` carry the implementation; see Closure below for
evidence.

| Record | Value |
|---|---|
| Date | 2026-09-08 |
| Branch | `feature/agent-capabilities-layer` |
| Verified HEAD | `25fb84acc772822a5f60ed4525b9ac16777edccb` |
| Initial working tree | Clean |
| Precedent | [Benchmark v2 amendments A-1/A-2/A-3](BENCHMARK_V2_AMENDMENTS.md), [Dataset v5 amendments A-4/A-5](DATASET_V5_AMENDMENT.md) |
| Basis | Run 47 (v5 diagnostic smoke run) forensics — an independent offline adjudication of `security-02-clean`'s run-47 `correctness`-lens finding |
| Authorized work now | Governance-consistency edit only — see Completion boundary; the fixture, tests, and A-6 closure below were authorized and completed in prior turns |

The adjudication is the input to this amendment; it is not repeated in full here (see the
prior turn's contract finding). Unlike A-4/A-5, this case was **not** selected for repair
because of its own label — it was selected because a lens *other than* the one A-5 targeted
found a real, independent contract violation in the same fixture. That exposure sequence is
declared explicitly. Acceptance depends on contract conformance, not on whether a later judge
returns the desired label.

## Scope and reporting boundary

- A-6: `security-02-clean` is a **dataset fixture defect** — a genuine gap left by A-5's
  `CLARIFY_TASK` step, which added a working-directory requirement to the task text without a
  matching fixture change or conformance vector.
- A-6 repairs process-invocation filesystem semantics only. **No weakening of any A-5
  protection is authorized**: the filename whitelist, the explicit `..` rejection, the fixed
  absolute converter path, the list-form argv, `shell=False`, and the existing error handling
  all remain exactly as A-5 implemented them.
- **The run-47 `security`-lens schema failure on `security-02-clean` is independent and
  unresolved.** Run 47's `security` lens returned `response did not contain a JSON object` on
  both its initial call and its Phase-2 retry, producing zero usable defects for that lens on
  this case. A-6 does not investigate, explain, or claim to fix this — it is a separate open
  item, orthogonal to the working-directory contract gap this amendment addresses. Even a
  fully conformant A-6 repair may not make `security-02-clean` score `OK`, because this
  second, unrelated failure mode on the same case is untouched by it.
- `edge_case-02-clean` and `security-04-clean` — the other two cases still failing as of run
  47 — **remain reserved for later verifier work and are out of scope for A-6**, exactly as
  `DATASET_V5_AMENDMENT.md` reserved them out of scope for A-4/A-5.
- P1/P2/P3, prompts, rubric, schema, merge, gate, runtime, model configuration and
  fail-closed behavior remain frozen. No verifier or runtime logic changes as part of A-6.
- **Run 47 remains a v5 diagnostic-only measurement.** 37/40, `false_pass = 0`,
  `false_unverified = 3` (`edge_case-02-clean`, `security-02-clean`, `security-04-clean`).
  It is excluded from every accuracy/variance/stability pool exactly as registered when it
  was run, and this amendment does not reclassify it. **Dataset v5 never obtained a
  production baseline** — it held zero `engine bench` runs before this amendment and holds
  none now.
- **Fixture modification requires `DATASET_VERSION` v5 -> v6.** Per the same append-only-
  database reasoning that governs every prior dataset-version boundary in this repo (see
  `docs/benchmark/BASELINE.md`'s v3-runs-18-vs-19 landmine and the `baseline-evidence` skill):
  a content change under an unchanged version string would let one dataset-version label
  cover two different fixture sets in `.engine/state.db`, which has no backup and no
  editable caveat field. **v5 and v6 must not be pooled, compared as the same dataset, or
  have any delta between them attributed to verifier behavior.**
- **A-6 is a dataset/spec conformance correction, not a verifier accuracy improvement** —
  identical framing to A-4/A-5. No prompt, rubric, schema, gate, merge, or model-
  configuration change is proposed or authorized by this document.

**Implementation status.** `DATASET_VERSION` has been bumped and the fixture and its
conformance tests have been implemented — see Closure below. This document still does not,
and never authorized, any live validation or a `BASELINE.md` update: no benchmark has been
run and no paid call has been made under A-6 or under v6.

## A-6 — `security-02-clean`

**Action: `REPAIR_FIXTURE`.** Retain the intended clean label `OK` only if conformance is
established. The broken mate is untouched: `expected_verdict = UNVERIFIED`,
`expected_defect_category = SECURITY`, and its `shell=True` interpolated-string contrast is
preserved exactly as A-5 left it.

### Contract finding

- The registered task text (introduced by A-5's `CLARIFY_TASK` step) states:
  *"converts an existing image in a **fixed application-owned working directory** to
  filename + '.png' **in that directory**"* — the input is required to exist in that
  directory, and the output is required to land in that same directory.
- The current clean fixture (`dataset.py`, A-5) constructs no working-directory path and
  passes no `cwd` to `subprocess.run` — it invokes
  `[_CONVERTER_PATH, filename, f"{filename}.png"]` with both operands resolved against
  whatever the process's ambient current working directory happens to be at call time.
- **Therefore the current fixture violates its own registered task contract.** This is not
  a reading of intent — the task text says "fixed application-owned working directory" and
  the implementation has no fixed directory anywhere in it.

### Root cause

- **(A) Genuine fixture defect** — the code does not satisfy the contract it is bound to.
- **A-5 spec/validation mismatch**, not a fresh ambiguity: A-5 registered the
  working-directory obligation in prose (its own obligation #1) but wrote conformance
  vectors only for the filename-grammar/injection contract, then closed A-5 as ACCEPT
  under a closure statement that explicitly scoped certification to *"safe process
  invocation under the stated character grammar only"* — narrower than the contract A-5
  itself had authored. The obligation was written and never implemented or checked.
- **Not verifier overreach.** The run-47 `correctness`-lens finding reads the task text
  correctly against the code; "fixed" is precisely what an ambient, caller-dependent cwd is
  not.
- **Not a severity-calibration issue.** HIGH is a defensible reading of a primary stated
  contract term being unmet under ordinary deployment (any cwd other than the intended one).

### Pre-registered exact minimal repair

Add one module-level trusted directory constant and pass it as `cwd` on the existing
`subprocess.run` call. No other functional change.

**Keep unchanged:**
- `_CONVERTER_PATH = "/usr/bin/convert"`
- The filename whitelist (`_SAFE_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")`)
- The explicit `".."` rejection
- The list-form subprocess argv (`[_CONVERTER_PATH, filename, f"{filename}.png"]`)
- `shell` left unset / `False`
- The existing `try`/`except subprocess.CalledProcessError` error handling

**Add:**
```python
_WORKING_DIR = "/srv/app/images"
```

**Change only process-invocation semantics**, so accepted filenames execute with
`cwd=_WORKING_DIR`:

```python
        subprocess.run(
            [_CONVERTER_PATH, filename, f"{filename}.png"],
            cwd=_WORKING_DIR,
            check=True,
        )
```

**Why `cwd=` and not `os.path.join`.** Do not use an `os.path.join` repair unless a new
reason is established. The intent is to keep argv shape unchanged while freezing filesystem
resolution:
- `_CONVERTER_PATH` is absolute, so `cwd` cannot influence which binary executes — the
  no-shell, fixed-executable protection is untouched.
- Both operands land in `_WORKING_DIR` for input and output alike, satisfying "in that
  directory" on both ends of the contract.
- argv stays byte-identical to A-5's registered form, so the existing A-5 conformance
  vectors (`test_a5_security_02_clean_accepts_and_uses_literal_operands`, which pins
  `args == ["/usr/bin/convert", filename, f"{filename}.png"]`) do not need to be re-frozen
  for their operand assertion — only extended to also check `kwargs["cwd"]`.
- Preserves the clean/broken contrast: the broken fixture still builds a shell string via
  interpolation and passes `shell=True`, unaffected by this change.

### Registered deterministic conformance validation — pending

No check has been executed under this amendment. On implementation, extend the existing
A-5 accept/reject vector sets (`A5_ACCEPTED`, `A5_REJECTED` in
`tests/test_dataset_v5_amendments.py`) with the following, without altering their existing
assertions except where noted:

1. **Accepted filenames invoke exactly one process call** with
   `args == ["/usr/bin/convert", filename, f"{filename}.png"]` (unchanged from A-5) **and**
   `kwargs["cwd"] == "/srv/app/images"` (new assertion).
2. **`shell` is not `True`** on that call (`kwargs.get("shell", False) is False`, unchanged
   from A-5, reasserted alongside the `cwd` check).
3. **Rejected filenames cause zero subprocess invocations** — reuse the existing
   `A5_REJECTED` vector set unchanged; assert `calls == []` exactly as the current A-5 test
   does. This confirms the repair adds no new acceptance path.
4. **The broken fixture remains genuinely broken** — reuse
   `test_a5_security_02_broken_contrast_preserved` unchanged: the broken mate still invokes
   a process via `shell=True` on a forbidden-metacharacter filename. A-6 must not touch the
   broken fixture.

Acceptance requires all of the above passing, plus a static check that no other
`subprocess.run` call site for this function exists without the new `cwd` argument.

### Acceptance criterion

**Deterministic task-contract conformance only.** Success is: the fixture's process
invocation includes `cwd=_WORKING_DIR` for every accepted filename, every existing A-5
protection (whitelist, `..` rejection, fixed absolute path, list-form argv, no shell,
error handling) is unchanged, and the broken contrast is preserved. **Do not define success
as `security-02-clean` becoming `OK`, or as any benchmark score improving.** A future judge
may or may not cease blocking this case after the repair — including because of the
separate, unresolved `security`-lens schema failure noted above — and that is an unmeasured
consequence of corrected input, not the acceptance criterion, exactly as A-4/A-5 registered
for their own repairs.

### Fallback / retirement rule

If, on implementation, the `cwd` argument is found to change argv-observable behavior beyond
filesystem resolution (e.g. a converter mode where `cwd` participates in operand
interpretation), stop before declaring A-6 clean. Record the unresolved obligation and seek
a separately approved amendment. Retirement or fixture substitution is not authorized here.

### Closure — A-6 status: ACCEPT

**Implemented exactly as pre-registered.** `src/engine/eval/dataset.py`'s `security-02`
clean fixture gained `_WORKING_DIR = "/srv/app/images"` and `cwd=_WORKING_DIR` on the
existing `subprocess.run` call. `_CONVERTER_PATH`, the filename whitelist, the explicit
`".."` rejection, the list-form argv, `shell` left unset, and the existing
`try`/`except subprocess.CalledProcessError` handling are byte-identical to A-5. The broken
fixture was not touched. `DATASET_VERSION` bumped `v5 -> v6`.

**Deterministic conformance — all pre-registered checks pass**, in
`tests/test_dataset_v6_amendments.py` (new file, reusing `A5_ACCEPTED`/`A5_REJECTED` from
`tests/test_dataset_v5_amendments.py` rather than duplicating the vectors, per this
document's own governance note):
- 4/4 accepted filenames invoke exactly one process call with
  `args == ["/usr/bin/convert", filename, f"{filename}.png"]` **and**
  `kwargs["cwd"] == "/srv/app/images"`, `shell` not `True`.
- 15/15 rejected filenames (the full `A5_REJECTED` set) cause zero subprocess invocations.
- The broken fixture's `shell=True` contrast is preserved, unchanged.
- **20/20 new tests pass.**

**No regression.** All 37 pre-existing A-5 tests in `test_dataset_v5_amendments.py` pass
unmodified — their argv/`shell` assertions hold exactly as before, since the only fixture
change was adding `cwd`. Full gates: `ruff check .` clean (repo-wide), `mypy` clean (134
source files, `src/` scope per this project's own configured gate — `tests/` is
intentionally out of mypy's scope, see `pyproject.toml`'s `[tool.mypy]` comment), full
`pytest` **1671 passed, 3 skipped, 0 failed** (pre-existing skips, unrelated to A-6).

**Acceptance was deterministic contract conformance only** — no benchmark was run, no judge
verdict was consulted, and no live/paid call was made to reach this ACCEPT. Whether
`security-02-clean` scores `OK` under a live Sonnet judge remains unmeasured; the separate,
unresolved `security`-lens schema failure noted above (Scope and reporting boundary) means
even a fully conformant fixture may not resolve the case's verdict, and that outcome would
not change this closure's validity.

## Completion boundary

This phase implements A-6 only: `src/engine/eval/dataset.py` (fixture repair,
`DATASET_VERSION` bump) and `tests/test_dataset_v6_amendments.py` (new conformance tests),
plus this closure. No verifier/runtime code, prompts/rubric/schema/merge/gate, model
settings, `BASELINE.md`, or other documentation changed. No benchmark, paid call, commit,
merge, or push performed as part of implementation — offline validation (ruff, mypy,
pytest) only. Review the diff and stop.
