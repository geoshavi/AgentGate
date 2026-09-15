# AgentGate v1.0.0

AgentGate is an AI agent orchestration engine: an orchestrator analyzes a
task, builds a validated execution plan, dispatches specialized sub-agents
under enforced token/spend limits, then runs their output through a
multi-layer verification pipeline (automated gates + independent LLM-judge
review) before accepting it. No LLM ever decides pass/fail directly — a pure,
model-free function owns the verdict, and any CRITICAL/HIGH defect, a failed
automated gate, or a malformed judge response all block, fail-closed.

## Key capabilities

- Single-provider (Anthropic) sequential multi-agent orchestration —
  coding, research, testing, and refactoring roles.
- Automated gates (`ruff` / `mypy` / `pytest`) plus a 3-lens LLM-judge review
  (correctness, security, code-quality), merged into one deterministic
  `OK` / `UNVERIFIED` verdict.
- Every LLM call — agents and judge lenses alike — routes through a single
  gateway that enforces a token/spend budget before the call and records
  usage after it; exceeding a limit raises and terminates the run instead of
  retrying silently.
- Two purpose-built engineering agents beyond `engine run`: a Coding Agent
  that edits an existing workspace in place, and a Debug Agent that
  reproduces a reported bug, fixes it, and proves the fix against the frozen
  reproduction and the full regression suite before verification runs.
- SQLite run history and per-call cost/latency metrics for every call,
  including failures.

## CLI surface

| Command | Purpose |
| --- | --- |
| `engine run "<task>"` | Generate code for a task; verified before being accepted |
| `engine code "<task>" --workspace <dir>` | Bounded coding task against an existing workspace |
| `engine debug "<bug>" --workspace <dir> --repro=<token>` | Reproduce, fix, and prove a bug fix |
| `engine bench [--dry-run]` | Run, or validate without calling any API, the `engine-review-benchmark` suite |

See [`docs/coding-agent.md`](docs/coding-agent.md) and
[`docs/debug-agent.md`](docs/debug-agent.md) for full flag references and
exit-code contracts.

## Test status

1,875 tests: **1,872 passed, 3 skipped.**

## Benchmark status

Measured against the project-specific `engine-review-benchmark` v2 suite —
not an industry-standard external benchmark, but a falsifiability check for
changes to this engine. Current configuration: dataset v6, judge
`claude-sonnet-5`.

**Run 68** (most recent standard full 40-case run): **38/40 (95.0%)**,
`false_pass = 0`, `false_unverified = 2`. Category accuracy: correctness
100%, quality 100%, edge_case 100%, security 80%.

## Safety / verification positioning

In the recorded benchmark evidence, the current configuration had zero false
passes. That preference — a false pass is worse than a false alarm — is
enforced by what has been rejected as much as by what shipped: four separate
interventions that raised or promised to raise the benchmark score were
reverted once they were shown to increase false-pass exposure. AgentGate
does not claim universal correctness or a production guarantee; it reports
what a specific, versioned benchmark measured under a specific configuration.

## Known limitations

- `security-04-clean` is closed by adjudication, not fixed — two HIGH
  security findings map to already-adjudicated dataset/spec buckets with no
  current verifier-side resolution mechanism; deferred to a possible future
  dataset revision.
- Judge lens calls are capped at `max_tokens=1600`; on the largest fixture a
  response can still truncate, which fails closed to `UNVERIFIED`.
- Single provider (Anthropic), pinned to `anthropic>=0.40.0,<1.0.0`, and
  sequential execution — multi-provider routing and parallel sub-agents are
  not yet implemented.

See [`README.md`](README.md#known-limitations) and
[`docs/benchmark/BASELINE.md`](docs/benchmark/BASELINE.md) for the full
record.

## Installation / quick start

```
python -m venv .venv
.venv/Scripts/activate     # Windows
pip install -e ".[dev]"
cp .env.example .env       # fill in ANTHROPIC_API_KEY
engine run "write a function that checks if a string is a palindrome, with a unit test"
```
