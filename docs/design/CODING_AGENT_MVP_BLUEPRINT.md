# Coding Agent MVP — Technical Blueprint

Agent #1 of AgentGate. Branch `feature/coding-agent-mvp`, based on `f1e2123`
(Phase 9E safe-retry state + committed retry-safety tests).

Status: **blueprint only. No implementation code exists yet.**

---

## 0. Prime directive

AgentGate's value is a 19-run measurement history and a validated 88.0% (SD 0.447)
benchmark result. The Coding Agent is a **new client** of that system, never a
modification of it.

Concretely, this blueprint commits to:

- **Zero edits to the measured path** — `eval/dataset.py`, `eval/runner.py`,
  `verification/{judge,rubric,schema,verdict,pipeline}.py`,
  `runtime/{gateway,budget}.py`.
- **Zero edits to the existing Research → Coding → Testing path** —
  `orchestrator/manager.py`, `orchestrator/agents/*`, `agents/registry.py`.
  The existing `CodingAgent(PromptFileAgent)` stays byte-identical; the benchmark
  and `engine run` keep using it.
- All new code lives under `src/engine/codeagent/`, a leaf client of
  `runtime/`, `verification/`, `state/`, `config`.

If any step below turns out to require touching the measured path, that step stops
and is raised, per `git-safety`.

---

## 1. MVP user experience

```
$ engine code "parse_due_date('') fails with an unhelpful error. It should
               raise ValueError('due date must not be empty'). Fix it and add
               a regression test." --repo ./examples/todo_cli
```

The agent then, on one screen:

```
session  cd-8f3a1c              workspace  .engine/codeagent/cd-8f3a1c/ws
plan     3 steps, 2 target files

  1  list_files      .                              12 files
  2  read_file       todo.py                        1.4 KB
  3  grep            parse_due_date                 3 hits
  4  replace_in_file todo.py                        1 replacement
  5  write_file      test_due_date.py               new, 640 B
  6  run_command     python -m pytest -q            ok (4 passed)
  7  git_diff        --stat                         2 files, +18 -1

verification  OK        turns 7/25   repairs 0/2
tokens 31,204/100,000   spend $0.0416/$1.00   elapsed 71s

report  .engine/codeagent/cd-8f3a1c/report.json
diff    .engine/codeagent/cd-8f3a1c/final.diff
```

Exit code `0` only when verification returns `OK`. Every other outcome is non-zero
and still emits a full report.

The agent works in a **copy** of the target repo. The user's tree is never touched;
the deliverable is a diff the user applies themselves.

---

## 2. Exact capabilities

| # | Capability | Mechanism |
|---|---|---|
| 1 | Receive a real coding task | `engine code "<task>" --repo <path>` |
| 2 | Inspect a repository | `list_files`, `read_file`, `grep` tools |
| 3 | Identify relevant files | Model-driven, via those tools; recorded in the plan's `target_files` |
| 4 | Concise implementation plan | One bounded planning call before the loop; validated `Plan` dataclass |
| 5 | Read and edit files through real tools | `read_file`, `write_file`, `replace_in_file` |
| 6 | Run commands/tests | `run_command`, argv-allowlisted, `shell=False` |
| 7 | Observe failures | Real stdout/stderr/exit code fed back as the next observation |
| 8 | Bounded repair attempts | `MAX_REPAIR_ROUNDS = 2`, incremental (no workspace wipe) |
| 9 | Inspect the final diff | `git_diff` tool + `final.diff` artifact |
| 10 | Pass work through AgentGate verification | `verification.pipeline.run_verification`, called unchanged |
| 11 | Structured final report | `FinalReport` → `report.json` + terminal summary |

---

## 3. Explicit non-capabilities

Deliberately out of scope for the MVP. Each is a decision, not an oversight.

- **No Debug Agent, no Refactoring Agent.** Explicitly deferred.
- **No multi-agent coordination.** One agent, one session, sequential.
- **No parallel tool calls.** Exactly one tool call per turn (see §7).
- **No native provider tool-use.** Text protocol only (see §7 for why).
- **No git write operations.** No `add`, `commit`, `push`, `reset`, `checkout`,
  `stash`, `clean`, `rebase`, `merge`, `tag`. Read-only git subcommands only.
- **No network access from tools.** No `curl`, `wget`, `pip`, `npm` in the allowlist.
  (Not a hard sandbox guarantee — see §11.)
- **No package installation.** The workspace uses the host interpreter as-is.
- **No large-repo verification.** `read_code_snapshot` inlines every `*.py` in the
  workspace; the MVP pre-checks that size and aborts cleanly above the cap rather
  than modifying measured-path code. MVP targets small repos.
