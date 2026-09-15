<img width="1536" height="1024" alt="8abfc9de-d3ce-4147-96fc-db843e66f480" src="https://github.com/user-attachments/assets/fd079104-aea4-4866-bb76-93fcad8dbdad" />



# AgentGate

AgentGate is an AI agent orchestration engine: an orchestrator analyzes a
task, builds a validated execution plan, dispatches specialized sub-agents
under enforced token/spend limits, then runs their output through a
multi-layer verification pipeline (automated gates + independent LLM-judge
review) before accepting it.

AgentGate is the project name only. The Python package, the `engine` CLI
command, runtime paths (`.engine/`) and the `engine-review-benchmark` suite
keep their existing names.

## Status

Working runtime: single provider (Anthropic), sequential multi-agent execution
(coding / research / testing / refactoring), bounded retry loop, automated gates
(ruff/mypy/pytest) + 3-lens LLM-judge review, deterministic verdict, SQLite run
history and per-call metrics. 153 tests.

Every LLM call in the codebase — agents and judge lenses alike — routes through
a single gateway (`runtime/gateway.py`) that enforces a token/spend budget
before the call and records usage after it. Limits are enforced at runtime, not
merely declared: exceeding them raises `BudgetExceededError` and terminates the
run rather than retrying.

Multi-provider routing, parallel sub-agents, merge control, and long-term memory
are planned for later milestones.

### Verification architecture

No LLM ever decides pass/fail directly. Each judge lens (`verification/judge.py`)
must return structured defects as JSON, validated against a fixed schema
(`verification/schema.py`). A defect is exactly
`{id, category, severity, location, fix}`; `category` must be one of
**CORRECTNESS**, **SECURITY** or **CODE-QUALITY**, and `severity` one of
CRITICAL / HIGH / MEDIUM / LOW. There is no confidence score and no free-form
evidence field — a defect the schema does not accept is not a defect.

A pure, model-free Python function — `verification/verdict.py`'s `merge`/`gate`
— is the only code path allowed to produce an `OK`/`UNVERIFIED` verdict. The
validated defects from all three lenses are merged into one list, and then:

- **any CRITICAL or HIGH defect blocks** the verdict (`UNVERIFIED`);
- **MEDIUM and LOW findings never block** — they are reported, not gating;
- a **malformed judge response blocks** (fails closed);
- a **failed automated gate blocks**.

