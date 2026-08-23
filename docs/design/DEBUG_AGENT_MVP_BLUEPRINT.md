# Debug / Fix Agent — MVP Blueprint

Agent #2 in AgentGate. Takes a **reported failure** and returns a **verified fix**
with a stated root cause, or refuses.

Base: `feature/debug-agent-mvp`, branched from `cda6bf2` (Coding Agent MVP shipped).

This document is a design. No implementation code exists yet.

---

## 0. Decisions taken before design

Four questions were settled up front because each one changes the architecture.
They are recorded here because the rest of the document depends on them.

| # | Decision | Consequence |
|---|---|---|
| 1 | **Reproduction command is required** (`--repro <argv...>`) | Reproduction is a deterministic gate, not a model claim. Offline tests can be exact. |
| 2 | **New `debugagent/` package importing `codeagent/`** | Zero rewrite of just-shipped code. A small number of additive seams in `codeagent/`. |
| 3 | **Fail closed when the failure will not reproduce** | `ABORTED_NO_REPRO`, exit 2, zero files changed. No edit without observed evidence. |
| 4 | **Targeted repro + full suite must both pass** | Catches a fix that breaks a neighbour — the failure mode debugging is most prone to. |

The one thing that unifies all four: **the Debug Agent never takes the model's
word for whether the bug existed or whether it is gone.** The harness runs the
repro command before and after, and the difference is the evidence. This is the
same discipline `report.files_changed` already follows — it comes from the
workspace ledger, never from what the model said it changed.

---

## 1. MVP user experience

```
$ engine debug "cart_total crashes on an empty cart" \
      --workspace ./examples/cart_bug \
      --repro python -m pytest -q tests/test_cart.py::test_empty_cart
```

```
session  dbg-4c19ae            workspace  examples/cart_bug
repro    python -m pytest -q tests/test_cart.py::test_empty_cart

  reproduce   exit 1   ValueError: min() arg is an empty sequence   REPRODUCED
              suspect  cart.py:23 in _discount

plan     4 steps, 1 target file

  1  read_file       cart.py                        1.1 KB
  2  read_file       tests/test_cart.py             0.6 KB
  3  replace_exact   cart.py                        1 replacement
  4  run_repro       (frozen)                       exit 0   PASSES
  5  run_tests       python -m pytest -q            ok (7 passed)

fix gate     repro PASSES    suite PASSES     PROVEN
verification OK              turns 8/25       repairs 0/2

root cause   cart.py:23 _discount() calls min() on an unguarded sequence;
             an empty cart reaches it because cart_total() applies the
             discount before checking whether there is anything to discount.
             confidence OBSERVED (location named in the traceback)

fix          guard the discount computation, not cart_total's return path
             1 file, +2 -1

verdict  PASSED    tokens 24,110    spend $0.0512    elapsed 48s
report   .engine/debugagent/dbg-4c19ae/report.json
```

Exit codes stay the honest three from the Coding Agent, with one added meaning:

| Code | Meaning |
| --- | --- |
| `0` | AgentGate verified the work **and** the fix gate proved the bug is gone |
| `1` | Reviewed and blocked — defects, a failed gate, or the fix was not proven |
| `2` | Never reached a verdict — including **could not reproduce** |

---

## 2. Architecture

