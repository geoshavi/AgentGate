# Debug Agent (`engine debug`)

Agent #2. Give it a reported failure, a workspace, and a command that
reproduces the failure; it reproduces the bug, diagnoses it, applies the
smallest fix, and then **proves** the fix by re-running the same reproduction
and the full regression suite before AgentGate reviews the change.

It exits 0 only when both halves hold:

```
PASSED  iff  the frozen reproduction passes
        AND  the full regression suite passes
        AND  AgentGate verification returned OK
```

Design and rationale:
[`DEBUG_AGENT_MVP_BLUEPRINT.md`](design/DEBUG_AGENT_MVP_BLUEPRINT.md).

## What it actually claims

Be precise about this, because the words in this space are usually oversold.
The Debug Agent does **not** prove a program correct and does not prove it
found the true cause of anything. What it demonstrates is narrower and
checkable:

- A command that **failed** before the run **passes** after it.
- The full suite that was green before is still green.
- Three independent judge lenses plus ruff/mypy/pytest reviewed the resulting
  code and did not block it.
- Every file that changed is named by the workspace ledger, not by the model.

A stated root cause is the one thing here that only a model can supply, and no
code can check that a stated mechanism is the true one. It is reported as a
*claim*, with a harness-computed confidence label saying how well the captured
traceback corroborates the location it names. The proof gate is what actually
holds the line.

## Running it

```powershell
engine debug "<the reported bug>" --workspace <directory> --repro=<token> ...
```

**The workspace is edited in place.** Point it at a copy unless you want the
changes. It refuses to run against this engine's own source tree — an agent
that can edit `verification/verdict.py` can edit the thing that judges it.

### Commands are argv, never shell strings

There is no shell anywhere in this path. `--repro` and `--suite` are
**repeated flags, one argv token each**, and every token is passed to the child
process verbatim: nothing is word-split, glob-expanded, or interpreted.

Use the `--flag=value` spelling for every token. It is *mandatory* for any
token starting with `-` (argparse would otherwise read `-q` as an option), and
using it uniformly means one rule instead of two:

```
--repro=python --repro=-m --repro=pytest --repro=-q --repro=tests/test_cart.py::test_x
```

This is more verbose than a quoted command line, and deliberately so. A single
`--repro "python -m pytest -q tests/..."` would have to be split by something,
and every splitter — the shell's, `shlex`'s, ours — is a place where a token
containing a space, a quote or a semicolon means something other than what was
typed.

### The bundled example

```powershell
Copy-Item -Recurse examples\cart_bug "$env:TEMP\cart_bug"

engine debug "Asking for the total of an empty cart crashes instead of returning shipping." `
  --workspace "$env:TEMP\cart_bug" `
  --repro=python --repro=-m --repro=pytest --repro=-q `
  '--repro=tests/test_cart.py::test_empty_cart_is_shipping_only' `
  --budget 0.25
```

Note the single quotes around the token containing `::`. PowerShell passes a
single-quoted token through untouched, which is the safest habit for any token
carrying punctuation.

What the run does:

1. Runs the reproduction. It fails with
   `ValueError: min() arg is an empty sequence` — **REPRODUCED**, and the
   traceback names `cart.py:24`.
2. Diagnoses: `_discount` computes the cheapest price *before* checking the
   cart has contents, so an empty cart reaches `min()`.
3. Fixes: moves the count check ahead of the minimum. One file, a few lines.
4. Proves: the same frozen reproduction now exits 0, and `python -m pytest -q`
   is green — including `test_bulk_discount_applies_to_the_cheapest_item`,
   which the tempting shortcut fix (make the discount unconditionally zero)
   breaks.
5. Verifies: AgentGate runs ruff, mypy, pytest and its three judge lenses over
   the workspace and returns OK.
6. Reports **PASSED**, exit 0.

### If the bug report contains quotes

PowerShell 5.1 mangles embedded double quotes on their way to a native
program. Put the report in a file instead — a file has no quoting rules:

```powershell
engine debug --task-file bug.txt --workspace "$env:TEMP\cart_bug" `
  --repro=python --repro=-m --repro=pytest --repro=-q `
  '--repro=tests/test_cart.py::test_empty_cart_is_shipping_only'
```

Exactly one of the positional argument and `--task-file` may be given.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | **PASSED** — the fix was proven *and* AgentGate returned OK |
| `1` | **UNVERIFIED** — the run reached a conclusion and it was not a pass: the fix was not proven, or AgentGate blocked it, or verification could not run |
| `2` | The run never reached a verdict — could not reproduce, no validated root cause, an unusable workspace, or a refused command |

