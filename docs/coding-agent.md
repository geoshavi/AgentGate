# Coding Agent (`engine code`)

Agent #1. Give it a task and a workspace; it plans, edits files with real
tools, runs the tests, and then puts the result through AgentGate
verification. It exits 0 only if AgentGate says OK.

Design and rationale: [`CODING_AGENT_MVP_BLUEPRINT.md`](design/CODING_AGENT_MVP_BLUEPRINT.md).

## Running it

```powershell
engine code "<task>" --workspace <directory>
```

**The workspace is edited in place.** Point it at a copy unless you want the
changes. It refuses to run against this engine's own source tree — an agent
that can edit `verification/verdict.py` can edit the thing that judges it.

Try it on the bundled fixture:

```powershell
Copy-Item -Recurse examples\todo_cli "$env:TEMP\todo_cli"

$task = "parse_due_date('') fails with an unhelpful error. Make it raise " +
        "ValueError('due date must not be empty') for empty input, and add " +
        "a regression test."

engine code $task --workspace "$env:TEMP\todo_cli" --budget 0.25
```

The task text is a single argument, so it is assembled into `$task` rather
than split with a line-continuation backtick. `--budget 0.25` is a hard
ceiling enforced before each model call.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | AgentGate verified the work |
| `1` | The work was reviewed and **blocked** — defects, a failed gate, or verification declined |
| `2` | The agent or the runtime failed — it never reached a verdict |

`1` and `2` are deliberately distinct: "reviewed and rejected" and "never got
there" are different results.

## Options

| Flag | Default | Purpose |
| --- | --- | --- |
| `--workspace` | *required* | Directory the agent may read and edit |
| `--provider` | `anthropic` | Provider |
| `--model` | provider's coding model | Model for the agent |
| `--judge-model` | provider's judge model | Model for the three judge lenses |
| `--budget USD` | `ENGINE_PLANNED_BUDGET` | Hard spend ceiling, enforced *before* each call |
| `--max-tokens` | `ENGINE_MAX_TOKENS` | Token ceiling |
| `--timeout SECONDS` | 600 | Wall-clock deadline for the whole run |
| `--max-turns` | 25 | Model turns, shared across repair rounds |
| `--max-repairs` | 2 | Verification-driven repair rounds |
| `--json PATH` | — | Also write the report JSON here |

Budget and deadline are terminal, never retried: the budget does not
replenish and the clock does not reset.

## What it does, in order

1. **Validate the workspace** — must exist, be a directory, and not be this
   engine's tree. Refusal happens before any model call, so a bad path costs
   nothing.
2. **Build bounded repo context** — a shallow file listing, names and sizes
   only, no contents, with credential files filtered out.
3. **Plan** — one bounded call, structurally validated. Paths are checked
   against the workspace guard and validation commands against the command
   policy, so a plan that names `git push` is rejected at plan time rather
   than at turn 12. An unusable plan is *not* fatal: the run continues and
   records that it had no plan.
4. **Run the turn loop** — one tool call per turn, every bound terminal.
5. **Verify** — the existing `run_verification` unchanged: three judge
   lenses, ruff/mypy/pytest, and `verdict.gate` as the only thing that can
   say OK.
6. **Repair, bounded** — structured defects go back to the agent. The
   workspace is **not** reset between rounds; a repair continues from the
   accumulated diff.
7. **Report** — JSON and a human summary.

## Reading the report

The report carries **two** status fields, and the difference is the point:

- `agent_status` — what the agent did (`COMPLETED_UNVERIFIED`, `ABORTED_*`).
- `status` — what AgentGate concluded (`PASSED`, `UNVERIFIED`).

The agent saying "done" is a claim about effort. `PASSED` is a claim about
correctness, and only `verdict.gate` can make it.

`files_changed` comes from the workspace ledger — a record of writes that
actually happened — never from what the model said it changed.

Artifacts land in `.engine/codeagent/<session-id>/`:

| File | Contents |
| --- | --- |
| `report.json` | The full structured report |
| `session.jsonl` | One record per planning attempt, model call, tool call, and verification step |

`session.jsonl` stores counts of model text, never the text itself. No
chain-of-thought is written to disk.

## Safety

- Every path goes through one guard: absolute paths, `..`, and symlink or
  junction escapes are refused, as are credential-shaped files (`.env`,
  `id_rsa`, `*.pem`, `.git/`, …) on **read** as well as write.
- Commands are argv lists, never shell strings, `shell=False`, from a short
  allowlist (`python`, `pytest`, `ruff`, `mypy`, `git`). Git is restricted to
  read-only subcommands, which is what makes `push`, `commit`, `reset`,
  `clean` and `checkout` unreachable.
- Child processes get a scrubbed environment with API keys removed.
- Edits are anchored exact replacements: the anchor must match exactly once,
  and zero or multiple matches are explicit errors rather than a guess.

**This is a policy layer, not a sandbox.** There is no container, seccomp, or
namespace. An allowlisted `python` running a script the agent just wrote could
reach the network or the wider filesystem. What you get is a narrow argv
surface, a forced working directory, a bounded runtime, and a scrubbed
environment — not proof of confinement. Run it on code you are willing to see
changed.

## Fixtures

| Fixture | Purpose |
| --- | --- |
| `examples/todo_cli/` | Straightforward: the obvious guard works first time |
| `examples/todo_cli_repair/` | The obvious guard (a length check) breaks an existing whitespace test, so the agent must observe the failure and repair |

Each carries a `TASK.md` with the exact task text.