```
engine debug <task> --workspace DIR --repro <argv...>
      |
      v
debugagent/app.py :: run_debug_task()          composition root
      |
      +--(1) validate workspace                REUSE codeagent.workspace
      |
      +--(2) REPRODUCE  [gate, no model]       NEW  debugagent/repro.py
      |         run --repro argv               REUSE codeagent.tools.shell.execute
      |         non-zero exit -> FailureEvidence
      |         exit 0 / timeout / denied -> ABORTED_NO_REPRO, exit 2
      |
      +--(3) collect evidence  [no model]      NEW  debugagent/evidence.py
      |         exit code, bounded output tails,
      |         parsed in-workspace traceback frames, suspect frame
      |
      +--(4) plan, seeded with evidence        REUSE codeagent.plan.make_plan
      |                                              (evidence via repo_context)
      +--(5) bounded turn loop                 REUSE codeagent.session.CodingSession
      |         debug system prompt                  via a new AgentProfile
      |         + run_repro tool (frozen argv)  NEW  debugagent/tools/repro.py
      |         final block carries root cause  NEW  debugagent/protocol.py
      |
      +--(6) FIX GATE  [deterministic]         NEW  debugagent/gate.py
      |         re-run frozen repro  -> must pass
      |         run full suite       -> must pass
      |
      +--(7) AgentGate verification            REUSE codeagent.verify (unchanged
      |         + repair rounds                       semantics; new post_check seam)
      |
      +--(8) report                            NEW  debugagent/report.py
                root cause, fix, evidence,            wrapping codeagent FinalReport
                repro before/after, verdict
```

### Where the boundaries are

Each unit answers one question and can be tested without the others:

- `repro.py` — *did the reported failure actually happen?* Needs a workspace and
  an argv. No model, no gateway.
- `evidence.py` — *what did the failure tell us?* Pure function from captured
  output to a structured record. No I/O at all.
- `tools/repro.py` — *let the agent re-observe the same failure.* One tool, no
  arguments.
- `protocol.py` — *is this a well-formed root-cause claim?* Pure parsing.
- `gate.py` — *is the bug demonstrably gone and nothing else broken?* No model.
- `app.py` — wiring only.

Five of the six new modules make no model call and no network call. That is the
property that makes the offline test suite meaningful.

---

## 3. Reuse from the Coding Agent

### 3.1 Reused unchanged

| Concern | Module | Why it transfers untouched |
|---|---|---|
| Path guard, `..`/symlink/credential refusal, mutation ledger | `codeagent/workspace.py` | Debugging reads and edits the same way coding does |
| argv allowlist, denied flags, shell-metacharacter refusal, env scrub | `codeagent/policy.py` | The repro command must be policy-checked like any other |
| `list_files`, `read_file`, `search_files`, `write_file`, `replace_exact`, `run_command`, `run_tests`, `git_diff`, `git_status` | `codeagent/tools/` | A debugger needs exactly these plus one |
| `execute()` — policy check, timeout, truncation, `CommandRun` record | `codeagent/tools/shell.py` | The repro runner is a caller of this, not a second executor |
| Block-fence scanning | `codeagent/protocol.find_blocks` | Already the shared primitive; `plan.py` is the precedent |
| Turn loop, every bound, every terminal status | `codeagent/session.py` | Debugging is the same loop with a different prompt |
| Budget enforcement before each call | `runtime/budget.py`, `runtime/gateway.py` | **Measured path — not touched** |
| Three judge lenses, automated gates, `verdict.gate` | `verification/` | **Measured path — not touched. Semantics unchanged.** |
| Snapshot pre-check, defect sanitising, repair loop | `codeagent/verify.py` | Verification-driven repair is agent-agnostic |
| Two-status reporting (`agent_status` vs `status`) | `codeagent/report.py` | The distinction matters more here, not less |
| Offline `ScriptedProvider` / `ScenarioProvider` | `tests/codeagent_harness.py` | Extended, not replaced |

### 3.2 Additive seams in `codeagent/` — the honest cost

Reuse is not free. Six committed files need small, **default-preserving**
additions. Every existing call site keeps working with no change, and every
existing test must still pass untouched — that is the acceptance bar for D2.