`1` and `2` are deliberately distinct: "we looked and it did not hold up" and
"we never got there" are different results, and a script needs to tell them
apart. In particular **could not reproduce is a `2`**, not a `0`: nothing was
demonstrated, and nothing was changed.

## Options

| Flag | Default | Purpose |
| --- | --- | --- |
| `task` (positional) | — | The reported bug, as a user would describe it |
| `--task-file PATH` | — | Read the reported bug from a file instead |
| `--workspace` | *required* | Directory the agent may read and edit, in place |
| `--repro=TOKEN` | *required* | One argv token of the reproduction command; repeat per token |
| `--suite=TOKEN` | `python -m pytest -q` | One argv token of the regression suite; repeat per token |
| `--provider` | `anthropic` | Provider |
| `--model` | provider's coding model | Model for diagnosis and the fixing session |
| `--judge-model` | provider's judge model | Model for the three judge lenses |
| `--budget USD` | `ENGINE_PLANNED_BUDGET` | Hard spend ceiling, enforced *before* each call |
| `--max-tokens` | `ENGINE_MAX_TOKENS` | Token ceiling |
| `--timeout SECONDS` | 600 | Wall-clock deadline for the fixing session |
| `--repro-timeout SECONDS` | 120 | Deadline for one run of the reproduction or the suite |
| `--max-turns` | 30 | Model turns in the fixing session, shared across repair rounds |
| `--max-repairs` | 2 | Proof-driven repair rounds |
| `--max-files` | 3 | Distinct files the fix may change |
| `--json PATH` | — | Also write the report JSON here |

`--max-files 3` is worth a sentence. "Prefer minimal fixes over broad
rewrites" is an instruction a model can ignore; the workspace refusing the
fourth changed file is not. It is a mechanism, not a prompt line.

## The flow, in order

```
validate workspace
  freeze reproduction argv          policy-checked
  freeze regression argv            policy-checked, before anything can edit
    reproduce                       no model call yet
      exit 0 / timeout / denied  ->  ABORTED_NO_REPRO, exit 2, zero edits
    build bounded evidence          traceback frames inside the workspace only
    diagnose                        one call, one retry, validated against disk
      no validated root cause    ->  ABORTED_NO_ROOT_CAUSE, exit 2, zero edits
    fix                             bounded session, anchored edits only
    prove                           frozen reproduction, then the full suite
      not proven                 ->  UNVERIFIED, exit 1
    verify                          AgentGate, unchanged
      not OK                     ->  UNVERIFIED, exit 1
    PASSED, exit 0
```

Two properties of that order are load-bearing:

**Nothing is edited without an observed failure.** The reproduction gate runs
before a model is called at all. A command that exits 0, times out, is refused
by the command policy, or cannot run produces no evidence, and a fix made
against no evidence is an unfalsifiable guess.

**The commands cannot move.** The reproduction is frozen at the start and
exposed to the fixing session only through a `run_repro` tool that takes **no
arguments**. An agent that could pass its own argv could narrow a failing test
until it passed and the report would read as a fix.

## The proof gate

Two commands, in this order, run by the harness after the session ends:

1. The **frozen reproduction** must now exit 0. If it does not, the suite is
   not run at all — its answer could not change the verdict, and "the
   reproduction still fails" is the clearer feedback.
2. The **full regression suite** must exit 0. This is what catches the classic
   debugging failure: the targeted test goes green and a neighbour breaks. A
   targeted-only gate would report that as success.

A failed proof is fed back to the agent as a repair round — deterministic
evidence citing a real command and a real exit code, not a critique. Repair
rounds are bounded by `--max-repairs`, and turn and time allowances are shared
across rounds, so repairs cannot extend a session past its own bounds.

The fixing session's own status and the proof are separate claims and stay
separate. A session that hit its turn ceiling may still have fixed the bug, so
the gate runs either way; a session that ended cleanly with "fixed the bug"
over a failing reproduction is UNPROVEN.

## AgentGate verification

`engine debug` calls the **same verification path** `engine code` uses, with no
change to its semantics: the same `run_verification` signature, the same three
judge lenses, the same automated ruff/mypy/pytest gates, the same severity
thresholds, and `verdict.gate` as the only thing that can return OK.

Two caller-side decisions sit on this side of that boundary:

