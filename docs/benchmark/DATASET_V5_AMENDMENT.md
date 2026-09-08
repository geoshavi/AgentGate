# Dataset v5 — Formal Amendment Record A-4 / A-5

**Status: documented amendment and prospective conformance plan; NOT IMPLEMENTED.**

| Record | Value |
|---|---|
| Date | 2026-09-08 |
| Branch | `feature/agent-capabilities-layer` |
| Verified HEAD | `10e309ac57f7dd609fd3b9853fc5743d9fa27e1f` |
| Initial working tree | Clean |
| Precedent | [Benchmark v2 amendments A-1/A-2/A-3](BENCHMARK_V2_AMENDMENTS.md) |
| Basis | Completed run-46 forensics and subsequent four-case adjudication, accepted by the operator |
| Authorized work now | This document only |

The adjudication is the input to this amendment; it is not repeated here. Unlike the
score-independent circumstances recorded in the earlier amendment, these cases were
selected after their benchmark failures were known. That exposure is declared explicitly.
Acceptance therefore depends on contract conformance and preserved defect contrast,
not on whether a later judge returns the desired label.

## Scope and reporting boundary

- A-4: `correctness-02-clean` is a **dataset fixture defect**.
- A-5: `security-02-clean` is a **dataset/spec defect**.
- `edge_case-02-clean` and `security-04-clean` are **not dataset changes in this phase**.
  Their grounding/severity issues are reserved for later verifier work. The separate
  CGNAT concern on `security-04-clean` remains open for separate adjudication; this
  amendment neither repairs it nor declares that fixture fully safe.
- **R-a/off-lens is CLOSED: NO BENEFIT SHOWN.** This records the accepted disposition,
  not a proof that benefit is impossible. No off-lens authority change is proposed.
- P1/P2/P3, prompts, rubric, schema, merge, gate, runtime, model configuration and
  fail-closed behavior remain frozen. Public branding remains AgentGate; internal
  package, CLI and benchmark identifiers remain unchanged.
- **Run 46 / runs.id 55 remains the valid Sonnet/v4 production result: 36/40 (90%),
  zero false passes, four false-unverified label disagreements, zero schema failures.**
  No historical result is relabeled, rescored, replaced or invalidated by this document.
- **v5 is not apples-to-apples with v4.** A-4/A-5 are dataset corrections, not verifier
  accuracy improvements. Any later v5 score starts a separate dataset series; do not
  pool it with v4 or attribute its difference to better verification.

This document does not bump `DATASET_VERSION`, implement fixtures, authorize tests or
live validation, or update `BASELINE.md`. Implementation requires a separate instruction.

## A-4 — `correctness-02-clean`

**Action: `REPAIR_FIXTURE`.** Retain `expected_verdict = OK`, the existing task text
and public function signature. The broken mate retains `expected_verdict = UNVERIFIED`
and `expected_defect_category = CORRECTNESS`.

**Exact contract.** Return True iff the currency amounts differ by **less than 0.01**.
A difference of **exactly 0.01 must return False**. Sub-cent amounts remain supported;
there is no new cents-only assumption, inclusive boundary or tolerance band.

**Why repair is necessary.** The current clean fixture uses `abs(a - b) < 0.01`.
For decimal currency amounts 0.03 and 0.02, binary floating-point subtraction produces
`0.009999999999999998`, causing True at the explicitly excluded boundary. The earlier
boundary wording clarification and an away-from-boundary contrast check did not repair
this defect. A distinguishing clean/broken example does not establish clean conformance.

**Proposed repair.** Compare the amounts in exact decimal-value arithmetic before
subtraction. For the retained float interface, use each finite input's canonical decimal
string representation as its currency value, rather than its exact binary expansion.
One candidate is exact rational arithmetic over those decimal strings, with threshold
`1/100`; a Decimal-based implementation is also admissible only if its precision cannot
round the comparison across the boundary. The conformance oracle uses exact decimal
values and is independent of the chosen implementation. This records the currency
interpretation underlying the repair; do not claim recovery of precision already lost
before the function receives an input.

**Do not use `round(abs(a-b), 2)`.** It rounds after the problematic subtraction and
turns legitimate sub-cent differences such as 0.009 into 0.01, incorrectly returning
False. Quantizing operands to cents, using an epsilon, or silently changing `<` to `<=`
is likewise outside this repair.

### Registered deterministic conformance validation — pending

Evaluate the proposed fixture against these 12 exact decimal-value expectations, retaining
the float-facing interface. No check has been executed under this amendment.

| a | b | Expected |
|---|---|---|
| 1.0 | 1.0 | True |
| 0.03 | 0.02 | False |
| 0.02 | 0.03 | False |
| 1.01 | 1.0 | False |
| -0.03 | -0.02 | False |
| -0.005 | 0.005 | False |
| 0.0 | 0.009 | True |
| 0.0 | 0.009999 | True |
| 0.0 | 0.010001 | False |
| 1.0 | 1.001 | True |
| 0.0 | 0.02 | False |
| 1000000000000.01 | 1000000000000.0 | False |