| File | Addition | Size |
|---|---|---|
| `session.py` | `AgentProfile` dataclass + one optional `profile=CODE_PROFILE` param | ~20 lines |
| `state.py` | `Phase.REPRODUCING`, `SessionStatus.ABORTED_NO_REPRO` | 2 lines |
| `limits.py` | `repro_timeout_seconds`, `max_repro_output_bytes`, `max_evidence_frames`, `max_root_cause_chars` | ~6 lines |
| `verify.py` | optional `session_factory` and `post_check` params | ~15 lines |
| `cli.py` | `debug` subparser + dispatch branch | ~40 lines |
| `plan.py` | **none** — evidence goes through the existing `repo_context` | 0 |

**`AgentProfile`** is the one new abstraction, and it exists because
`CodingSession.run()` hard-codes four things a debugger needs to change:

```python
@dataclass(frozen=True)
class AgentProfile:
    agent_name: str                                  # metrics attribution
    build_system_prompt: Callable[[dict[str, Tool]], str]
    render_opening: Callable[[str], str]
    parse_turn: Callable[[str], ParsedTurn]

CODE_PROFILE = AgentProfile("CodingAgent.turn", protocol.build_system_prompt,
                            protocol.render_task, protocol.parse)
```

This is a knob, and `CLAUDE.md` says not to add knobs for use cases that do not
exist. The use case exists: there are exactly two concrete profiles, both
shipped. The alternative — a `DebugSession` that copies a 150-line `run()` — is
duplicated infrastructure, which is what this design was told to avoid.

**Rejected:** extracting a neutral `engine/agentkit/` package. It is the better
long-term name, but it rewrites every `codeagent` import and test for zero
behavioural gain, and `CLAUDE.md`'s surgical-changes rule exists precisely to
stop that. Revisit when Agent #3 lands and the shared core has two proven
consumers.

### 3.3 What is deliberately NOT reused

- **`RunTestsTool` is not the repro tool.** `run_tests` runs the whole suite
  with an argv the agent could vary. `run_repro` re-runs the *frozen* argv the
  caller supplied and takes no arguments at all — the agent cannot redefine what
  the bug is.
- **The Coding Agent's system prompt.** It says "make the smallest change that
  satisfies the task". A debugger needs "do not change anything until you can
  say which line is wrong and why".

---

## 4. The debugging loop

```
REPRODUCING -> PLANNING -> EXPLORING -> [EDITING <-> TESTING] -> VERIFYING -> REPORTING
     |
     +-- cannot reproduce -> ABORTED_NO_REPRO (terminal, 0 files changed)
```

`Phase` is observability only — no control flow reads it, which is why adding
`REPRODUCING` to the shared enum is safe.

### Turn budget

Debugging front-loads observation, so the defaults shift without changing the
mechanism:

```python
DEBUG_LIMITS = replace(
    DEFAULT_LIMITS,
    max_files_changed=3,          # "smallest fix" as a MECHANISM, not a prompt line
    max_turns=30,                 # more looking, less writing
    max_tool_calls=25,
    repro_timeout_seconds=120.0,
    max_repro_output_bytes=8_000,
    max_evidence_frames=10,
    max_root_cause_chars=800,
)
```

`max_files_changed=3` deserves the emphasis. "Prefer minimal fixes over broad
rewrites" is an instruction a model can ignore; `Workspace.note_changed` raising
on the 4th file is not. The existing ceiling is reused — no new mechanism.

---

## 5. Evidence collection

Deterministic, model-free, and identical on every run for the same failure —
which is what makes the offline tests exact.

```python
@dataclass(frozen=True)
class Frame:
    file: str          # workspace-relative
    line: int
    function: str

@dataclass(frozen=True)
class FailureEvidence:
    argv: list[str]
    reproduced: bool
    exit_code: int | None
    timed_out: bool
    duration_ms: int
    stdout_tail: str          # bounded by max_repro_output_bytes
    stderr_tail: str          # bounded by max_repro_output_bytes
    exception_type: str | None
    exception_message: str | None
    frames: list[Frame]       # bounded by max_evidence_frames
    suspect: Frame | None     # last in-workspace frame
```

### Traceback parsing rules