- **No non-Python repos.** The automated gates are ruff/mypy/pytest.
- **No resumable sessions.** A session runs once; a crash means rerun.
- **No LLM-driven choice of which agent to use.** That is the orchestrator's job.
- **No new DB tables.** MVP reuses `runs` + `agent_execution_metrics` and writes its
  transcript to JSONL (see §15).
- **No chain-of-thought persistence.** Ever. See §15.

---

## 4. Architecture

```
                    engine code (cli)
                           |
                   CodingSession  ..................  the only stateful object
                   /       |      \
              Planner   TurnLoop   Reporter
                           |
                 +---------+---------+
                 |                   |
            Protocol            ToolRegistry
         (parse/render)               |
                          +-----------+-----------+
                          |           |           |
                        fs.py     shell.py     diff.py
                          |           |           |
                          +----- Workspace -------+     path guard
                                      |
                                CommandPolicy           argv guard
                           - - - - - - - - - - -
                                      |
     LLMGateway (unchanged)  <---  BudgetController (unchanged)
                                      |
     verification.pipeline.run_verification (unchanged)
                                      |
                        verdict.gate  ->  OK | UNVERIFIED
```

Dependency direction is strictly downward. `codeagent/` imports `runtime/`,
`verification/`, `state/`, `engine.config`. Nothing imports `codeagent/`.

**Architecture-rule impact.** `codeagent/` must not import `providers/` or an SDK —
Rules A/B already cover this by placement. Rule D's eval allowlist is
`{engine.eval, engine.verification, engine.runtime, engine.state}` plus `engine.config`,
so `engine.codeagent` is *already* forbidden inside `eval/` with no test change. One new
rule is proposed:

> **Rule G:** nothing under `eval/`, `verification/`, `runtime/`, `state/`, or
> `orchestrator/` may import `engine.codeagent`. The agent is a leaf client; if the
> verification system ever depends on the thing it verifies, the benchmark stops
> measuring what it claims to measure.

Rule G is a new test in `tests/test_architecture.py`. That file is not on the measured
path, and the addition is purely additive.

---

## 5. Agent execution loop

```
build workspace (copy repo, git init if absent, record base commit)
plan()                                  1 LLM call, bounded, validated

for turn in 1..MAX_TURNS:                              # default 25
    check deadline / token budget / spend budget       # breach -> terminal
    response = gateway.generate(messages)              # budget enforced pre-call
    parsed = protocol.parse(response.text)

    match parsed:
        ToolCall   -> policy.check() -> tool.run() -> observation
        Final      -> break
        ParseError -> observation("malformed tool call: ...")
                      parse_errors += 1
                      if parse_errors > MAX_PARSE_ERRORS: terminal
    messages.append(assistant=response.text)
    messages.append(user=render(observation))
    record TurnRecord -> session.jsonl

final_diff = git diff
status, merged, automated = run_verification(...)      # unchanged

for repair in 1..MAX_REPAIR_ROUNDS:                    # default 2
    if status == "OK": break
    feedback = build_retry_feedback(merged)            # reused, unchanged
    re-enter the turn loop with feedback appended      # NO workspace reset
    status, merged, automated = run_verification(...)

emit FinalReport
```

**Why repair does not reset the workspace.** `manager.py` wipes the workspace before
every attempt because its agents regenerate whole files from scratch, so leftovers from
a prior attempt are contamination. An editing agent's entire value *is* the accumulated
diff — wiping it would discard the work and force a from-scratch rewrite of files the
agent never intended to author. This single behavioural difference is the strongest
argument for a separate loop rather than a fifth entry in `AGENT_REGISTRY`.

**Turn budget and repair budget are separate counters.** Repair rounds consume turns
from the same `MAX_TURNS` pool, so a repair storm cannot extend the session; the number
of *verification rounds* is capped independently at `MAX_REPAIR_ROUNDS`.

---

## 6. Tool abstraction

```python
@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict[str, object]

@dataclass(frozen=True)
class ToolResult:
    ok: bool
    output: str            # already truncated; exactly what the model sees
    truncated: bool
    error: str | None = None

class Tool(Protocol):
    name: str
    description: str       # rendered into the system prompt
    def run(self, args: dict, workspace: Workspace) -> ToolResult: ...
```

`TOOL_REGISTRY: dict[str, Tool]`, mirroring `AGENT_REGISTRY`'s shape so the codebase
reads consistently.