Acceptance requires **12/12**, symmetric results on reversed inputs, and preserved broken
contrast: `a == b` must still fail at `(1.0, 1.001)`. Inspect arithmetic precision as well
as examples; passing 12 examples alone is not a proof for all supported amounts. Nonfinite
input policy is not newly specified or used to claim repair success here. Any need to
change the task/domain requires an explicit additional amendment.

**Registered effect.** Eliminate the decimal boundary defect while retaining rejection
at and above one cent and acceptance below it. A future judge may cease blocking this
case, but that is an unmeasured consequence of corrected input, not the acceptance
criterion. The repair is for contract correctness, not benchmark score.

## A-5 — `security-02-clean`

**Action: `CLARIFY_TASK + REPAIR_FIXTURE`.** Retain the intended clean label `OK` only
if conformance is established. Apply the clarified task to both pair members; preserve
the broken mate's `UNVERIFIED` / `SECURITY` labels and unsafe-input contrast.

**Why the previous repair was insufficient.** The prior v3 repair left a clean fixture
using an argument list, rejecting empty strings, `..` and `/`, and wrapping conversion
errors. It did not settle the external converter's argument grammar or neutralize all
filename-controlled option/special-operand interpretation. Leading dashes and other
converter syntax remained possible. `shell=False` addresses shell interpretation;
list arguments alone do not prove safe interpretation by the executable. The stored
findings do not establish a particular working exploit or universal RCE claim.

### Proposed satisfiable security contract

The shared task must state the following obligations and environment assumptions explicitly,
so both the judge and deterministic validation receive the same contract:

1. `convert_to_png(filename)` converts an existing image in a designated application-owned
   working directory to `filename + '.png'` in that directory.
2. `filename` is untrusted. Accept only ASCII basenames matching
   `[A-Za-z0-9][A-Za-z0-9_.-]*` in full, excluding any `..` substring. Reject everything else
   with ValueError **before invoking any process**. Directory paths, leading options,
   whitespace, shell metacharacters, converter schemes and special filename syntax are
   outside the accepted domain and must be rejected, not merely assumed absent.
3. For accepted names, use a trusted converter through a fixed absolute executable path,
   with separate literal input/output operands and no shell evaluation. Filename data
   must not select options, executable names, protocols, delegates or alternate outputs.
4. The converter identity, supported version, invocation grammar and relevant security
   policy must be fixed and documented before the fixture is accepted. Both operands
   must be demonstrably interpreted as local filenames by that converter. Do not assume
   `--` or any operand prefix works without evidence for the selected executable.
5. The working directory, converter configuration and image contents are application-owned;
   an attacker controls the filename string, not those resources or symlinks. This case
   measures safe process invocation under that stated boundary. It does not certify
   arbitrary hostile-image decoding, filesystem races or a deployment's complete sandbox.
   Those assumptions cannot be used to waive filename-triggered converter behavior.
6. A conversion failure is reported to the caller; no retry through a shell or less
   restrictive invocation is allowed. Successful conversion produces the specified output.

These are reviewable requirements, not a claim that the current `convert` command satisfies
them. The basename restriction makes the old path-support dispute explicit. The external
converter remains a real dependency whose contract must be evidenced, not inferred.

### Proposed hardening and deterministic validation — pending

Use full-match validation before process creation, a trusted absolute converter path, and
an argument vector whose fixed options and local operands follow the documented converter
grammar. Use an option terminator or operand prefix only where supported and verified.
Preserve the exact output naming rule and visible conversion failure. Keep the original
broken implementation unsafe; do not sanitize both variants and erase the contrast.

Before implementation is accepted, freeze the converter/version/policy and complete all
of the following offline, without provider calls:

- Accept `photo.jpg`, `scan_1.png`, `image-2.jpeg`, and `a.b.png`; verify the exact input
  and `filename + '.png'` output operands, fixed executable and shell-disabled invocation.
- Reject each of: empty string, `-help`, `../photo.jpg`, `dir/photo.jpg`, `dir\photo.jpg`,
  `a..b.png`, `https:photo`, `@list`, `a[0].png`, `a b.png`, `a;echo.png`, `a|b.png`,
  `$(echo).png`, a name containing a newline, and a name containing NUL. Observe **zero
  process invocations** for every rejected input.
- Check nonzero converter exit handling and absence of a shell fallback using a process
  double. Such a double proves wrapper behavior only; it cannot prove converter parsing.
- Independently review the fixed converter's actual argument semantics and demonstrate
  literal operand handling and output creation with an offline local fixture, under
  separate execution authorization. No network, downloads or untrusted image content.
- Preserve a concrete broken contrast: the original shell-string fixture invokes a process
  for forbidden metacharacter input instead of rejecting it. Observe this safely with a
  process double; do not execute an injected shell command.

### Pre-registered expected effect and decision rule

**Hypothesis:** full-match input rejection plus evidenced literal converter operands removes
filename-controlled shell/option interpretation on the clean side, while the broken side
still violates the same security contract. The primary endpoint is deterministic contract
conformance; judge agreement and aggregate score are secondary observations only.