1. Scan for `File "<path>", line <N>, in <fn>` plus the trailing
   `ExceptionType: message` line. Best-effort: a non-Python failure yields
   `frames == []` and is still valid evidence — the exit code and output tails
   carry it.
2. **Keep only frames whose file resolves inside the workspace.** Stdlib and
   `site-packages` frames are noise, and an absolute path from a traceback is an
   untrusted string — it goes through `Workspace.resolve`, and a frame that
   escapes is dropped, not reported.
3. `suspect` is the **last** in-workspace frame — the deepest workspace code
   before the throw. It is a heuristic and is labelled as one.
4. **Tails, not heads.** A pytest failure puts the useful part at the end.

### What the agent is shown

Rendered into the opening message and into the planner's `repo_context`:

```
REPRODUCED FAILURE
command : python -m pytest -q tests/test_cart.py::test_empty_cart
exit    : 1
error   : ValueError: min() arg is an empty sequence
suspect : cart.py:23 in _discount
frames  : cart.py:11 in cart_total -> cart.py:23 in _discount
--- output (last 8000 chars) ---
...
```

---

## 6. Root-cause representation

The one thing the model must supply that nothing else can. It arrives in the
`final` block:

````
```final
{"root_cause": {
   "summary":   "min() is called on an unguarded sequence",
   "location":  "cart.py:23",
   "mechanism": "cart_total applies the discount before checking the cart is
                 non-empty, so _discount receives [] and min() raises",
   "evidence":  ["traceback names cart.py:23 in _discount",
                 "test_empty_cart passes [] to cart_total"]},
 "fix": "guard the discount computation rather than cart_total's return path",
 "files_changed": ["cart.py"]}
```
````

```python
@dataclass(frozen=True)
class RootCause:
    summary: str
    location: str
    mechanism: str
    evidence: list[str]
    confidence: str      # OBSERVED | INFERRED -- COMPUTED, never model-supplied
```

### What is validated, and what is not

Honest scope: **no code can check that a stated mechanism is the true cause.**
What can be checked is checked, and the rest is labelled.

| Claim | Treatment |
|---|---|
| `location` names a real file | **Validated** — through `Workspace.resolve`. A root cause pointing at a nonexistent file is a parse error. |
| `location` line is within the file | **Validated** — bounds-checked. |
| `files_changed` | **Ignored as a claim** — the report uses the ledger, as the Coding Agent already does. |
| `confidence` | **Computed, not accepted.** `OBSERVED` iff the `location` file appears in the captured traceback frames; `INFERRED` otherwise. |
| `mechanism` is correct | **Not checkable.** Rendered as the agent's stated reasoning, and the fix gate is what actually holds the line. |

Computing `confidence` rather than accepting it is the same move as deriving
`files_changed` from the ledger: where a fact is available to the harness, the
harness owns it.

---

## 7. The fix gate

Deterministic, runs after the agent finishes, **before** AgentGate:

```python
@dataclass(frozen=True)
class FixGate:
    repro_before: CommandRun     # from step 2 -- failed, by definition
    repro_after: CommandRun      # must now pass
    suite_after: CommandRun      # must pass
    proven: bool                 # repro_after.ok and suite_after.ok
    reason: str
```

### Relationship to AgentGate — no semantics change

This must be exact, because "do not change AgentGate verification semantics" is
a hard constraint:

- `run_verification` is called **unchanged**, same signature, same lenses, same
  thresholds. `verdict.gate` remains the only thing that can return `OK`.
- The fix gate **cannot turn `UNVERIFIED` into `PASSED`.** It only ever
  *withholds* a pass.

```
final status = PASSED   iff  AgentGate == OK  AND  fix_gate.proven
             = UNVERIFIED otherwise
```

Withholding a pass is not a change to AgentGate's semantics — AgentGate still
decides its own verdict and we still never claim `OK` when it did not say so. We
simply refuse to call a run successful when the bug it was asked to fix is
demonstrably still there.