| Tool | Args | Notes |
|---|---|---|
| `list_files` | `path=""`, `max_depth=3` | Respects `.gitignore`; denylisted paths are invisible |
| `read_file` | `path`, `start=1`, `end=None` | Line-numbered; capped at `MAX_READ_BYTES` |
| `grep` | `pattern`, `glob=None` | Fixed-string or regex; capped hit count |
| `write_file` | `path`, `content`, `overwrite=False` | Refuses to clobber unless `overwrite=True` |
| `replace_in_file` | `path`, `find`, `replace` | `find` must occur **exactly once** |
| `run_command` | `argv: list[str]` | Policy-checked; see §11 |
| `git_diff` | `stat=False` | Read-only; diffs against the recorded base commit |

Every result is truncated to `MAX_TOOL_OUTPUT_BYTES` (default 8000) with
`truncated=True` set, so the model is *told* it is seeing a partial result rather than
silently receiving one.

---

## 7. Tool protocol — the pivotal decision

The `Provider` protocol accepts `list[Message]` where `Message` is
`{role: "user"|"assistant", content: str}`, and returns `GenerationResult.text`, a
flattened join of text blocks. There is no tool-use surface anywhere in the chain.

**Option A — native Anthropic tool-use.** Extend `Message` to carry content blocks,
extend `GenerationResult` with `tool_use` blocks, add a `tools` parameter to
`Provider.generate` and `LLMGateway.generate`.
*Rejected:* requires editing `llm_types.py`, `providers/base.py`,
`anthropic_provider.py`, and `runtime/gateway.py`. The last is measured-path, and every
judge lens call flows through the same function. Changing it invalidates comparability
with all 19 stored runs to buy an ergonomic win for one new feature.

**Option B — text protocol over the existing `generate()`.** The agent emits exactly one
fenced tool call per turn; the loop parses it, executes it, and appends the result as
the next user message.
*Recommended.* Zero measured-path changes. Works with every provider in the tree,
including those with no tool-use support.

**Option C — a second gateway with native tool-use, parallel to the first.**
*Rejected:* two budget-enforcement paths is precisely the "complexity invisible in a
diff" that `CLAUDE.md` warns about, and it makes `BudgetExceededError` reachable from
two places with independent accounting.

### The grammar (Option B)

An assistant turn ends with exactly one fenced block — either a tool call:

    ```tool
    {"name": "read_file", "args": {"path": "todo.py"}}
    ```

or a finish:

    ```final
    {"summary": "...", "files_changed": ["todo.py", "test_due_date.py"]}
    ```

Parser rules, all strict and all fail-loud:

1. Exactly one ` ```tool ` **or** one ` ```final ` block per turn. Zero → `ParseError`.
   Two or more → `ParseError` — never "take the first"; ambiguity is a bug, not a
   preference.