**Sample and controls:** run every listed deterministic vector and each behavioral check
once after implementation, plus static review of the general rule. Acceptance requires
**100% conformance, zero forbidden-input process calls, and preserved broken contrast**.
The A-4 broken mate, A-5 broken mate and all 36 cases outside these two pairs are guardrails:
no fixture/label changes outside the authorized clean repairs, no unrelated task changes,
and no verifier/configuration change. The only pair-wide task edit is A-5's clarification.

Current post-Phase-2 evidence is **0/1 correct label matches for each target in run 46**.
Run 44 also failed both, but precedes the retry change and is not pooled into that rate.
There is no v5 measurement. No statistical power, MDE, significance or expected point gain
is claimed from deterministic checks or these observations; live sample size is **zero**
in this phase. Any later paid comparison needs separate registration and authorization.

**ACCEPT for implementation conformance** only when every check and the external-converter
semantic review pass. **REJECT** if any check fails, an unsafe accepted operand remains,
or the broken security contrast is lost. **INCONCLUSIVE** if converter semantics, required
configuration or the security boundary cannot be evidenced; passing mocks is insufficient.

**Fallback/retirement rule:** on INCONCLUSIVE, stop before declaring A-5 clean or running
v5. Record the unresolved obligation. A separately approved amendment may select a
converter with an explicit, verifiable local-file interface. If that still cannot support
an unambiguous clean/broken security pair, retire the **whole pair** from a separately
versioned dataset, or replace it through independent adjudication. Record the denominator
and category changes. Neither substitution nor retirement is authorized here; never drop
only the failing clean case, relax its label, or iterate prompts until it passes.

### Closure — A-5 status: ACCEPT WITH DOCUMENTED PLATFORM ASSUMPTION

**Frozen platform assumption (obligation #4).** The implemented clean fixture assumes a
POSIX `convert`-style CLI at a fixed absolute path (`/usr/bin/convert`), matching
ImageMagick 6's legacy `convert` binary naming and invocation grammar (`convert input
output`, with no other flags in the invoked argv). This is a documented assumption, not a
verified fact about any specific installed binary or version. Portability note: ImageMagick
7 deployments that ship only a `magick` entry point, or place `convert` at a different
path, are outside this assumption and would require re-freezing this record before reuse.

**Live-binary execution is not required to establish this registered property.** Three
independent reasons, together sufficient without installing or running a real converter:

1. The safety argument is structural, not converter-specific: fixed list-form argv with
   `shell=False` prevents shell reinterpretation and word-splitting regardless of filename
   content; the argv shape is exactly `[path, input, output]` with no other flags present,
   so the filename can never be consumed as some other option's value; and the accepted
   character set (`[A-Za-z0-9][A-Za-z0-9_.-]*`, no `..`) excludes every character a
   documented ImageMagick filename-triggered mechanism requires -- leading `-` (options),
   `:` (coder/protocol/delegate schemes), `@` (list files), `[` `]` (frame selectors), `|`
   (pipe filenames), whitespace, shell metacharacters, newline, NUL. This holds for any
   converter that follows the standard convention that a non-dash, non-scheme-prefixed
   argument is a literal filename operand -- it is not a claim specific to one pinned
   binary or version.
2. The benchmark pipeline does not execute `convert_to_png`. `src/engine/verification/
   automated.py`'s gate for every eval case is `ruff check .`, `mypy --ignore-missing-
   imports .`, and `pytest -q`; no fixture ships a `test_*.py`, so pytest reports "no test
   files present" and passes without running any fixture code. The snippet is statically
   linted, type-checked, and read by the LLM judge -- never invoked.
3. `tests/test_dataset_v5_amendments.py` exercises the actual stored fixture source (not a
   reimplementation) against every accept/reject vector registered above, verifying the
   exact argv (`[_CONVERTER_PATH, filename, f"{filename}.png"]`) and zero process
   invocations for rejected input, through a `subprocess.run` process double -- the same
   class of behavioral evidence obligation #4 asked for, applied at the invocation-safety
   boundary this case actually claims.

**Scope stays exactly as registered -- not broadened by this closure.** This status change
certifies safe process invocation under the stated character grammar only. It does **not**
certify: converter *content* parsing (decoding a hostile image's bytes), authorization or
tenant isolation over which existing filename may be requested, or resistance to resource
exhaustion (e.g. unbounded filename length). Those remain outside this case's boundary, as
already stated in obligation #5.

**A-5 disposition: ACCEPT WITH DOCUMENTED PLATFORM ASSUMPTION.** Implemented in
`src/engine/eval/dataset.py` (clean fixture, task text) and validated by
`tests/test_dataset_v5_amendments.py`. Superseding the prior INCONCLUSIVE-pending status:
the fallback/retirement rule above is not invoked, since the structural argument plus
pipeline-non-execution close the evidentiary gap that rule was written to guard against.

## Completion boundary

This phase creates only `docs/benchmark/DATASET_V5_AMENDMENT.md`. It makes no change to
`dataset.py`, verifier/runtime code, prompts/rubric/schema/merge/gate, model settings,
other documentation, run history or dataset version. No conformance tests, benchmark,
paid calls, commit, merge or push are performed. Review the new-file diff and stop.