### Fix-gate failure is repairable evidence

A failing fix gate is *better* repair input than a judge defect: it is
deterministic and cites a real command. `verify.py` currently repairs only on
judge defects, so it gains an optional `post_check` seam. Repair feedback:

```
FIX NOT PROVEN
The reproduction command still fails after your change.
command : python -m pytest -q tests/test_cart.py::test_empty_cart
exit    : 1
--- output ---
...
```

or, for the regression case:

```
FIX BROKE THE SUITE
The reproduction now passes, but the full suite does not.
2 failed, 5 passed
--- output ---
...
```

Repair rounds stay at `max_repair_rounds = 2`, shared with AgentGate repairs —
one budget, not two. Turn and time allowances remain shared across rounds, so
repairs cannot extend a session past its own bounds.

---

## 8. State additions

`TaskState` is the Coding Agent's serialized shape and is reused as-is. Debug
facts hang off a parallel record so the existing report shape is untouched:

```python
@dataclass
class DebugState:
    repro_argv: list[str]
    evidence: FailureEvidence | None = None
    root_cause: RootCause | None = None
    fix_description: str = ""
    fix_gate: FixGate | None = None
```

Additions to shared enums (both additive):

- `Phase.REPRODUCING`
- `SessionStatus.ABORTED_NO_REPRO`

`DebugReport` wraps `FinalReport` rather than replacing it, so every field the
Coding Agent report already carries keeps its meaning and position:

```python
@dataclass(frozen=True)
class DebugReport:
    base: FinalReport            # status, agent_status, defects, gates, usage...
    repro_argv: list[str]
    reproduced: bool
    evidence: dict[str, Any]
    root_cause: dict[str, Any] | None
    fix: str
    fix_proven: bool
    repro_before: dict[str, Any]
    repro_after: dict[str, Any] | None
    suite_after: dict[str, Any] | None
```

This directly satisfies requirement 10: root cause, files changed (`base`), fix
made, tests run (`base.commands_run` + the three gate records), verification
verdict (`base.status`).

New session-log record kinds: `repro_attempt`, `repro_result`, `fix_gate`,
`root_cause_recorded`. Counts and structure only — the existing rule that no
chain-of-thought reaches disk is unchanged.

---

## 9. Tools

One new tool. Everything else is the existing registry.

```python
DEBUG_TOOL_REGISTRY = TOOL_REGISTRY | {"run_repro": RunReproTool(frozen_argv)}
```

| Tool | Args | Behaviour |
|---|---|---|
| `run_repro` | **none** | Re-runs the caller's frozen repro argv. Cannot be redirected. Returns exit code + bounded output. |

`RunReproTool` holds the argv given at construction. It takes no arguments *by
design*: an agent that could pass its own argv could quietly narrow the failing
test until it passed, and the report would read as a fix.

`write_file`, `replace_exact`, `run_command`, `run_tests` and the read tools
carry over unchanged. `git_diff` matters more here than for coding — it is how
the agent checks its change is actually minimal.

---

## 10. Tests

All offline. No live API call, no network, no key.