**AgentGate runs only on a proven fix.** `PASSED` already requires both halves,
so verifying an unproven patch cannot change the outcome — it can only spend
three judge calls producing a verdict the report is forbidden to act on. The
proof gate can withhold a pass; it can never grant one.

**Verification is terminal.** There is no second repair loop around AgentGate.
The repair budget is spent by the proof gate, whose feedback is a failing
command rather than prose, and a second fixing system with weaker evidence is
not something this MVP wants. When AgentGate blocks a proven fix, the run
reports UNVERIFIED with the defects attached, and a human decides.

Verification **fails closed** in every degraded case — a verifier exception, an
exhausted budget mid-verification, malformed judge output, a failed automated
gate, or a workspace snapshot too large to inline honestly. Each of those ends
the run UNVERIFIED, exit 1. None of them can produce a pass.

## Reading the report

The report separates **three** kinds of claim, as three nested objects, so the
distinction survives into JSON:

| Block | What it holds | Who produced it |
| --- | --- | --- |
| `observed` | exit codes, the reproduction before and after, the suite, changed and inspected files, commands run | the harness, by running things |
| `claimed` | the root cause summary, mechanism, location, proposed fix, and the fixing session's closing sentence | a model |
| `agentgate` | OK/UNVERIFIED, defects, automated gate results, schema errors | `verdict.gate` |

`status` is computed from `observed.proof_status` and `agentgate.status` and
from nothing else. Nothing in `claimed` can move it.

`observed.files_changed` comes from the workspace ledger — a record of writes
that actually happened — never from what the model said it changed. The
terminal rendering prints the observed block and the AgentGate block *before*
the claimed block, for the same reason.

The one field that crosses the line is `claimed.root_cause.confidence`, and it
crosses in the safe direction: it is **computed** by the harness from the
captured traceback (`OBSERVED` / `CORROBORATED` / `INFERRED`) and a
model-supplied value is discarded. It sits in the claimed block because it
qualifies a claim.

Artifacts land in `.engine/debugagent/<session-id>/`:

| File | Contents |
| --- | --- |
| `report.json` | The full structured report |
| `session.jsonl` | One record per reproduction attempt, diagnosis attempt, model call, tool call, proof run and verification step |

`session.jsonl` stores counts of model text, never the text itself. No
chain-of-thought and no prompts are written to disk or to the report.

### `--json` shape

```json
{
  "task_id": "dbg-4c19ae",
  "run_id": 41,
  "workspace": "C:\\Temp\\cart_bug",
  "reported_bug": "Asking for the total of an empty cart crashes ...",
  "repro_command": ["python", "-m", "pytest", "-q", "tests/test_cart.py::test_empty_cart_is_shipping_only"],
  "suite_command": ["python", "-m", "pytest", "-q"],
  "status": "PASSED",
  "reason": "the reproduction passes, the regression suite is green, and AgentGate verified the change",
  "phase_reached": "DONE",
  "observed": {
    "reproduced": true,
    "repro_status": "REPRODUCED",
    "evidence": {"exception_type": "ValueError", "suspect": {"file": "cart.py", "line": 24}, "...": "..."},
    "repro_before": {"argv": ["python", "..."], "exit_code": 1, "timed_out": false, "duration_ms": 412},
    "repro_after":  {"argv": ["python", "..."], "exit_code": 0, "timed_out": false, "duration_ms": 388},
    "suite_after":  {"argv": ["python", "-m", "pytest", "-q"], "exit_code": 0, "timed_out": false, "duration_ms": 501},
    "proof_status": "PROVEN",
    "proof_stage": "PROVEN",
    "proof_reason": "the reproduction passes and the regression suite is green",
    "files_changed": ["cart.py"],
    "files_inspected": ["cart.py", "tests/test_cart.py"],
    "commands_run": [{"argv": ["python", "..."], "exit_code": 0, "timed_out": false, "duration_ms": 388}],
    "tool_results": [{"tool": "replace_exact", "ok": true, "exit_code": null, "error": null}],
    "repair_rounds": 0,
    "fix_session_status": "COMPLETED_UNVERIFIED",
    "turns_used": 2,
    "tool_calls": 1
  },
  "claimed": {
    "root_cause": {
      "summary": "the bulk discount computes the cheapest price before checking the cart has contents",
      "mechanism": "min() runs over an empty generator because the BULK_UNITS check comes after it",
      "primary_file": "cart.py",
      "primary_line": 24,
      "proposed_fix": "take the BULK_UNITS check first",
      "confidence": "OBSERVED",
      "related_files": [],
      "evidence_refs": ["the traceback names cart.py:24 in _discount"],
      "validation_plan": [["python", "-m", "pytest", "-q"]]
    },
    "diagnosis_status": "OK",
    "diagnosis_attempts": 1,
    "diagnosis_errors": [],
    "fix_summary": "moved the empty-cart guard ahead of min()"
  },
  "agentgate": {
    "ran": true,
    "status": "OK",
    "reason": "AgentGate verification passed",
    "defects": [],
    "automated_gates": [{"gate": "ruff", "passed": true, "detail": "All checks passed!"}],
    "schema_errors": [],
    "snapshot_files": 3,
    "snapshot_bytes": 2841
  },
  "usage": {
    "model_calls": 2,
    "input_tokens": 20,
    "output_tokens": 40,
    "thinking_tokens": 0,
    "tokens_spent": 150,
    "spend": "0.0011000",
    "elapsed_ms": 1839
  }
}
```