Severity decides the outcome. The `verdict` string a lens returns is validated
for self-consistency but never overrides the severities it was derived from.
This separation -- deterministic script owns the verdict, LLMs only supply
evidence -- was inspired by the verification harness in
[kimi-atlas](https://github.com/null0xxx/kimi-atlas). The implementation here is
this project's own.

### Runtime control

Task analysis is separated from execution. `orchestrator/task_analyzer.py`
classifies the request; `orchestrator/execution_plan.py` produces a validated
plan (steps, dependencies, token/spend/agent limits); `orchestrator/manager.py`
executes it. Agents never talk to each other directly — all coordination goes
through the orchestrator.

Cost is tracked in `Decimal` (never float) against a dated price table, and
fails closed on an unknown model rather than silently costing nothing. Per-call
metrics — model, input/output/cache tokens, latency, spend, status — are written
to SQLite after every call, including failures.

Three architecture tests enforce the invariants that make the above true:
provider SDKs may only be imported inside `runtime/` and `providers/`; only
`runtime/gateway.py` may reach into `providers/`; and `providers/` may not
import `runtime/`. These fail with the offending file and the rule it broke,
so the gateway cannot be quietly bypassed by future code.

## Benchmark

The verification pipeline is measured against a project-specific suite,
`engine-review-benchmark` v2 (`src/engine/eval/dataset.py`). **It is not an
industry-standard external benchmark** — it exists to make changes to this
engine falsifiable, not to compare this engine with others.

**Methodology.** 20 hand-written tasks × 2 variants = **40 cases**: 20 *clean*
(a correct solution, expected verdict `OK`) and 20 *broken* (one genuine
semantic, security or structural defect, expected `UNVERIFIED`). Ten cases each
in correctness, security, code-quality and edge-case. Every snippet is authored
to be `ruff`- and `mypy`-clean on its own merits, so a failed automated gate can
never be mistaken for a judge decision, and the suite deliberately mixes obvious
anchors (SQL injection, mutable default argument) with subtle ones (weak
randomness, SSRF, timing-attack comparison, Unicode truncation, non-atomic
increment) so it tests generalization rather than keyword matching.

**Result** — five runs at the same commit, dataset frozen:

| | |
| --- | --- |
| Scores | **36, 35, 35, 35, 35** |
| Mean | **35.2 / 40 = 88.0%** |
| Sample SD | **0.447** |
| False passes (broken code accepted) | **0 / 100** broken-case observations |
| Deterministic cases | 39 of 40 |
| Stable clean failures | 4 cases at 0/5 |
| Variable clean case | `edge_case-04-clean` at 1/5 — the only source of score variance |

Run it with `engine bench` (`--dry-run` validates the dataset and prints the cost
plan without making a single API call).

### Safety philosophy

**A false pass is worse than a false alarm.** Accepting broken code silently
defeats the point of the pipeline; flagging correct code wastes a review. The
verdict path is fail-closed everywhere — a malformed judge response, a failed
automated gate, or any CRITICAL/HIGH defect all block.

That preference is not just stated, it is enforced by what has been *rejected*.
Four separate interventions raised or promised to raise the score and were
reverted once the evidence arrived:

| Intervention | Why it was reverted |
| --- | --- |
| Severity reordering (emit severity after the analysis) | +3 cases, but bought with false-pass exposure |
| Verdict normalization | 2 false passes in a single run |
| Demonstrability prompt (“name the input that shows the defect”) | the model fabricated plausible inputs that were simply false |
| Executed-witness verification | **26 false passes in 100 broken-case observations** |

The engine shipped here is the one that never accepted broken code, not the one
that scored highest. Each attempt is written up in its own `docs/experiments/PHASE8*.md` artifact,
including the measurements that killed it.

### Known limitations

- **Four clean cases fail consistently** (`correctness-02-clean`,
  `security-02-clean`, `security-04-clean`, `edge_case-03-clean`), which caps this
  configuration at 36/40. The judge blocks them on claims that are factually
  wrong, spec-irrelevant, or an implementation preference. A read-only analysis
  (`docs/experiments/PHASE8E0_SAFE_IMPROVEMENT_SELECTION.md`) found no general, deterministic fix
  that does not also risk accepting their broken twins, so the search was stopped
  rather than continued unsafely.
- **`edge_case-04-clean` is variable** (1/5) — it flips on a single defect
  crossing the MEDIUM/HIGH boundary, and is the sole source of run-to-run score
  variance.
- **Judge lens calls are capped at `max_tokens=800`.** On the largest fixture a
  response occasionally truncates, which fails closed to `UNVERIFIED`. Raising it
  is a cost and comparability trade-off, not a free fix, so it is left as a known
  operational limit.
- **Single provider** (Anthropic) and sequential execution.

## Project documentation

- `docs/benchmark/` — benchmark design, amendments, changelog, historical baseline
- `docs/experiments/` — pre-registered experiments and rejected intervention evidence
- `FINAL_PROJECT_STATUS.md` — release-candidate summary
- `DEFERRED_FIXES.md` — intentionally deferred engineering issues

## Developer tooling: dependency graph

`tools/research_graph.py` renders a local architecture/dependency view of the
codebase into `graphify-out/` (`graph.html`, `graph.json`, `GRAPH_REPORT.md`).
Open `graphify-out/graph.html` in a browser to explore module relationships.

It is a **developer aid only** — it is gitignored, plays no part in the
verification pipeline, and has no influence on any verdict or benchmark score.

## Setup

```
python -m venv .venv
.venv/Scripts/activate     # Windows
pip install -e ".[dev]"
cp .env.example .env       # fill in ANTHROPIC_API_KEY
```

## Usage

```
engine run "write a function that checks if a string is a palindrome, with a unit test"
```

Generated code lands in `.engine/workspace/`, a run report in `.engine/report.md`,
and full run/verification history in `.engine/state.db`.

## Tests

```
pytest
```

## n8n (local workflow automation)

Runs via Docker Compose alongside `engine-api`, a small HTTP wrapper around the
same verification pipeline `engine run` uses — the difference is `engine-api`
reviews code you already wrote instead of generating new code first.

```
docker compose up -d      # start n8n (:5678) + engine-api (:8000)
docker compose down       # stop (data persists in the n8n_data / engine_review_data volumes)
```

Uses `N8N_ENCRYPTION_KEY` from `.env` (generate with `openssl rand -hex 32`);
changing it after workflows/credentials exist makes stored credentials
unreadable.

### Code-review webhook

`engine-api`'s only endpoint:

```
POST /review
{
  "task": "what this code is supposed to do",
  "files": {"solution.py": "...", "test_solution.py": "..."}
}
```

Returns `{"status": "OK" | "UNVERIFIED", "defects": [...], "automated_results": [...]}` —
same deterministic verdict, same orchestrated correctness/security/code-quality
judge lenses as `engine run`, just skipping code generation.

Import `n8n-workflows/code-review.json` into n8n (menu → *Import from File*) to get
a ready `Webhook -> Call Engine Review -> Respond to Webhook` workflow. It POSTs
whatever the webhook receives straight to `http://engine-api:8000/review` (reachable
by service name on the compose network) and echoes the JSON verdict back as the
HTTP response — call it with:

```
curl -X POST http://localhost:5678/webhook/review \
  -H "Content-Type: application/json" \
  -d '{"task": "add two numbers", "files": {"add.py": "def add(a, b):\n    return a - b\n"}}'
```

**Known limitation:** the automated gates run `pytest` on submitted files directly
in the `engine-api` container — there is no sandboxing beyond the container
boundary itself. Don't expose this webhook to the public internet without adding
auth and/or real sandboxing in front of it.