| Suite | Covers |
|---|---|
| `test_debugagent_evidence.py` | Traceback parsing; frames outside the workspace dropped; path-escape frame refused; tails not heads; `max_evidence_frames` honoured; non-Python failure yields empty frames but valid evidence |
| `test_debugagent_repro.py` | Non-zero exit -> reproduced; **exit 0 -> `ABORTED_NO_REPRO`**; timeout -> `ABORTED_NO_REPRO`; policy-denied argv -> `ABORTED_NO_REPRO`; zero files changed in every abort path |
| `test_debugagent_protocol.py` | Root-cause block parsing; missing keys rejected; `location` naming a nonexistent file rejected; out-of-range line rejected; `confidence` computed `OBSERVED`/`INFERRED` and **model-supplied confidence ignored** |
| `test_debugagent_tools.py` | `run_repro` ignores any args passed; runs the frozen argv; bounded output |
| `test_debugagent_gate.py` | proven only when both pass; repro-still-fails feedback; suite-broke feedback; gate cannot upgrade `UNVERIFIED` to `PASSED` |
| `test_debugagent_app.py` | End-to-end offline via `ScenarioProvider`: happy path; no-repro abort; fix-gate failure -> repair -> pass; repair exhausted -> `UNVERIFIED` exit 1; `max_files_changed=3` abort |
| `test_codeagent_*.py` (existing) | **Must pass unchanged** — the acceptance bar for every seam in §3.2 |
| `test_architecture.py` | Rule G extended: `debugagent` is a leaf client too — never imported by `eval/`, `verification/`, `runtime/`, `state/`, and never reaches a provider SDK |

`tests/codeagent_harness.py` gains `repro_turn()`, `root_cause_final()` and a
`FakeRepro` helper. It is extended, not forked — one harness, both agents.

---

## 11. Demo bug fixtures

Mirrors the existing `todo_cli` / `todo_cli_repair` pair, and for the same
reason: one fixture proves the happy path, the other proves the repair loop.

### `examples/cart_bug/` — straightforward

```python
# cart.py
SHIPPING_FLAT = 4.99

def cart_total(items):
    subtotal = sum(i.price * i.qty for i in items)
    return subtotal + SHIPPING_FLAT - _discount(items)

def _discount(items):
    """10% off the cheapest item once the cart holds 3+ units."""
    cheapest = min(i.price for i in items)         # ValueError on []
    if sum(i.qty for i in items) < 3:
        return 0.0
    return cheapest * 0.10
```

The ordering is the bug and is load-bearing: computing `cheapest` *before* the
`< 3` check is what lets an empty cart reach `min()`. Verified — with the check
first, the empty cart short-circuits and never raises, and the fixture would
prove nothing.

Repro: `python -m pytest -q tests/test_cart.py::test_empty_cart_is_shipping_only`
→ `ValueError: min() arg is an empty sequence`.

The guard belongs in `_discount`; the existing tests stay green.

### `examples/cart_bug_repair/` — repair required

Same bug, plus an existing test:

```python
def test_empty_cart_is_shipping_only():
    assert cart_total([]) == SHIPPING_FLAT
```

The tempting fix — `if not items: return 0.0` at the top of `cart_total` — makes
the *reproduction* pass and **breaks this test**, because an empty cart still
owes shipping. The agent must observe the suite failure and move the guard into
`_discount`.

This is exactly the case a targeted-only regression policy would report as a
success, which is why decision #4 was taken.

Each fixture carries a `TASK.md` with the task text and the exact `--repro`
command, in Windows PowerShell form, matching the convention `examples/todo_cli`
already follows.

---

## 12. Acceptance criteria

Gate-checkable. `CLAUDE.md`: the criterion for a code change is `ruff`, `mypy`,
`pytest`, plus the named behaviour. Benchmark accuracy is **not** a criterion
here and no benchmark run is part of this work.

**Automated**

1. `ruff check .` passes.
2. `mypy` passes.
3. `pytest -q` passes, with **all 564 existing tests still passing unchanged**.
4. `test_architecture.py` Rule G holds for `debugagent`.

**Behavioural**

5. A repro command that exits 0 aborts with `ABORTED_NO_REPRO`, exit 2, and
   **zero files changed** — asserted against the workspace ledger.
6. A reproduced failure yields `FailureEvidence` with the correct exception type
   and a `suspect` frame inside the workspace.
7. A frame pointing outside the workspace is dropped, never resolved.
8. `run_repro` called with arguments runs the frozen argv anyway.
9. A root cause naming a nonexistent file is rejected as a parse error.
10. `confidence` is computed; a model-supplied value is ignored.
11. Fix gate proven only when repro passes **and** suite passes.
12. `PASSED` is unreachable unless AgentGate returned `OK` **and** the fix gate
    proved — asserted by a test that forces `OK` with an unproven fix and
    expects `UNVERIFIED`, exit 1.