2. Block body must be valid JSON with a `name` present in `TOOL_REGISTRY`.
3. Unknown tool name, missing required arg, or wrong arg type → `ParseError`.
4. A `ParseError` becomes a real observation ("your last message contained no valid tool
   call; emit exactly one ```tool block") and counts a turn. After `MAX_PARSE_ERRORS`
   (default 3) the session aborts.

**Honest cost of Option B.** A text protocol is measurably less reliable than native
tool-use — malformed calls do happen. The mitigation is that malformation is *loud,
bounded, and counted*, never silently repaired. If parse-error rates prove unacceptable
in practice, that is evidence for revisiting Option A as its own pre-registered change
with explicit measured-path approval — not something to smuggle in later.

---

## 8. Task state model

```python
@dataclass(frozen=True)
class Plan:
    summary: str
    steps: list[str]          # 1-7 items, each one line
    target_files: list[str]   # best-effort; advisory, not binding

@dataclass
class TurnRecord:
    index: int
    tool_call: ToolCall | None
    result: ToolResult | None
    parse_error: str | None
    text_chars: int           # a COUNT, never the text (see §15)
    latency_ms: int

@dataclass
class SessionState:
    session_id: str
    run_id: int               # FK into the existing runs table
    task_id: str              # attribution key for agent_execution_metrics
    task_text: str
    workspace: Workspace
    plan: Plan | None
    turns: list[TurnRecord]
    repairs_used: int
    parse_errors: int
    status: SessionStatus
    stop_reason: str

@dataclass
class FinalReport:
    status: SessionStatus
    stop_reason: str
    plan: Plan | None
    files_changed: list[str]
    diff_stat: str
    verification_status: str | None     # "OK" | "UNVERIFIED" | None if never reached
    defects: list[dict]                 # verdict.merge output, unmodified
    automated_gates: list[VerificationResult]
    turns_used: int
    max_turns: int
    repairs_used: int
    tokens_spent: int
    spend: Decimal                      # Decimal, never float
    duration_ms: int
```

```python
class SessionStatus(str, Enum):
    PASSED           = "PASSED"            # verification returned OK
    UNVERIFIED       = "UNVERIFIED"        # ran to completion, verdict blocked
    ABORTED_TURNS    = "ABORTED_TURNS"
    ABORTED_BUDGET   = "ABORTED_BUDGET"
    ABORTED_DEADLINE = "ABORTED_DEADLINE"
    ABORTED_POLICY   = "ABORTED_POLICY"    # repeated denied commands
    ABORTED_PROTOCOL = "ABORTED_PROTOCOL"  # parse errors exhausted
    ERROR            = "ERROR"             # provider/internal failure
```

`PASSED` is set from `verdict.gate`'s return value and nowhere else. No LLM, and no code
in `codeagent/`, may write it directly.

---

## 9. Workspace isolation

```python
class Workspace:
    root: Path              # .engine/codeagent/<session_id>/ws, resolved
    base_commit: str | None

    def resolve(self, relative: str) -> Path:
        """Resolve `relative` inside root, or raise WorkspaceEscape."""
```

Construction: copy `--repo` into the session workspace (`shutil.copytree`, ignoring
`.git`, `.venv`, `__pycache__`, `node_modules`), then `git init` plus one baseline
commit so `git diff` has something to diff against. The user's tree is opened read-only,
once.

`resolve()` rules, applied to every path from every tool:

1. Reject absolute paths.
2. Reject any path whose resolved form is not `is_relative_to(root)` — the same guard
   `orchestrator/agents/common.py:write_files` already uses. That *pattern* is reused
   rather than reinvented, but `codeagent/` gets its own copy: importing it would make
   the agent depend on the legacy execution path this blueprint keeps separate.
3. `Path.resolve()` resolves symlinks, so a symlink pointing outside `root` fails the
   same check. Explicitly tested.
4. Reject a **path denylist**, matched after resolution:
   `.env`, `.env.*`, `*.pem`, `*.key`, `id_rsa*`, `.git/config`, `.git/hooks/**`,
   `.aws/**`, `.ssh/**`, `.engine/**`, `**/secrets*`.
   Denied paths are invisible to `list_files` and `grep`, and rejected by `read_file`,
   `write_file`, and `replace_in_file` — reading a secret is as much a leak as writing
   one, since it lands in the transcript.

---

## 10. Editing strategy

**Anchored search/replace**, not full-file rewrite and not unified diff.

- `replace_in_file(path, find, replace)` requires `find` to appear **exactly once**.
  Zero occurrences → error observation hinting to `read_file` first. Two or more → error
  observation asking for a longer anchor. Never "replace the first match".
- `write_file` is for **new** files. Overwriting an existing file requires
  `overwrite=True`, which is recorded distinctly in the transcript, and is refused
  outright above `MAX_OVERWRITE_BYTES` so "rewrite the whole module" cannot masquerade
  as an edit.

Rationale: full-file rewrite burns output tokens proportional to file size and is how
the current `PromptFileAgent` silently loses code it did not think to re-emit. Unified
diff is compact but brittle — one line of context drift makes the patch unapplicable,
and the model cannot see the failure coming. Exact-anchor replace fails loudly, cheaply,
and in a way the model can correct on the next turn.

**Mass-deletion guard.** Any `replace_in_file` whose `replace` is empty and whose `find`
exceeds `MAX_DELETE_BYTES` (default 2000) is refused, as is any `write_file` that would
truncate a non-empty file to empty.

---

## 11. Command execution policy

```python
@dataclass(frozen=True)
class CommandPolicy:
    allowed: frozenset[str]
    git_subcommands: frozenset[str]
    timeout_seconds: float = 120.0     # mirrors automated.py's TIMEOUT_SECONDS
```

- **argv only.** `run_command` takes `list[str]`. `shell=False`, always. A single string
  is a type error, not a convenience — `shell=True` is how every injection in this class
  of tool happens.
- **`argv[0]` allowlist:** `python`, `python3`, `pytest`, `ruff`, `mypy`, `git`.
  `python`/`python3` are normalised to `sys.executable`, so the agent cannot select an
  interpreter outside the environment.
- **git subcommand allowlist:** `status`, `diff`, `log`, `show`, `ls-files`,
  `rev-parse`. Everything else denied, which covers `push`, `reset`, `clean`,
  `checkout`, `commit`.
- **Denied-token scan** across the whole argv: `--force`, `-f` for `git`, `..`, `rm`,
  `sudo`, `curl`, `wget`, `pip`, `chmod`, `>`, `|`. The last two are meaningless without
  a shell, so their presence signals the model expects one — worth failing on.
- **cwd is forced** to `workspace.root`; the tool exposes no cwd parameter.
- **Environment is scrubbed.** The child gets a minimal env with `ANTHROPIC_API_KEY`,
  `OPENAI_API_KEY`, `GOOGLE_API_KEY`, and `AWS_*` removed, so a command that does run
  cannot exfiltrate a credential.
- **Timeout** per command; a timeout is a real observation ("timed out after 120s"), not
  a failure of the session.
- **Output truncated** to `MAX_TOOL_OUTPUT_BYTES`, with `truncated=True`.

**Stated non-guarantee.** This is a policy layer, not a sandbox. It uses no containers,
seccomp, or namespaces, so it cannot *prove* a process stayed inside the workspace or
off the network — a Python script the agent writes and then runs with an allowlisted
`python` could do either. The allowlist deliberately excludes network tools, and the env
scrub removes the credentials worth stealing, but the honest claim is "narrow argv
surface plus scrubbed env", not "sandboxed". Container isolation is a post-MVP item, and
the MVP's own demo runs on a throwaway fixture repo.

---

## 12. Planning behavior

One LLM call before the loop, capped at `PLAN_MAX_TOKENS` (default 1200). It receives
the task text and a shallow file listing — *not* file contents; discovery is the loop's
job.

Output is a fenced JSON `Plan`. Validation is structural only, mirroring
`validate_execution_plan`'s discipline of never judging content:

- `summary` non-empty
- `1 <= len(steps) <= 7`
- each step non-empty and single-line
- `target_files` may be empty — the model is allowed not to know yet

A malformed plan is retried **once**, then the session proceeds planless with
`plan=None` recorded. The plan is advisory context, never a constraint on which tools
may run: binding the loop to a plan written before any file was read would be optimising
the wrong thing.

---

## 13. Retry / repair limits

| Bound | Default | Enforced by | On breach |
|---|---|---|---|
| `MAX_TURNS` | 25 | `CodingSession` | `ABORTED_TURNS` |
| `MAX_REPAIR_ROUNDS` | 2 | `CodingSession` | stop, report last verdict |
| `MAX_PARSE_ERRORS` | 3 | `protocol` + session | `ABORTED_PROTOCOL` |
| `MAX_DENIED_COMMANDS` | 3 | `CommandPolicy` + session | `ABORTED_POLICY` |
| Token budget | `config.max_tokens` | `BudgetController` (unchanged) | `ABORTED_BUDGET` |
| Spend budget | `config.planned_budget` | `BudgetController` (unchanged) | `ABORTED_BUDGET` |
| Wall-clock deadline | `config.timeout_seconds` | session deadline check | `ABORTED_DEADLINE` |
| Per-command timeout | 120s | `subprocess.run(timeout=)` | observation, not terminal |
| Per-call timeout | `min(120, remaining)` | passed to gateway | provider error |

Budget and deadline are **terminal, never retried** — the same reasoning `manager.py`
documents: the budget does not replenish and the clock does not reset, so retrying burns
the remaining attempts for nothing.

---

## 14. AgentGate verification integration

`codeagent/verify.py` is a thin adapter. It calls:

```python
run_verification(
    workspace.root, gateway, budget, judge_model, task_text,
    run_id=state.run_id, task_id=state.task_id, conn=conn,
    timeout_seconds=min(120.0, remaining),
)
```

**unchanged, with no new parameters and no new hooks.** It returns
`(status, merged, automated_results)`; `codeagent/` reads them and never recomputes a
verdict. `build_retry_feedback(merged)` is likewise reused as-is to produce repair
feedback — the same function the existing retry loop uses, so repair feedback has one
implementation, not two.

**The snapshot-size pre-check.** `read_code_snapshot` inlines every `*.py` under the
workspace. On a real repo that is unbounded. Since `pipeline.py` is measured-path, the
bound goes in the caller: before verifying, `verify.py` sums the same glob and, above
`MAX_SNAPSHOT_BYTES` (default 200 KB), skips verification and ends the session
`UNVERIFIED` with `stop_reason="workspace too large for verification"`. That is a
truthful, fail-closed outcome — never a silent partial verification, and never a claim
the work passed.

---

## 15. Logging / observability

Artifacts under `.engine/codeagent/<session_id>/`:

| File | Contents |
|---|---|
| `session.jsonl` | One JSON object per turn: index, tool name, args, `ok`, truncated output, latency, token counts |
| `plan.json` | The validated `Plan`, or `null` |
| `report.json` | The `FinalReport` |
| `final.diff` | `git diff` against the base commit |
| `ws/` | The working copy |

LLM-call metrics need no new code: passing `conn`, `run_id`, and `task_id` into
`gateway.generate` writes an `agent_execution_metrics` row per call — model, tokens,
cache tokens, latency, `Decimal` spend, `stop_reason`, `text_chars` — including on
failure. `agent_name` is `"CodingAgent.plan"` / `"CodingAgent.turn"` /
`"CodingAgent.repair"` so the phases separate in analysis. The session row comes from
`db.create_run`. **No schema migration.**

### No hidden chain-of-thought

Persisted: plans, tool calls, tool arguments, tool results, verification output,
metrics, and `text_chars` **counts**. Not persisted: the model's prose reasoning outside
a tool block, and `thinking` content of any kind.

This matches a decision the codebase already made deliberately — `GenerationResult`
carries `thinking_tokens` as a count, with a docstring stating the reasoning text "is
deliberately never carried here." The agent inherits that rule rather than inventing
one. In-flight conversation history necessarily holds the current turn's text; nothing
writes it to disk.

---

## 16. Failure behavior

Fail closed, and never fabricate.

- **Never simulate a tool result.** Every observation is a real return value from a real
  call. There is no code path that synthesises plausible output — if a tool cannot run,
  the observation says so.
- **Provider error** → one retry for transport-shaped failures, then `ERROR`.
- **Budget / deadline** → immediate terminal status; report still emitted.
- **Denied command** → error observation, counter incremented; `ABORTED_POLICY` at 3.
  A denial is visible to the model so it can choose differently.
- **Workspace escape attempt** → error observation plus a `SECURITY` entry in the
  report. Not silently dropped.
- **Verification `UNVERIFIED` after repairs exhausted** → status `UNVERIFIED`, defects
  reported in full. A legitimate outcome, not a crash.
- **Any abort still writes `report.json` and `final.diff`.** Partial work stays
  inspectable; the status says plainly that it was partial.
- Exit code is `0` **only** for `PASSED`.

---

## 17. Proposed folder / module structure

```
src/engine/codeagent/
    __init__.py
    session.py          CodingSession: the loop, all bounds, terminal statuses
    protocol.py         parse(text) -> ToolCall | Final | ParseError; render(result)
    plan.py             Plan + parse_plan + validate_plan
    state.py            ToolCall, ToolResult, TurnRecord, SessionState, SessionStatus
    workspace.py        Workspace: construction, resolve(), path denylist
    policy.py           CommandPolicy: argv allowlist, denied tokens, env scrub
    verify.py           adapter over verification.pipeline (+ snapshot pre-check)
    report.py           FinalReport assembly, JSON + terminal rendering
    log.py              JSONL session writer
    prompts/
        system.md       agent contract: tool grammar, safety rules, one call per turn
        planner.md      planning prompt
    tools/
        __init__.py
        base.py         Tool protocol, ToolResult helpers, truncation
        registry.py     TOOL_REGISTRY + get_tool()
        fs.py           list_files, read_file, write_file, replace_in_file
        search.py       grep
        shell.py        run_command
        diff.py         git_diff

tests/codeagent/
    test_workspace.py   path guard, symlinks, denylist
    test_policy.py      allowlist/denylist matrix, env scrub
    test_protocol.py    parse grammar, malformed, multi-block
    test_tools_fs.py    replace_in_file arity, overwrite guard, delete guard
    test_tools_shell.py real subprocess, timeout, truncation
    test_plan.py        plan validation
    test_session.py     loop, bounds, terminal statuses (FakeProvider)
    test_verify.py      adapter + snapshot pre-check (stub judge)
    test_report.py      report assembly + serialization
    test_e2e_demo.py    marked, opt-in, real API
```

`engine/cli.py` gains one `code` subparser. That file is not on the measured path; the
change is additive and touches no existing subcommand.

---

## 18. Tests

**Unit — no network, no LLM, no API key.**

- `workspace`: absolute path rejected; `../` rejected; symlink-to-outside rejected;
  `.env` and `.git/config` invisible to `list_files` and rejected by `read_file`;
  legitimate nested path accepted.
- `policy`: each allowlisted `argv[0]` accepted; `git push` / `git reset` / `rm` /
  `curl` / `sudo` rejected; `--force` rejected; string-instead-of-list is a type error;
  the scrubbed env contains no `*_API_KEY`.
- `protocol`: one valid tool block parses; zero blocks → ParseError; two blocks →
  ParseError; invalid JSON → ParseError; unknown tool → ParseError; a `final` block
  parses; a fenced tool block appearing *inside* a `read_file` result does not confuse
  the parser.
- `tools/fs`: `replace_in_file` with 0 / 1 / 2 matches; `write_file` refusing to
  clobber; empty-replace mass-delete guard; truncation sets `truncated=True`.
- `tools/shell`: `python -c "print(1)"` really runs; a sleep exceeds the timeout and
  returns a timeout observation; large output truncates.
- `plan`: valid plan; 0 steps rejected; 8 steps rejected; malformed JSON → retry-once
  path; planless fallback recorded.
- `session` bounds: turn cap → `ABORTED_TURNS`; `BudgetExceededError` →
  `ABORTED_BUDGET`; expired deadline → `ABORTED_DEADLINE`; 3 parse errors →
  `ABORTED_PROTOCOL`; 3 denials → `ABORTED_POLICY`. Each asserts a report was still
  written.
- `report`: round-trips to JSON; `Decimal` spend never becomes a float.
- `test_architecture.py`: **Rule G** — no module under `eval/`, `verification/`,
  `runtime/`, `state/`, or `orchestrator/` imports `engine.codeagent`; and no module
  under `codeagent/` imports `engine.providers` or an SDK.
- **Regression guard:** the existing `PromptFileAgent` path is untouched —
  `tests/test_agents.py`, `test_manager.py`, `test_orchestrator.py`, and
  `test_verification.py` must pass unmodified. Any required edit to those files is a
  signal that the isolation broke.

**Integration — `FakeProvider`, still no network.**

A scripted provider returning a fixed turn sequence, following the existing
fake-provider pattern in `tests/test_manager.py`.

- Happy path: plan → list → read → replace → run pytest → final → report `PASSED`.
- Failure-observation path: pytest fails, the agent reads the output, edits again,
  passes. Asserts the *real* failure text reached the next prompt.
- Repair path: verification returns `UNVERIFIED`, `build_retry_feedback` is fed back,
  the second round returns `OK`; asserts the workspace was **not** reset and the
  first-round edits survived.
- Repair exhaustion: two rounds, still `UNVERIFIED` → final status `UNVERIFIED` with
  defects listed.
- Snapshot pre-check: an oversized workspace ends `UNVERIFIED` with the size stop_reason
  and makes **no** judge call.

**E2E — real API, opt-in.**

Marked `@pytest.mark.e2e`, skipped without `ANTHROPIC_API_KEY` and without
`ENGINE_E2E=1`. Never part of the default `pytest` gate, so no test run can spend money
by accident.

---

## 19. Concrete end-to-end demo task

Fixture repo `examples/todo_cli/` — new, small, self-contained:

```python
# todo.py
def parse_due_date(raw: str) -> tuple[int, int, int]:
    parts = raw.split("-")
    return int(parts[0]), int(parts[1]), int(parts[2])   # unhelpful ValueError on ""
```

```python
# test_todo.py
def test_parses_iso_date():
    assert parse_due_date("2026-08-21") == (2026, 8, 21)
```

**Task given to the agent:**

> `parse_due_date('')` fails with an unhelpful error. It should raise
> `ValueError("due date must not be empty")` instead. Fix it and add a regression test.

`""` splits to `[""]`, so `int(parts[0])` raises
`ValueError: invalid literal for int() with base 10: ''` before any index can go
out of range — the defect is the *unhelpful message*, not an `IndexError`.

**Expected trajectory** — exercises all 11 capabilities from §2:

| Turn | Tool | Demonstrates |
|---|---|---|
| — | plan | 4 |
| 1 | `list_files .` | 2 |
| 2 | `grep parse_due_date` | 3 |
| 3 | `read_file todo.py` | 5 (read) |
| 4 | `replace_in_file todo.py` | 5 (edit) |
| 5 | `write_file test_due_date.py` | 5 (create) |
| 6 | `run_command [python, -m, pytest, -q]` | 6, 7 |
| 7 | `git_diff --stat` | 9 |
| — | verification + report | 10, 11 |

The task is deliberately small enough that the whole workspace fits under
`MAX_SNAPSHOT_BYTES`, so verification runs for real.

**A second fixture is required, not optional.** A variant where the obvious fix breaks
the existing ISO-date test, so the demo proves the agent *observes a real failure and
repairs*. A one-shot success would leave capabilities 7 and 8 untested by the demo.

---

## 20. MVP acceptance criteria

The MVP is done when **all** of the following hold. Each is checkable, and none is a
benchmark-accuracy claim.

1. `ruff check .`, `mypy .`, and `pytest` all pass on the branch.
2. `git diff f1e2123 --stat` shows **no** changes to any measured-path file, and none to
   `orchestrator/manager.py`, `orchestrator/agents/*`, or the verification modules.
3. The pre-existing test suite passes **unmodified** — the only test-file change is the
   Rule G addition to `test_architecture.py`.
4. Every unit and integration test in §18 exists and passes offline, with no API key
   present.
5. `engine code "<task>" --repo examples/todo_cli` completes against the live API and
   returns `PASSED` with exit code 0.
6. The repair-fixture variant returns `PASSED` after **at least one observed real test
   failure**, proving capabilities 7 and 8.
7. Every safety requirement has a test demonstrating the refusal: no push, no
   `reset --hard`, no mass deletion, no `.env` read or write, no path outside the
   workspace, no unallowlisted binary.
8. `report.json`, `session.jsonl`, `plan.json`, and `final.diff` are produced for both a
   passing and an aborted session.
9. `session.jsonl` and `report.json` contain **no** model prose reasoning — only
   structured records and counts. Asserted by a test.
10. Each of the eight bounds in §13 has a test proving the correct terminal status.
11. The user's source repo is byte-identical after a run — verified by hashing before
    and after.
12. `agent_execution_metrics` rows exist for every LLM call in a session, attributable
    by `(run_id, task_id)`.

Explicitly **not** an acceptance criterion: any benchmark score. Per `CLAUDE.md`, code is
verified by the gates; a hypothesis is verified by a pre-registered experiment. This
change is not expected to move the benchmark, and if a run happens to follow it, that is
not evidence about this work.

---

## 21. Phased implementation plan

Each phase ends green on `ruff` + `mypy` + `pytest` and is independently committable.
Phases 1–3 involve **no LLM call and no API key at all**, which is where most of the
safety surface lives.

| Phase | Scope | Deliverable | Gate |
|---|---|---|---|
| **P1 — Ground** | `workspace.py`, `policy.py`, `tools/*`, `state.py` | Every tool works and is bounded; no model anywhere | `test_workspace`, `test_policy`, `test_tools_*` green; Rule G added and green |
| **P2 — Loop** | `protocol.py`, `session.py`, `log.py` | Full turn loop driven by `FakeProvider`; all bounds terminal | `test_protocol`, `test_session` green; each §13 bound proven |
| **P3 — Plan** | `plan.py`, `prompts/*` | Planning call, validation, planless fallback | `test_plan` green |
| **P4 — Verify** | `verify.py`, `report.py` | `run_verification` integration (unchanged), repair loop, snapshot pre-check, report artifacts | `test_verify`, `test_report` green; repair-survives-workspace test green |
| **P5 — Ship** | `cli.py` subcommand, `examples/todo_cli/` + repair fixture, E2E | `engine code` end to end | §20 criteria 1–12 all satisfied |

**Sequencing rationale.** P1 first because the safety guarantees are the part that must
not be retrofitted — a path guard added after the tools exist is a guard with unknown
coverage. P2 before P3 because a planless loop is a working agent, while a plan without
a loop is a paragraph. P4 last among the non-shipping phases because it is the only one
that touches AgentGate, and by then everything it integrates is already proven.

**Rollback shape.** Each phase adds files under `codeagent/` and `tests/codeagent/`;
none modifies an existing module except `cli.py` (P5, additive) and `test_architecture.py`
(P1, additive). Reverting any phase is a directory deletion plus one revert, and cannot
leave the existing engine in a changed state.

---

## 22. Open decisions

Assumptions taken to keep this blueprint complete. Each is cheap to change now and
expensive later.

1. **Copy-in, diff-out** (§9) rather than editing the user's repo in place. Chosen for
   safety; means the user applies the diff themselves.
2. **`engine code` as a new CLI subcommand**, rather than a flag on `engine run`. Keeps
   the old path's surface untouched.
3. **JSONL transcript, no new DB tables** (§15). Defers a schema decision until there is
   a real query to serve.
4. **Defaults**: 25 turns, 2 repairs, 200 KB snapshot cap, 8 KB tool-output cap. Round
   numbers, not measured — expected to move once real sessions exist.
5. **Judge model** defaults to `DEFAULT_MODELS[provider]["judge"]`, the same as the rest
   of the system.