`usage.model_calls` and the token counts cover the diagnosis and fixing phases,
from each phase's own per-call accounting; judge lens calls are not visible to
either. `tokens_spent` and `spend` come from the shared budget controller and
therefore *do* include the judges. They are different measurements and are
reported as such rather than reconciled into one number that would be wrong for
both. `thinking_tokens` is a count; reasoning text is never carried.

## Safety

Everything the Coding Agent guarantees, inherited by construction — the same
`Workspace`, the same `CommandPolicy`, the same tool implementations:

- Every path goes through one guard: absolute paths, `..`, and symlink or
  junction escapes are refused, as are credential-shaped files (`.env`,
  `id_rsa`, `*.pem`, `.git/`, …) on **read** as well as write. That applies to
  file paths parsed out of a traceback too — a frame pointing outside the
  workspace is dropped, never resolved.
- Commands are argv lists, never shell strings, `shell=False`, from a short
  allowlist (`python`, `pytest`, `ruff`, `mypy`, `git`). Git is restricted to
  read-only subcommands.
- Child processes get a scrubbed environment with API keys removed.

Plus two the fixing phase adds:

- **No `run_command` and no `write_file`.** The fixing tool set omits both, so
  there is no path by which a model can run a narrower test or rewrite a file
  wholesale. Edits are anchored exact replacements that must match once.
- **`run_repro` takes no arguments.** The reproduction cannot be redirected,
  narrowed, or replaced.

**This is a policy layer, not a sandbox.** There is no container, seccomp, or
namespace. An allowlisted `python` running a test the agent just edited could
reach the network or the wider filesystem. What you get is a narrow argv
surface, a forced working directory, a bounded runtime, and a scrubbed
environment — not proof of confinement. Run it on code you are willing to see
changed.

## Fixtures

| Fixture | Purpose |
| --- | --- |
| `examples/cart_bug/` | The traceback points at the line that raised, which is **not** where the fix belongs; the obvious shortcut fix passes the reproduction and breaks the suite |

`examples/cart_bug/TASK.md` carries the reported bug and the exact commands.
The fixture is committed **broken**: `python -m pytest -q` inside it reports
`1 failed, 3 passed`. If it does not, the fixture has been edited and no longer
proves anything.

## MVP limitations

Stated plainly, because each one is a thing this does not do:

- **One reproduction attempt.** A flaky failure that reproduces once and then
  passes for an unrelated reason would be treated as fixed. There is no
  repeat-N reproduction and no flakiness statistic.
- **The root cause is not verified, only validated.** The harness checks that
  the named file and line exist and computes how well the traceback
  corroborates them. Whether the stated mechanism is the real one is not
  checkable by any code here.
- **The suite is whatever you name.** "The full regression suite passes" means
  the argv you passed exited 0. If that command covers little, the gate proves
  little.
- **Python tracebacks only.** Evidence parsing understands CPython and pytest
  failure formats. A non-Python failure still yields valid evidence — exit code
  and bounded output tails — but no frames and no suspect line, so diagnosis
  works from less.
- **No interactive debugging.** No breakpoints, no stepping, no `pdb`.
- **No post-verification repair.** When AgentGate blocks a proven fix the run
  stops and reports; it does not try to satisfy the judges.
- **Single workspace, edited in place.** No branch, no commit, no revert. Undo
  is whatever your version control gives you.