13. Editing a 4th file aborts on the ledger ceiling.
14. `verification/`, `runtime/`, `eval/`, `providers/`, judge prompts and
    severity thresholds are **byte-identical** — asserted by `git diff --stat`
    over the measured path at review time.

**Not in scope:** live provider demo (a separate, explicitly approved step, as
with the Coding Agent), Refactoring Agent, benchmark tuning.

---

## 13. Phased implementation plan

Five phases, mirroring the Coding Agent's P1–P5. Each ends green on all three
gates and is independently committable.

| Phase | Delivers | Model calls | Key test |
|---|---|---|---|
| **D1** | `evidence.py` + `repro.py`. Repro gate, traceback parsing, frame filtering, `FailureEvidence`. Limits and enum additions. | none | exit 0 → `ABORTED_NO_REPRO`, 0 files changed |
| **D2** | `AgentProfile` seam in `session.py`; `debugagent/protocol.py` (root-cause block); `tools/repro.py`. | scripted | every existing `test_codeagent_*` still passes |
| **D3** | Debug planning — `make_plan` reused, evidence through `repo_context`. | scripted | plan seeded with the suspect frame |
| **D4** | `gate.py` + `post_check` seam in `verify.py`. Fix gate, repair feedback, status composition. | scripted | AgentGate `OK` + unproven fix → `UNVERIFIED` |
| **D5** | `app.py`, `report.py`, `engine debug` CLI, both fixtures, `docs/debug-agent.md`. | scripted | full end-to-end offline |

**D3 has an explicit escape hatch.** The plan is to reuse `plan.py` with *zero*
changes by passing evidence through the existing `repo_context` parameter. The
planner prompt will say "coding task" rather than "debugging task". If D3's
offline tests show the plans are systematically wrong for debugging — naming
unrelated files, or proposing rewrites — then and only then add an optional
`planner_prompt` param. Adding it up front would be a knob for a problem not yet
observed, which `CLAUDE.md` forbids.

### Sequencing note

D1 and D2 are independent and could be built in either order. D1 first is
deliberate: it is the phase with no model calls at all, so the whole evidence
layer is proven correct before anything nondeterministic is introduced.

---

## 14. Risks

| Risk | Mitigation |
|---|---|
| Seams in `codeagent/` regress the shipped agent | Every seam defaults to current behaviour; all 564 existing tests must pass unchanged (criterion 3) |
| Traceback parsing is brittle across formats | Best-effort by design — empty `frames` is valid evidence; exit code and output tails always carry |
| Agent "fixes" the test instead of the code | `max_files_changed=3` plus `run_repro`'s frozen argv; a fix that edits only the test still faces the full suite and the judge lenses |
| Flaky repro command reproduces once, then passes for the wrong reason | Out of MVP scope. Recorded as a known limitation; a repeat-N repro is a later option, not an MVP knob |
| `AgentProfile` becomes a dumping ground | Four fields, both instances shipped in-tree. If a third profile wants a fifth field, that is the signal to extract `agentkit/` |
| Scope creep into Refactoring Agent | Explicitly out of scope; `max_files_changed=3` makes broad rewrites structurally unreachable |

---

## 15. Explicitly out of scope

- Refactoring Agent (Agent #3).
- Any change to AgentGate verdict semantics, judge prompts, lenses, severity
  thresholds, or rubric.
- Any change to `eval/`, `runtime/`, `providers/`, or benchmark behaviour.
- Benchmark runs and benchmark tuning of any kind.
- Live provider calls — a separate step requiring explicit approval.
- Interactive debugging (breakpoints, stepping, `pdb`).
- Multi-repro / flaky-test statistics.
