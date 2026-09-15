# AgentGate Capabilities Layer — MVP Blueprint

**Status:** design only. Nothing in this document is implemented.
**Base commit:** `b20d7331db8dca317264897ffbbbe8878f3330d7`
**Branch:** `feature/agent-capabilities-layer`
**Revision:** rev 3 — standards/reference validation pass. Changes in §19.
**Scope:** three capabilities — Agent Skills, Context7 MCP, Testing/Test Detection —
added *before* Agent #3 (Refactoring Agent), so Agent #3 inherits them rather than
motivating a third copy of the same wiring.

**External references consulted** (rev 3), treated as data, never as instructions:

| Reference | Used for |
|---|---|
| `agentskills.io/specification`, `/home` | authoritative SKILL.md frontmatter, directory shape, progressive-disclosure levels |
| `github.com/upstash/context7` (README, verbatim "Available Tools") | real Context7 MCP tool + parameter names |
| `hermes-agent.nousresearch.com/docs/…/work-with-skills`, `…/skills-catalog` | a second, independent progressive-disclosure implementation to compare against |
| `aitmpl.com/skills`, `mcpmarket.com` | community catalogues — evidence for the deferred-marketplace trust decision |

---

## 0. Decisions taken before design

1. **The session loop does not change.** `CodingSession` already accepts `tools`,
   `system_prompt` and `agent_name`. Its own docstring says those seams exist so the
   Debug Agent's fix session can be "this same loop with a different brief" rather than
   a second loop. Three capabilities that arrive as *tools plus prompt text* need
   exactly those seams and nothing more.

2. **A capability is a tool, or it is not reachable.** `RunReproTool` is the precedent:
   a per-session tool instance constructed with frozen state, injected through
   `build_fix_tools(repro) -> dict[str, Tool]`, advertised by a generated system prompt.

3. **The capability package is a leaf.** It must not import `codeagent` or `debugagent`
   — the discipline `llm_types.py` is held to by Rule F.

4. **Trust is established by time-ordering and immutability, never by location.**
   A skill is trusted because it was read into an immutable snapshot *before any
   mutating tool existed*, not because of where it sits on disk (§4).

5. **`load_skill` never touches the filesystem.** It serves only pre-session snapshot
   content. There is no re-read, re-stat or re-digest at load time, for any reason
   including observability (§4.3).

6. **Conform to the Agent Skills standard; extend only through `metadata`.** The
   standard's required fields are `name` and `description`. AgentGate reads any
   spec-conformant skill with no extension required, and its own additions live under
   the standard-sanctioned `metadata` map (§4.5).

7. **Frontmatter is parsed by a real YAML parser (`yaml.safe_load`), not a hand-rolled
   reader.** The specification says frontmatter is YAML; a fixed-key reader would reject
   syntactically valid skills that use only standard fields — folded scalars, quoted
   values containing `:`, comments — and the 1024-character `description` makes folded
   scalars the common case, not an edge case. Writing a partial YAML parser to avoid a
   YAML dependency produces more code, more bugs, and less compatibility. Parsing
   produces **data only** and grants nothing (§4.6, §4.8).

8. **External egress gets one small general policy.** `CommandPolicy` governs
   subprocesses and does not reach in-process network calls, so the capabilities layer
   owns an `EgressPolicy` with `CommandPolicy`'s shape and idioms (§6).

9. **`verdict.gate`, `verification/`, `runtime/`, `eval/` and the fixtures are
   untouched.** This layer changes what an agent *knows*, never what a verdict *means*.

---

## 1. What the three capabilities are

| | Agent Skills | Testing capability | Context7 |
|---|---|---|---|
| **Is** | instructions / procedure | deterministic detection + a skill | external read-only lookup |
| **Produces** | text into context | a `TestEnvironment` value | text into context |
| **Authority** | none | none | none |
| **Model-facing** | `load_skill` + catalogue | `detect_tests` + the `testing` skill | `lookup_docs` |
| **Governed by** | snapshot immutability | `CommandPolicy` | `EgressPolicy` |
| **Optional** | yes (no roots ⇒ no catalogue) | yes | yes (unconfigured ⇒ tool absent) |

```
Skills   = instructions and domain procedure       (what to do)
Tools    = actions the harness will perform        (what can be done)
MCP      = a transport for one external capability (how a lookup reaches out)
Policy   = Workspace + CommandPolicy + EgressPolicy + the tool set   (what is permitted)
```

**A skill never grants permission.** The load-bearing invariant, enforced in §4.8.

---

## 2. Architecture

```
  ┌────────────────────────────────────────────────────────────────────────────┐
  │  STARTUP — before any model call, before any mutating tool object exists    │
  │                                                                            │
  │   trusted roots ──► SkillRegistry.snapshot() ──► tuple[SkillPackage, ...]  │
  │   (builtin + operator)                           IMMUTABLE, IN MEMORY      │
  │                                                  body + refs + digests     │
  │   capabilities.toml ──► EgressPolicy (frozen)                              │
  └───────────────┬────────────────────────────────────────────────────────────┘
                  │  after this line the registry never touches a filesystem again
                  v
  ┌────────────────────────────────────────────────────────────────────────────┐
  │  engine/capabilities/            (LEAF — imports no agent package)          │
  │                                                                            │
  │   skills/     SkillRoot · SkillManifest · SkillPackage · Registry · Loader  │
  │   testenv/    detect(root, permits=...) -> TestEnvironment                  │
  │   external/   EgressPolicy · EgressLedger · DocsPort ◄─ Context7Adapter     │
  │                                                          ◄─ McpTransport    │
  └───────────────┬────────────────────────────────────────────────────────────┘
                  │  plain values: str, int, frozen dataclasses.
                  │  No Tool, no ToolContext, no Workspace, no CommandPolicy.
                  v
  ┌────────────────────────────────────────────────────────────────────────────┐
  │  engine/codeagent/  — the ONLY layer that knows about Tool/ToolContext      │
  │   capabilities.py · tools/skills.py · tools/docs.py · tools/testenv.py      │
  └───────────────┬────────────────────────────────────────────────────────────┘
                  │  tools=  /  system_prompt=      (existing seams, unchanged)
                  v
     Coding Agent    ·    Debug Agent    ·    Refactoring Agent (future)
                  │
                  v
        AgentGate verification  (UNCHANGED — verdict.gate still the only OK)
```

The vertical order *is* the security argument. The snapshot happens at the top, mutating
tools are created at the bottom, and `build_capability_tools` requires an
already-snapshotted registry as an argument — so a tool cannot exist before the content
it might have corrupted was already read.

---

## 3. Package and file layout

```
skills/                                  # authored, git-tracked, first-party library
  testing/
    SKILL.md
    references/
      pytest-selection.md

src/engine/capabilities/
  __init__.py
  errors.py                  CapabilityError, SkillError, EgressDenied
  skills/
    roots.py                 SkillRoot      — read-only rooted path guard, trust tier
    manifest.py              SkillManifest  — spec-conformant front-matter reader
    package.py               SkillPackage   — the immutable snapshot (§4.2)
    registry.py              SkillRegistry  — snapshot at construction, advertise, get
    loader.py                SkillLoader    — bounded disclosure FROM THE SNAPSHOT ONLY
  testenv/
    models.py                TestEnvironment, TestConfidence
    detect.py                detect(root, *, permits, max_*) -> TestEnvironment
  external/
    policy.py                EgressPolicy, ExternalCapability, EgressLedger
    port.py                  DocsPort (Protocol), DocsAnswer
    context7.py              Context7Adapter — implements DocsPort (§6.3)
    transport.py             McpTransport    — the ONLY MCP SDK import site
    config.py                parse capabilities.toml -> EgressPolicy

src/engine/codeagent/
  capabilities.py            build_capability_tools(...) + CapabilityBundle
  tools/skills.py            LoadSkillTool
  tools/testenv.py           DetectTestsTool
  tools/docs.py              LookupDocsTool

tests/
  capabilities_harness.py    FakeDocsPort, skill-tree builders
  test_capabilities_skills.py
  test_capabilities_selfhost.py
  test_capabilities_testenv.py
  test_capabilities_external.py
  test_codeagent_capabilities.py
```

**Modified existing files (the honest cost):**

| File | Change |
|---|---|
| `codeagent/limits.py` | new bound fields (§8) |
| `codeagent/state.py` | `CapabilityEvent` + `TaskState` fields (§9) |
| `codeagent/tools/base.py` | `ToolContext.capability_log` (defaulted) — mirrors `command_log` |
| `codeagent/session.py` | drain `capability_log` beside `command_log` (~4 lines, no branch) |
| `codeagent/protocol.py` | optional `skills_catalogue` arg on `build_system_prompt` |
| `codeagent/report.py`, `debugagent/report.py` | a `context_sources` block (§9) |
| `pyproject.toml` | add `pyyaml>=6.0` to `dependencies` (§4.6) |
| `cli.py` | `--skills-dir`, `--capabilities-config`, `--no-capabilities` |
| `tests/test_architecture.py` | Rules H and I (§7) |

---

## 4. Agent Skills

### 4.1 The self-modification threat

AgentGate must be able to debug and refactor **its own repository**. In that run the
workspace root and the skill root overlap:

```
workspace root  = /…/project engine          (the agent may write here)
skill root      = /…/project engine/skills   (physically inside the workspace)
```

`skills` is not in `DENIED_DIR_NAMES`, so `Workspace.resolve("skills/testing/SKILL.md")`
succeeds and `write_file` will write there — **verified against the current tree, not
assumed**. Without a mitigation the escalation is:

```
turn k    write_file  skills/testing/SKILL.md   ← model authors new instructions
turn k+1  load_skill  testing                   ← its own text returns as trusted procedure
```

Model output laundered into a trusted channel.

An earlier draft proposed refusing any skill root inside the workspace. **That approach is
rejected and is not the design**: it made self-hosting impossible, and it rested on path
separation, which describes a layout rather than a trust property.

> **TRUSTED SOURCE ≠ "outside the workspace by assumption".**
> A source is trusted because of *when* it was read and the fact that it *cannot change
> afterwards for this run* — never because of where it happens to live.

### 4.2 Resolution: the immutable `SkillPackage` snapshot

`SkillRegistry` reads **everything it will ever serve** at construction, before any
mutating tool object exists, and keeps it frozen in memory. Workspace overlap is then
**permitted and recorded**, never fatal.

```python
@dataclass(frozen=True)
class ReferenceContent:
    name: str                 # one validated path component, e.g. "pytest-selection.md"
    text: str                 # already bounded
    truncated: bool
    chars: int
    digest: str               # sha256 of source bytes AS READ AT SNAPSHOT

@dataclass(frozen=True)
class SkillPackage:
    """A skill, frozen at snapshot time. Serving one touches no filesystem."""
    manifest: SkillManifest
    body: str                                    # SKILL.md below front matter, bounded
    body_truncated: bool
    body_digest: str
    references: Mapping[str, ReferenceContent]   # MappingProxyType, enumerated at snapshot
    assets: tuple[str, ...]                      # NAMES ONLY — never read (§4.9)
    scripts: tuple[str, ...]                     # NAMES ONLY — never read, never run (§4.9)
    source_root: Path                            # provenance for the report; never re-read
    trust_tier: str                              # "builtin" | "operator"
    overlaps_workspace: bool                     # recorded, never fatal
```

Properties, each a test in §14:

- **The registry retains no path it will ever read from again.** `SkillLoader`'s input is
  a `SkillPackage`; it has no filesystem access at all.
- **References get identical protection to `SKILL.md`,** being snapshotted in the same
  pass rather than lazily on first request.
- **No reload API exists.** `SkillRegistry` exposes `advertise()` and `get(name)`. There
  is no `refresh()`, `reload()` or `rescan()`, so a skill cannot reload itself.
- **Memory is bounded and trivial:** ≤ `max_advertised_skills` × (`max_skill_body_chars`
  + `max_skill_references` × `max_skill_reference_chars`) ≈ 8 × (20 000 + 5 × 4 000)
  ≈ 320 KB. Eager reading is affordable precisely because memory is not context.

> **Progressive disclosure is about prompt/token inclusion, not delayed trust
> establishment.** Trust is established once, at snapshot. `load_skill` only decides
> *when bytes already trusted enter the prompt*.

### 4.3 Mutation observability without a filesystem read

**`load_skill` MUST NEVER READ THE FILESYSTEM.** No re-open, no re-stat, no re-digest —
not for correctness, and not for observability. A read at load time would reintroduce
exactly the lazily-trusted channel §4.2 exists to close, and "we only read it to compare"
is one refactor away from "we read it and used it".

Mutation is therefore observed from data the harness *already has*:

**When a skill root overlaps the workspace** — the self-hosting case, and the only case
where the agent could have caused a mutation at all — the observation is derived from the
existing mutation ledger:

```
for rel in workspace.changed_files:              # already recorded by Workspace.note_changed
    for root in skill_roots where root.overlaps_workspace:
        if rel is under root.relative_prefix:
            record skill_source_mutated(root=…, path=rel)
```

Pure string prefix comparison over two in-memory lists. Zero filesystem access, zero new
bookkeeping — `Workspace` already records every write, and that ledger is the report's
existing source of truth for what changed.

**When a root does not overlap the workspace,** the agent has no write path to it through
any tool, so it cannot be the cause of a change. General external-root mutation detection
(another process editing an operator root mid-run) is **deferred** (§13.11). What is
recorded instead is provenance: `body_digest` and each reference's `digest`, captured at
snapshot, so a report can always state exactly which bytes were served.

The run continues in every case. Failing closed was considered and rejected for a concrete
reason: when the task *is* "improve the testing skill", editing `skills/testing/SKILL.md`
is the correct output of a correct run. Aborting on it would make legitimate refactoring
unrunnable and hand any confused agent a way to kill its own session. The edit is verified
by AgentGate like any other change; what it must never do is take effect as instructions
mid-run, and the snapshot guarantees that.

### 4.4 Trust tiers for skill roots

| Tier | Source | Admitted because | Model influence |
|---|---|---|---|
| `builtin` | the engine's own `skills/`, resolved relative to the installed package or repo root | provenance | none |
| `operator` | `--skills-dir PATH` or `capabilities.toml` | a human named it in this invocation | none |
| — | anything derived from model output | **never admitted** | n/a |

Admission is a human decision made before the run, and **admission is not durable** —
every admitted root of either tier gets identical snapshot treatment, because
"operator-declared" says who chose it, not whether it can change during the run.

Roots are ordered `builtin` first, then operator roots in declaration order. On a duplicate
skill `name`, **the first root wins and the shadowed one is recorded** as
`skill_shadowed`, so an operator root cannot silently displace a first-party skill.

### 4.5 Standard conformance — fields, and where AgentGate extends

The Agent Skills specification defines these frontmatter fields. AgentGate's handling:

#### A. Agent Skills standard fields

| Field | Standard status | Standard constraint | AgentGate handling |
|---|---|---|---|
| `name` | **required** | 1–64 chars; lowercase `a-z0-9` and `-`; no leading/trailing hyphen; **no consecutive hyphens**; must match parent directory name | validated exactly as specified; mismatch ⇒ skill excluded |
| `description` | **required** | 1–1024 chars, non-empty; should say what it does *and when to use it* | validated; used as the catalogue's when-to-use text unless the extension below refines it |
| `license` | optional | license name or bundled file reference | parsed, recorded, reported. Not rendered into any prompt |
| `compatibility` | optional | ≤ 500 chars; environment requirements | parsed, recorded, reported. **Never acted on** — it cannot install anything or widen policy |
| `metadata` | optional | map of string keys → string values | parsed; the sanctioned home for AgentGate's extensions (B) |
| `allowed-tools` | optional, **experimental** | space-separated string of pre-approved tools | **parsed and recorded as advisory metadata only. Never honoured as a grant.** See below |

Unknown top-level keys are **ignored, not rejected** — the forward-compatibility hinge
that lets a third-party skill parse without a core rewrite.

**On `allowed-tools`.** The standard describes it as "tools that are pre-approved to run",
and marks it experimental. AgentGate deliberately **does not implement that meaning**. In
this system a skill is a file; in the self-hosting case it is a *model-writable* file. A
field that turns a file into the grantor of capability is the exact escalation §4.1
describes. AgentGate records the declaration for reporting and ignores it for every
decision. This is a documented, intentional divergence from an experimental field, not an
oversight — and it is compatible in the sense that a skill declaring `allowed-tools` still
loads and works; it simply gets no extra authority.

#### B. AgentGate-specific optional extensions

All live under the standard `metadata` map, namespaced — the same convention Hermes uses
with `metadata.hermes.*`:

```yaml
metadata:
  agentgate.when_to_use: "Before running or choosing tests, or when validating a change."
```

| Extension key | Required? | Purpose | Fallback when absent |
|---|---|---|---|
| `agentgate.when_to_use` | **no** | a short catalogue line separate from the full `description` | the catalogue renders `description`, truncated to `max_skill_metadata_chars` |

**No extension is required for generic Agent Skills compatibility.** A skill with only
`name` and `description` is fully usable by AgentGate: discovered, advertised, loadable,
with references. The extension exists solely because `description` may run to 1024
characters while the catalogue budget is ~240 per skill, and a hand-written short line
reads better than a truncation. `version` is read from `metadata.version` if present, per
the specification's own example, and is not a top-level field.

### 4.6 On-disk shape and parsing

```
skills/testing/
  SKILL.md              required
  references/*.md       optional — enumerated and snapshotted, bounded
  assets/*              optional — names recorded, contents NEVER read (§4.9)
  scripts/*             optional — names recorded, contents NEVER read, NEVER run (§4.9)
```

```markdown
---
name: testing
description: Disciplined test selection and regression practice. Use before running or
  choosing tests, or when a change needs validating.
license: Apache-2.0
metadata:
  agentgate.when_to_use: Before running or choosing tests, or when validating a change.
  version: "1.0"
---

# Testing
...body...
```

Front matter is the block between the leading `---` delimiters, parsed with
**`yaml.safe_load`** (PyYAML — a new declared dependency, §3). `safe_load` is the
documented-safe entry point: it constructs only strings, numbers, booleans, `None`, lists
and dicts, and refuses `!!python/*` tags and every other custom constructor. `yaml.load`,
`unsafe_load` and `full_load` are never used, and no custom `Loader` or constructor is
registered.

Three guards sit around the parse, because "safe against object construction" is not the
same as "safe":

1. **Size cap.** Only the frontmatter block is parsed, and only up to
   `max_frontmatter_bytes` (8 000). A file with no closing delimiter within that window is
   rejected rather than scanned to EOF.
2. **No anchors or aliases.** The block is pre-scanned and rejected if it contains `&`
   anchors or `*` aliases. `safe_load` still expands aliases, so a ~1 KB document can
   expand to gigabytes ("billion laughs") — a denial-of-service, not a code-execution,
   hole. The Agent Skills field set is flat scalars plus one string→string map, so anchors
   have **no legitimate use** and refusing them costs nothing.
3. **Shape validation after parsing.** The result must be a mapping. `name`,
   `description`, `license`, `compatibility` and `allowed-tools` must be scalars;
   `metadata` must be a mapping whose values are scalars, stringified on read (so an
   unquoted `version: 1.0` becomes `"1.0"` rather than a float). A non-scalar where a
   scalar is required is a validation error, not a coercion.

**Parsing never grants authority.** The parse produces a `dict`; §4.8 governs what any of
it may cause. A field that parses successfully still changes no tool dict and no policy.

A malformed manifest makes that skill **absent from the registry**, recorded in
`skill_discovery_errors` — never a half-loaded skill.

`SkillRoot` is a deliberate ~15-line reimplementation of `Workspace.resolve`'s technique,
not an import of it: `capabilities/` is a leaf (Rule H); a skill root is read-only and must
not carry a mutation ledger; and `workspace.py` already documents choosing duplication over
coupling for exactly this trade.

### 4.7 Progressive disclosure — levels and how ours map

The specification defines three levels. AgentGate's mapping and bounds:

| Spec level | Spec guidance | AgentGate |
|---|---|---|
| 1. Metadata | `name` + `description` at startup, ~100 tokens | static "Available skills" section in the system prompt; `max_skill_metadata_chars` 240/skill, `max_skills_catalogue_chars` 2 000 total |
| 2. Instructions | full `SKILL.md` on activation, **< 5 000 tokens recommended**, < 500 lines | `load_skill` tool call; `max_skill_body_chars` = 20 000 (≈ the spec's 5 000-token ceiling) |
| 3. Resources | `references/`, `scripts/`, `assets/` on demand | `load_skill` with a `reference` key; `max_skill_reference_chars` 4 000, `max_loaded_references` 3. `scripts/`/`assets/` are never loaded (§4.9) |

`max_skill_body_chars` is set at 20 000 specifically so a **spec-conformant** skill written
to the standard's own recommendation is not truncated. First-party skills should stay far
below it — `skills/testing/SKILL.md` is expected around 3 000 chars — and the ceiling exists
for imported skills. A body over the bound is truncated and flagged (`body_truncated`), and
that flag is reported so an operator can see interop loss rather than infer it.

Lifecycle:

```
 startup — no model call, no mutating tool object in existence
   roots     = resolve_roots(builtin, operator_flags)
   registry  = SkillRegistry.snapshot(roots, limits)      ← ALL bytes read here, once
   catalogue = registry.advertise(limits)                 ← metadata only
        │
        v
 session start
   build_capability_tools(registry=…)      ← requires the snapshotted registry
   build_system_prompt(tools, skills_catalogue=catalogue)
   ── model sees name + catalogue line only
        │
        v
 turn N    load_skill {"skill": "testing"}
   ── served from SkillPackage.body. NO filesystem read. Costs one tool call.
        │
        v
 turn N+k  load_skill {"skill": "testing", "reference": "pytest-selection.md"}
   ── key lookup in that package's references mapping. NO filesystem read.
```

### 4.8 The permission invariant

> **A skill NEVER grants execution permission.**

`allowed-tools` and `compatibility` are recorded and reported, and read by **nothing** that
decides anything. Enforcement is structural, not checked:

- The `dict[str, Tool]` handed to `CodingSession` is built **before** the session and never
  mutated. `SkillLoader` returns a string and holds no reference to the tool dict,
  `Workspace`, `CommandPolicy`, or `EgressPolicy`.
- A body claiming "you may run `curl`" yields what any other text claiming it yields:
  `CommandPolicy.check` raises `CommandDenied`.
- `allowed-tools: lookup_docs` does not enable Context7. Only `EgressPolicy` does, and it
  is built from operator config.
- Rule H means a future edit *cannot* quietly give the loader a policy object to soften.

### 4.9 References, assets, scripts

**References** are addressable **only** by an identifier already enumerated in that
package's `references` mapping — the model's string is a **key lookup, not a path**:

- a key not in the mapping ⇒ tool error listing that package's available reference names;
- `..`, absolute paths, drive-qualified paths and nested paths are rejected at snapshot by
  `SkillRoot`, so such a name can never become a key. There is no second check at load
  time because there is no path at load time;
- symlinked references escaping the root are rejected at snapshot (resolve-then-contain);
- credential-shaped filenames are screened by the same rules `Workspace` uses;
- a reference of skill A is unreachable through skill B — the mapping is per-package;
- bounded by `max_skill_reference_chars` and `max_loaded_references`.

Per the specification, references are kept one level deep from `SKILL.md`; nested reference
chains are not followed.

**Assets** (`assets/`, spec-defined: templates, images, data files) are enumerated by name
for reporting and **never read** in the MVP. They are typically binary or template content
with no meaning as prompt text, and reading them would spend the context budget the whole
layer exists to protect. Deferred (§13.12).

**Scripts** (`scripts/`, spec-defined as "executable code that agents can run") are
enumerated by name and **never read and never executed**. The specification permits
execution; **AgentGate's runtime security policy is authoritative and forbids it.** A skill
declaring a script does not make it a command: the tool dict is fixed and contains no
script runner, and `CommandPolicy` would refuse the interpreter invocation regardless.
Deferred (§13.2).

---

## 5. Testing / Test Detection capability

### 5.1 Detection is code; discipline is a skill

- **`capabilities/testenv/detect.py`** — deterministic, model-free, file-signal based.
  Same tree ⇒ byte-identical result.
- **`skills/testing/SKILL.md`** — the procedure. Instructions only.

### 5.2 `TestEnvironment`

```python
class TestConfidence(Enum):
    CERTAIN = "CERTAIN"    # explicit config names the framework
    LIKELY  = "LIKELY"     # dependency or conventional layout implies it
    UNKNOWN = "UNKNOWN"    # nothing decisive found

@dataclass(frozen=True)
class TestEnvironment:
    framework: str | None
    suite_argv: tuple[str, ...]          # () when unknown — never a guess
    targeted_template: tuple[str, ...]   # argv with a "{target}" slot
    evidence: tuple[str, ...]            # "pyproject.toml [tool.pytest.ini_options]"
    confidence: TestConfidence
    executable: bool                     # would CommandPolicy permit suite_argv?
    blocked_reason: str | None           # the refusal, verbatim, when not executable
```

`confidence` is **computed by the harness from file evidence, never accepted from a
model** — the rule `rootcause.py` already applies to its own `confidence`.

`executable` is not a hardcoded language list. `detect()` takes a required
`permits: Callable[[tuple[str, ...]], str | None]` returning `None` (allowed) or a refusal
reason; the `codeagent` adapter supplies one backed by `CommandPolicy.check`. So
`capabilities/` stays a leaf, and the field reports the *live* policy rather than a belief
about it — widen the policy later and `executable` flips with no change here.

### 5.3 MVP scope — Python executable, JS/TS informational

| Ecosystem | Signal | Confidence | Executable |
|---|---|---|---|
| Python | `pyproject.toml` `[tool.pytest.ini_options]` | CERTAIN | yes |
| Python | `pytest.ini`, `tox.ini` `[pytest]`, `setup.cfg` `[tool:pytest]` | CERTAIN | yes |
| Python | `pytest` dependency, or `tests/` with `test_*.py` | LIKELY | yes |
| JS/TS | `package.json` `scripts.test` naming jest/vitest/playwright | CERTAIN | **no** |
| JS/TS | `jest.config.*`, `vitest.config.*` | CERTAIN | **no** |
| JS/TS | devDependency on jest/vitest only | LIKELY | **no** |

Anything else ⇒ `UNKNOWN`, `suite_argv = ()`, `executable = False`. **The MVP does not
guess.**

JS/TS detection is **informational metadata only**:

```
framework      = "vitest"
suite_argv     = ("npm", "test")     ← reported, never offered as runnable
executable     = False
blocked_reason = "program 'npm' is not allowed; allowed: ['git','mypy','pytest',
                  'python','python3','ruff']"
```

**`CommandPolicy` is not expanded to `node`/`npm` in this phase.** The `DetectTestsTool`
observation renders `executable: false` and the reason prominently, so a model is never
handed a command it will then be refused for trying.

### 5.4 The Debug Agent rule — frozen commands stay frozen

```
--repro supplied  ->  AUTHORITATIVE. Detection not consulted. Frozen. Full stop.
--suite supplied  ->  AUTHORITATIVE. Detection not consulted. Frozen. Full stop.
--suite omitted   ->  detection MAY PROPOSE, before any edit exists, and only if
                      executable is True:
                         proposal -> freeze_suite(argv, policy)   [existing call]
                      -> frozen for the run. Never revisited, never re-detected.
```

Enforcement points all already exist: `app.py` freezes both commands before the
reproduction and before any model call; `FrozenRepro` has no setter; `freeze_suite`
policy-checks at freeze time; the fix session's only re-run path is `RunReproTool`, which
takes **no arguments**. A non-executable detection can never be proposed, so the JS/TS path
cannot reach `freeze_suite` at all.

Current CLI behaviour (`--suite` defaults to `DEFAULT_SUITE_ARGV`) means the "omitted"
branch is **not reachable in the MVP CLI**; it is designed now so the future UX change is a
flag, not a redesign.

For Coding and Refactoring agents, `detect_tests` is an ordinary observation tool. AgentGate
continues to run `ruff`/`mypy`/`pytest` through `run_automated_gates` exactly as today.

---

## 6. External capability egress

### 6.1 `EgressPolicy` — one small general boundary

`CommandPolicy` governs subprocesses and does **not** reach an in-process network call.
Rather than give Context7 bespoke limits, the capabilities layer owns a policy with the
same shape and idioms — `check()` raises on violation and returns the permitted thing.

```python
@dataclass(frozen=True)
class ExternalCapability:
    name: str                       # "context7"
    operations: frozenset[str]      # {"lookup_docs"}
    timeout_seconds: float
    max_calls: int
    max_chars_per_call: int
    max_chars_total: int

@dataclass(frozen=True)
class EgressPolicy:
    capabilities: Mapping[str, ExternalCapability]   # allowlist; empty ⇒ no egress
    def check(self, *, capability: str, operation: str) -> ExternalCapability:
        """Raises EgressDenied for an unknown capability or operation."""
```

Policy/ledger split mirrors `Limits` (rules) and `Usage` (consumption).

**Deliberately not a universal framework.** The MVP admits exactly one capability with
exactly one operation. It exists so the *second* external capability is a config entry
rather than a second security system.

Invariants: skills cannot change it (they produce text; Rule H blocks the import; the
policy is frozen). Models cannot add servers (no `server`/`url`/`endpoint`/`capability`
argument exists; supplying one is refused as malformed). Agents cannot bypass it (the
adapter is unreachable except through the tool). Empty policy ⇒ tool unregistered.

### 6.2 `EgressLedger` — ordering

A response's size is unknown until the adapter returns, so the ledger reserves first and
records actual accepted characters last.

```python
class EgressLedger:                      # mutable, per session
    calls: int
    chars: int
    def begin_call(self, cap: ExternalCapability) -> int:
        """Reserve a call slot; return the char allowance for THIS call.
        Raises EgressDenied if calls >= cap.max_calls or the total budget is spent."""
    def record_chars(self, n: int) -> None:   # actual accepted chars, post-truncation
    def fail_call(self) -> None:              # slot stays spent, zero chars recorded
```

The full lifecycle of one `lookup_docs` call:

```
1. cap       = policy.check(capability="context7", operation="lookup_docs")   → EgressDenied?
2. allowance = ledger.begin_call(cap)
              = min(cap.max_chars_per_call, cap.max_chars_total - ledger.chars)
              ── raises EgressDenied if the call cap is hit or allowance <= 0
3. answer    = adapter.lookup(library=…, topic=…,
                              timeout_s=cap.timeout_seconds, max_chars=allowance)
              ── the timeout covers the WHOLE wrapper call, both MCP hops (§6.3)
4. validate  the response shape: DocsAnswer fields present, content is a str
5. truncate  content to `allowance` → (text, truncated)
6. ledger.record_chars(len(text))          ← ACTUAL ACCEPTED chars, after truncation
7. return    the bounded DocsAnswer → rendered as the observation
```

On an exception or invalid response at 3 or 4: `ledger.fail_call()`. The call slot stays
spent — a timeout consumed real budget and latency — and zero characters are recorded. That
is the honest accounting.

**The tool can never put over-budget external text into model context**, because
`allowance` is computed from the remaining total *before* the call, and truncation happens
at step 5 *before* the observation is built. `max_chars` is passed to the adapter as a hint
so a well-behaved provider can return less; step 5 does not trust it.

### 6.3 The port, the real Context7 interface, and the mapping

```python
@dataclass(frozen=True)
class DocsAnswer:
    library: str; resolved_id: str; topic: str
    content: str; truncated: bool; source: str

class DocsPort(Protocol):
    def lookup(self, *, library: str, topic: str,
               timeout_s: float, max_chars: int) -> DocsAnswer: ...
```

`DocsPort` is the whole vocabulary an agent-side module may know — no MCP, no JSON-RPC, no
servers, no transports.

**The real Context7 MCP interface**, as published in the upstash/context7 README
("Available Tools", quoted verbatim) and corroborated independently:

| Tool | Parameters | Notes |
|---|---|---|
| `resolve-library-id` | `query` (required) — the user's question/task, used to rank results; `libraryName` (required) — the library name to search for | returns candidates as Context7 IDs in `/org/project` form, with descriptions and scores |
| `query-docs` | `libraryId` (required) — exact Context7-compatible ID, e.g. `/mongodb/docs`; `query` (required) — the question or task | the docs fetch |

Documented workflow: `resolve-library-id` **must** be called first *unless* the caller
already has an ID in `/org/project` or `/org/project/version` form. Note that the current
interface exposes **no `topic` and no `tokens`/size parameter** — an older interface did —
so **output bounding is entirely client-side**, which is precisely why §6.2 truncates and
records post-truncation.

**Mapping — one model-facing tool onto two MCP tools:**

```
 model:  lookup_docs {"library": "pydantic", "topic": "model_validator"}
                │
                v  Context7Adapter.lookup(library, topic, timeout_s, max_chars)
                │
   library matches ^/[^/]+/[^/]+(/[^/]+)?$
        yes ──────────────► library_id = library            (skip the resolve hop)
        no  ──────────────► resolve-library-id(
                                libraryName = library,
                                query       = topic)
                            → take the top-ranked candidate → library_id
                │
                v
              query-docs(libraryId = library_id, query = topic)
                │
                v
   DocsAnswer(library=…, resolved_id=library_id, topic=…,
              content=<truncated to max_chars by the caller at step 5>,
              source="context7")
```

Both hops are **one** `lookup_docs` call and therefore **one** ledger call slot; the
`ExternalCapability.timeout_seconds` bounds the pair, not each hop. `resolved_id` is echoed
in the observation so the model can disambiguate on a retry by passing a `/org/project`
string as `library` — the one place a model influences resolution, and it influences only
*which library*, never *which server*.

Resolve-then-fetch stays **inside** the adapter: every extra model-facing step is another
place a model can loop, and the two-step protocol is a provider detail that `DocsPort`
exists to hide. If a future provider is single-step, the adapter changes and nothing above
it does. **The transport is not implemented in this phase** (§15, C6/C7).

### 6.4 Configuration

```toml
# capabilities.toml — operator-owned, outside the workspace, never model-writable
[external.context7]
enabled            = true
server             = "context7"   # key into the operator's MCP server table — not a URL
timeout_seconds    = 10.0
max_calls          = 5
max_chars_per_call = 6000
max_chars_total    = 20000
```

Absent / `enabled = false` / parse error ⇒ empty `EgressPolicy` ⇒ adapter `None` ⇒ tool
unregistered ⇒ the model never learns it might have existed. All three agents run unchanged.

### 6.5 Failure behaviour

Every failure is an ordinary `ToolResult(ok=False)` observation — never an exception into
the loop, never a session abort:

| Failure | Observation |
|---|---|
| unconfigured / unreachable | `documentation lookup is unavailable; continue from repository evidence` |
| timeout | `lookup timed out after Ns` |
| resolve found no library | `no matching library for '<name>'; continue from repository evidence` |
| malformed response | `lookup returned an unusable response` |
| `EgressDenied` (call cap) | `documentation lookup budget exhausted (N calls)` |
| `EgressDenied` (char cap) | `external context budget exhausted` |

Each wording tells the model to fall back to repository evidence.

---

## 7. Trust boundaries

```
 TRUSTED (operator, pre-session)   SEMI-TRUSTED (engine)      UNTRUSTED
 ─────────────────────────────────────────────────────────────────────────────────
 skills/ AS READ AT SNAPSHOT       SkillPackage body/refs     workspace contents
 capabilities.toml                 TestEnvironment            model output
 --skills-dir                      DocsAnswer after bounds    Context7 response body
 CommandPolicy, EgressPolicy                                  allowed-tools / compatibility
 tool dict composition                                        skills/ AFTER snapshot
```

The last row appears on both sides: **the same directory is trusted and untrusted,
separated only by time.** That is the point of §4.

1. **Untrusted text never becomes authority.** A Context7 response and a skill's
   `allowed-tools` line are both text in a prompt. Neither is consulted by `Workspace`,
   `CommandPolicy`, `EgressPolicy`, `verdict.gate`, or the tool dict.
2. **Operator input is trusted; model input never is.** A skill name is a key lookup
   against the advertised set; a reference name is a key lookup within one package.
3. **Workspace overlap is permitted, recorded, and neutralised by snapshot ordering.**
4. **Secrets stay out.** Skill and reference reads use the same credential-shape screen as
   `Workspace`. Context7 receives a library name and a topic — never a file, never a diff,
   never an environment variable. Transport credentials come from operator config and are
   never rendered into a prompt or a report. A skill cannot request credentials (§8, the
   Hermes divergence).

### New architecture rules (added to `tests/test_architecture.py`)

- **Rule H** — `engine/capabilities/**` must not import `engine.codeagent` or
  `engine.debugagent`. Keeps the layer a leaf, keeps Agent #3 off another agent's import
  path, and is what makes §4.8 and §6.1 structurally true rather than promised.
- **Rule I** — only `engine/capabilities/external/transport.py` may import an MCP client
  SDK. Rule B's shape for provider SDKs, for the same reason: one egress chokepoint a grep
  can prove.

Existing Rules A–G are unaffected; `capabilities/` is not in `VERIFIED_BY_PACKAGES`.

---

## 8. Comparison with Hermes skills

Hermes (Nous Research) is an independent implementation of the same idea, useful as a
cross-check rather than a source of code. **Nothing is copied and it is not a dependency.**

**What Hermes does:** `skills_list()` returns a compact list of all skills (~3k tokens) at
session start; `skill_view(name)` fetches one full `SKILL.md` on demand;
`skill_view(name, file_path)` loads a reference file. Frontmatter uses `name`,
`description`, `version`, and vendor extensions namespaced under `metadata.hermes.*`
(tags, category, and a `config` block). "When to Use" is a **body section**, not a
frontmatter field. ~100+ bundled skills across 14 categories, catalogued as
name/description/path.

**Borrowed conceptually:**

1. **Three-level disclosure** — list → full body → reference file. Ours is
   catalogue → `load_skill` → `load_skill(reference=…)`. Independent convergence on the
   spec's own model is good evidence the shape is right.
2. **Vendor namespacing under `metadata`** rather than inventing top-level keys. Hermes
   uses `metadata.hermes.*`; we use `metadata.agentgate.*` (§4.5.B). This is what moved
   `when_to_use` out of the top level in rev 3.
3. **Loading is an explicit action, not ambient context** — their `skill_view`, our
   `load_skill`.

**Deliberately different:**

1. **The catalogue is a static system-prompt section, not a tool call.** Hermes spends a
   `skills_list()` call; our system prompt is already generated from the live tool
   registry, so the catalogue sits beside the tool catalogue, costs no tool call, and
   cannot drift from the registry. It also keeps the advertised set *deterministic* — the
   harness decides what is advertised, the model only decides what to load.
2. **No skill-declared configuration or credential prompts.** Hermes lets a skill declare
   `metadata.hermes.config` and prompts the user for values such as an API key. AgentGate
   does not: a skill that can request credentials is a credential-elicitation channel, and
   in the self-hosting case that skill file is model-writable. All external configuration
   lives in `capabilities.toml`, operator-side, and never in a skill.
3. **Snapshot immutability.** Hermes targets a personal-agent trust model — the user's own
   machine, the user's own skills. AgentGate targets an *adversarial workspace*: the
   repository under repair may be hostile, and may literally contain the skill directory.
   That difference is the entire reason for §4.2.
4. **Bounded, reported context spend.** ~3k tokens of unconditional catalogue is
   reasonable for a personal assistant with 100+ skills; for a benchmarked engine where
   context is a measured variable, ours is capped at ~2 000 chars and every load is
   recorded in the report.

**Why instructions never grant tools or execution authority.** Neither Hermes nor the
specification's core makes skills grant capability — the spec's `allowed-tools` is the only
field that gestures at it, and it is marked experimental. AgentGate takes the stricter
position for a reason specific to this system: here a skill is *a file inside the artifact
under test*. Honouring `allowed-tools` would mean a model that can write a file can widen
its own permissions, which is escalation by design rather than by bug. Skills are
instructions; tools are actions; policy is authority; and those three must not be the same
object.

---

## 9. Context and token discipline

New `Limits` fields — ceilings, not targets:

```python
# Skills
max_advertised_skills:        int = 8
max_skill_metadata_chars:     int = 240      # per skill, in the catalogue
max_skills_catalogue_chars:   int = 2_000    # whole catalogue, hard cap
max_loaded_skills:            int = 2        # RESOLVED — §18.D
max_loaded_references:        int = 3        # total reference loads per session
max_skill_body_chars:         int = 20_000   # ≈ the spec's 5 000-token recommendation
max_skill_reference_chars:    int = 4_000
max_skill_references:         int = 5        # enumerated/snapshotted per skill
max_skill_source_bytes:       int = 256_000  # read ceiling at snapshot, per file
max_frontmatter_bytes:        int = 8_000    # parsed window; beyond it, rejected

# Test detection
max_testenv_files_read:       int = 8
max_testenv_file_bytes:       int = 32_000
```

External bounds (`max_calls`, `max_chars_per_call`, `max_chars_total`, `timeout_seconds`)
live on `ExternalCapability`, **not** on `Limits`: they are operator policy per capability,
not session bounds.

Worst case added to a session's context:

```
catalogue          2,000
skill bodies       2 x 20,000 = 40,000     (only if both loaded skills are spec-max)
references         3 x  4,000 = 12,000
external          20,000                   (EgressPolicy hard ceiling, any call count)
                  ──────────────────────
                  ~74,000 chars ≈ 18k tokens — bounded, and every part reported
```

Realistic case, first-party skills: catalogue 2 000 + one `testing` body ≈ 3 000 + zero or
one reference ≈ **≤ 9 000 chars**. The ceiling is for imported spec-max skills and is
essentially never reached.

Discipline rules:

- The catalogue is the **only** unconditional addition, capped twice. A session that loads
  nothing pays ~2 000 chars.
- Every bound is enforced at truncation *and* reported (`truncated: true`).
- Exceeding a count bound is a **refusal with a reason**, not silent omission.
- No body is re-sent. A second `load_skill` of an already-loaded skill returns a short
  "already loaded this session" observation; it still costs a tool call (§18.C) but does
  not re-spend `max_loaded_skills`.

---

## 10. State and reporting

### `TaskState` additions

```python
advertised_skills:        list[str]
loaded_skills:            list[str]
loaded_skill_references:  list[str]              # "skill/reference"
skill_load_events:        list[dict[str, Any]]   # name, reference|None, chars, truncated
skill_discovery_errors:   list[str]
skill_source_mutations:   list[str]              # derived from the workspace ledger (§4.3)
skill_roots:              list[dict[str, Any]]   # path, trust_tier, overlaps_workspace
external_calls:           int
external_failures:        list[str]              # reasons, never response bodies
external_chars:           int
detected_test_framework:  str | None
detected_test_confidence: str | None
detected_test_executable: bool | None
selected_suite_argv:      list[str]
suite_source:             str | None             # "explicit" | "detected" | "default"
```

### Session log events

`skill_advertised`, `skill_loaded`, `skill_load_refused`, `skill_source_mutated`,
`skill_shadowed`, `testenv_detected`, `external_lookup`, `external_lookup_denied`,
`external_lookup_failed`. All follow `log.py`'s rule: **counts and identifiers, never model
prose, never response bodies.**

### Report shape — a fourth category

Skills and external documentation are not measured facts, not model assertions, and not a
verdict. They are **inputs that shaped the run**:

```json
{
  "observed":        { "...": "unchanged" },
  "claimed":         { "...": "unchanged" },
  "agentgate":       { "...": "unchanged" },
  "context_sources": {
    "repository": { "files_inspected": [], "commands_run": [] },
    "skills": {
      "roots":     [{"path": "skills", "trust_tier": "builtin", "overlaps_workspace": true}],
      "advertised": [], "loaded": [], "references": [],
      "chars": 0, "errors": [], "mutations": [], "digests": {}
    },
    "external": { "provider": "context7", "calls": 0, "chars": 0, "failures": [] },
    "test_detection": { "framework": "pytest", "confidence": "CERTAIN",
                        "executable": true, "evidence": [], "suite_source": "explicit" }
  }
}
```

`external` absent or zeroed is a positive statement that nothing external was consulted.
`skills.mutations` non-empty is a positive statement that the on-disk skill changed during
the run and the snapshot was served anyway. `skills.digests` records exactly which bytes
were served.

---

## 11. Agent integration

```python
# codeagent/capabilities.py
@dataclass(frozen=True)
class CapabilityBundle:
    tools: dict[str, Tool]
    catalogue: str                  # "" when no skills
    registry: SkillRegistry | None
    docs: DocsPort | None
    egress: EgressPolicy

def build_capabilities(*, skill_roots, external_config, limits, workspace_root,
                       policy) -> CapabilityBundle: ...
```

Every agent's integration: build the bundle, merge `bundle.tools`, pass `bundle.catalogue`
to its system-prompt builder. Nothing else.

| | Coding Agent | Debug Agent | Refactoring #3 |
|---|---|---|---|
| Metadata shown | session start, system prompt | fix-session start | session start |
| Full skill loaded | on `load_skill` | on `load_skill` | on `load_skill` |
| Selector | model, from the advertised set | model | model |
| Load costs a tool call | yes | yes | yes |
| Context7 tool | when configured | when configured | when configured |
| `detect_tests` | yes | yes (advisory — commands already frozen) | yes |
| Report | `context_sources` | `context_sources` | `context_sources` |

**Debug Agent.** `build_fix_tools(repro)` gains a bundle parameter and merges;
`build_fix_prompt` gains the catalogue. Diagnosis (D2) is deliberately **left alone** — a
single bounded evidence-first call with no tool loop; a catalogue there would inflate every
diagnosis prompt for a capability the phase cannot use.

**Is a new `CodingSession` seam needed?** No. `tools`, `system_prompt` and `agent_name`
suffice. The only session-file edit is draining `capability_log`, mirroring
`_drain_commands` — no branch, no new terminal status.

---

## 12. Failure modes

| Failure | Behaviour |
|---|---|
| No skill roots / empty | empty catalogue, `load_skill` unregistered, run proceeds |
| Malformed `SKILL.md`, invalid YAML, or a shape violation | skill absent; `skill_discovery_errors`; siblings unaffected |
| Frontmatter over `max_frontmatter_bytes`, or containing anchors/aliases | skill absent; recorded compatibility error; nothing parsed |
| `name` ≠ directory, or violates the spec's charset/hyphen rules | skill absent; recorded |
| Root overlaps workspace | **admitted**, `overlaps_workspace: true` recorded (§4.2) |
| Skill file edited in the workspace after snapshot | snapshot served; `skill_source_mutated` derived from the workspace ledger; run continues |
| Duplicate skill name across roots | first root wins; `skill_shadowed` recorded |
| Unadvertised skill requested | tool error naming the advertised set |
| Unknown reference key | tool error naming that package's reference names |
| `max_loaded_skills` / `max_loaded_references` reached | refusal naming the bound |
| Body/reference over bound at snapshot | truncated, flagged; digest still covers full source |
| `scripts/` or `assets/` present | names recorded; never read; never executed |
| Context7 unconfigured | tool absent from dict and prompt |
| Context7 runtime failure / `EgressDenied` | `ToolResult(ok=False)`, `fail_call()`, session continues |
| Detection finds nothing | `UNKNOWN`, empty argv, `executable=False` |
| Detected argv refused by policy | `executable=False` + `blocked_reason`; never proposed |

---

## 13. Explicitly deferred

1. **Remote skill marketplace / installation.** No download, unpacking, version resolution,
   or third-party trust model. The community catalogues reviewed for rev 3
   (`aitmpl.com/skills`, `mcpmarket.com`) are community-submitted with star counts and
   "official/featured" labels as the only vetting signal — social proof, not verification.
   That is not a trust model this layer can build on. Forward hinge: `SkillRegistry` takes
   a *list* of roots with trust tiers, and the manifest reader ignores unknown keys — an
   imported skill becomes another root, not a rewrite.
2. **Executing skill `scripts/`.** The specification permits it; AgentGate's runtime
   security policy forbids it and is authoritative.
3. **Loading `assets/` content** (§4.9).
4. **Honouring `allowed-tools` as a grant** (§4.5.A) — deferred indefinitely; it would make
   a model-writable file the grantor of capability.
5. **Skill-declared configuration or credential prompts** (the Hermes divergence, §8).
6. **Unrestricted MCP server discovery.** One allowlisted capability from operator config.
7. **Arbitrary web access.** No fetch tool, no URLs, no hosts beyond the one adapter.
8. **Dynamic installation during a run.** `CommandPolicy` denies `pip`/`npm`.
9. **Expanding `CommandPolicy` to `node`/`npm`.**
10. **Ecosystems beyond Python and JS/TS** in detection.
11. **General external-root mutation detection** (a third party editing a non-overlapping
    operator root mid-run). Provenance digests are recorded; detection would require a
    filesystem re-read, which §4.3 forbids.
12. **Skills at the diagnosis phase or inside judge lenses.** Judges review code with fresh
    eyes; giving them procedure text is a verification-semantics change.
13. **A general egress framework.** One capability, one operation, until a second real one
    exists.
14. **YAML features outside the Agent Skills field set** — anchors, aliases, custom tags,
    multi-document streams. Refused with a recorded compatibility error (§4.6). These have
    no legitimate use for a flat scalar field set, and admitting them adds a
    denial-of-service surface for no interoperability gain.

---

## 14. Tests

All offline. No network, no API key, no MCP process, until C8.

### Self-modification / self-hosting (`test_capabilities_selfhost.py`)

- **AgentGate repo as target workspace with `skills/` inside it**: registry constructs,
  `overlaps_workspace` is `True`, the run is not refused
- **agent edits `skills/testing/SKILL.md` after session start ⇒ `load_skill` returns the
  pre-session snapshot**, byte-for-byte
- **same for a reference file**
- deleting the skill directory mid-session ⇒ `load_skill` still succeeds from memory
- **`load_skill` performs zero filesystem access** — asserted by snapshotting, then
  removing the root entirely, then loading successfully
- the mutation is recorded (`skill_source_mutated`) **and is derived from
  `workspace.changed_files`**, not from a re-read
- a workspace edit *outside* any skill root produces no mutation record
- `SkillRegistry` exposes no `reload`/`refresh`/`rescan` member
- `SkillPackage` is frozen; `references` is not a mutable dict
- a tool dict cannot be built from a non-snapshotted registry

### Standard conformance (`test_capabilities_skills.py`)

- a minimal spec-conformant skill (**only `name` + `description`**) is discovered,
  advertised and loadable — **no AgentGate extension required**
- `name` validation matches the spec: 1–64 chars; rejects uppercase, leading/trailing
  hyphen, **consecutive hyphens**, and a name ≠ parent directory
- `description` over 1024 chars ⇒ rejected; catalogue rendering truncates at
  `max_skill_metadata_chars` without rejecting
- `license`, `compatibility`, `metadata` parse and are recorded; `compatibility` is never
  acted on
- `metadata.agentgate.when_to_use` refines the catalogue line; absent ⇒ falls back to
  `description`
- **real YAML forms parse**: a folded (`>-`) and a literal (`|`) multi-line `description`,
  a double-quoted value containing `:`, a `#` comment line, and a nested `metadata:` map
- **`yaml.safe_load` refuses a `!!python/object` tag** — the skill is excluded with a
  recorded error and nothing is constructed
- frontmatter containing an anchor/alias is rejected before parsing, with a recorded
  compatibility error
- frontmatter with no closing `---` inside `max_frontmatter_bytes` is rejected
- shape validation: a list where `name` must be a scalar ⇒ rejected; `metadata` values are
  stringified, so an unquoted `version: 1.0` reads back as `"1.0"`
- `metadata.version` is read; a top-level `version` is not a recognised field
- unknown top-level keys ignored, skill still loads
- **`allowed-tools: run_command` does not add `run_command` to the tool dict**
- **`allowed-tools: lookup_docs` does not enable Context7**
- a body instructing `curl` still yields `CommandDenied`
- `assets/` and `scripts/` names recorded; contents never read; no script tool registered

### Skills behaviour (`test_capabilities_skills.py`)

- catalogue contains metadata only, never body text
- body not in context until `load_skill` is called
- **`load_skill` consumes exactly one ordinary tool call** (`usage.tool_calls` +1)
- **`max_loaded_skills = 2` blocks the third distinct load**, with a reason
- `max_loaded_references` refusal; re-loading a loaded skill does not re-spend the bound
- body over `max_skill_body_chars` ⇒ truncated + flagged
- reference key not enumerated ⇒ error naming available keys
- `..`, absolute, drive-qualified and nested reference names never become keys
- symlinked reference escaping the root rejected at snapshot
- credential-shaped filename inside a skill root refused
- reference of skill A unreachable through skill B
- duplicate names across roots ⇒ first wins, `skill_shadowed` recorded

### External (`test_capabilities_external.py`)

- `FakeDocsPort` returns a canned answer; observation well-formed
- unavailable / timeout / malformed ⇒ `ok=False`, fall-back wording, session continues
- **ledger ordering**: `begin_call` reserves before the adapter runs; `record_chars` records
  post-truncation length; a response larger than the allowance is truncated **before** the
  observation is built
- an over-budget response never appears in context, even when the adapter ignores
  `max_chars`
- a failed call spends a call slot and records zero chars (`fail_call`)
- `max_calls` and `max_chars_total` ⇒ `EgressDenied` with the documented wording
- **a model-supplied `server`/`url`/`capability` argument cannot select a server** — refused,
  no transport constructed
- `EgressPolicy.check` rejects an unknown capability and an unknown operation
- empty policy ⇒ `lookup_docs` absent from tools **and** from the system prompt
- `DocsPort` exposes no mutating operation (asserted over the Protocol's members)
- **adapter mapping** against a fake MCP client: a bare name issues
  `resolve-library-id(libraryName, query)` then `query-docs(libraryId, query)`; a
  `/org/project` string **skips the resolve hop**; `resolved_id` is echoed in the answer
- **agent completes a full offline session with Context7 disabled**

### Testing capability (`test_capabilities_testenv.py`)

- detects pytest from each CERTAIN signal; `evidence` names the file; `executable=True`
- detects jest and vitest; **`executable=False` with a `blocked_reason` naming the policy**
- **a JS/TS detection can never be proposed to `freeze_suite`**
- ambiguous tree ⇒ `UNKNOWN`, empty argv
- every returned argv is a tuple of strings, never a shell string
- detection is byte-identical over two runs on the same tree
- **explicit `--repro` and `--suite` are never replaced by detection**
- a proposed suite is frozen through `freeze_suite` and policy-checked
- `SKILL.md` contains no guidance to delete, skip, or weaken a test (phrase denylist)

### Cross-agent (`test_codeagent_capabilities.py`)

- Coding Agent loads a skill offline; `TaskState` records it
- Debug Agent uses the testing skill with D1/D2/D3 semantics unchanged: repro frozen, suite
  frozen, `PASSED` still requires proof **and** AgentGate
- one `CapabilityBundle` composes into both agents' tool dicts
- architecture Rules G, H, I hold
- a run with no skills and no Context7 is byte-identical to today's behaviour

---

## 15. Phased implementation plan

Each phase is independently testable, ends with `ruff check .` + `mypy` + `pytest -q`
green, and is commit-sized. No phase makes a network call before C8.

| Phase | Deliverable | Gate |
|---|---|---|
| **C0** | this blueprint | review |
| **C1** | `capabilities/skills/` — `SkillRoot`, spec-conformant `SkillManifest`, `SkillPackage`, snapshotting `SkillRegistry`, `SkillLoader`. Rule H. Pure leaf. | skills, standard-conformance **and self-host** suites pass |
| **C2** | `LoadSkillTool` + `build_capability_tools` + catalogue arg + `capability_log` + session drain + `TaskState` fields. Coding Agent only. | loads a skill offline; tool-call accounting asserted |
| **C3** | `capabilities/testenv/` + `DetectTestsTool` with `permits` injection. | detection, determinism, `executable=False` for JS/TS |
| **C4** | `skills/testing/SKILL.md` + references. First first-party skill, spec-conformant. | content denylist; `skills-ref validate`-equivalent checks; end-to-end offline |
| **C5** | Debug Agent wiring; `suite_source`; frozen-command invariants; workspace-ledger mutation derivation. | D1/D2/D3 semantics green |
| **C6** | `capabilities/external/` — `EgressPolicy`, `EgressLedger` (ordering per §6.2), `DocsPort`, config, `Context7Adapter` against a fake MCP client, `LookupDocsTool`. **No transport.** | all external tests offline, incl. the adapter mapping |
| **C7** | `McpTransport` + Rule I + CLI flags + `context_sources` in both reports. Still no live call in tests. | full offline acceptance (§16) |
| **C8** | *Optional, separately approved:* one live Context7 smoke test. | manual |

C1 carries the self-host suite because the snapshot *is* the security property; proving it
after wiring would mean shipping the escalation path for a phase.

---

## 16. MVP acceptance criteria

**Agent Skills — standard conformance**
1. A skill with only the spec's required `name` + `description` is discovered, advertised
   and loadable, with references — **no AgentGate extension required**.
2. `name` and `description` are validated to the spec's constraints exactly.
3. `license`, `compatibility` and `metadata` parse and are reported; `compatibility` is
   never acted on.
4. AgentGate extensions appear only under `metadata.agentgate.*`.
4a. Frontmatter is parsed with `yaml.safe_load` behind a size cap, an anchor/alias
    refusal, and post-parse shape validation. Skills using ordinary YAML syntax — folded
    or literal multi-line scalars, quoted values containing `:`, comments — load
    correctly. Parsing constructs no objects and grants no authority.

**Agent Skills — behaviour and trust**
5. The model sees `name` + one catalogue line only, within `max_skills_catalogue_chars`; no
   `SKILL.md` body reaches the system prompt.
6. A body enters context only after an explicit `load_skill` call.
7. **A skill root may overlap the workspace and the run still works** (self-hosting).
8. **`load_skill` performs no filesystem access whatsoever**; content served is the
   pre-session snapshot — body and references alike — and a post-snapshot edit cannot
   change it.
9. Post-snapshot mutation is observed from the existing workspace ledger, recorded, never
   ingested; there is no reload API.
10. Neither `allowed-tools` nor any other skill field changes the tool dict, a
    `CommandPolicy` outcome, or an `EgressPolicy` outcome.
11. References are addressable only by enumerated key; traversal and absolute paths cannot
    become keys.
12. `scripts/` and `assets/` are recorded by name and never read or executed.

**Testing capability**
13. `detect()` identifies pytest from each CERTAIN signal and jest/vitest from
    `package.json`, deterministically, with `evidence` naming the file.
14. Every command is argv; `executable` reflects a live `CommandPolicy` verdict.
15. A non-executable detection carries `blocked_reason` and can never be proposed or run.
16. Explicit `--repro`/`--suite` are never replaced; a proposed suite is frozen through
    `freeze_suite`.
17. The skill contains no guidance to delete, skip, or weaken a test.
18. The Debug Agent's `PASSED` still requires proof **and** AgentGate.

**Context7 / egress**
19. Optional: empty `EgressPolicy` ⇒ tool absent from dict and prompt; all agents complete
    offline sessions.
20. Read-only: the port exposes one operation returning text.
21. The ledger lifecycle of §6.2 holds: reserve → call → validate → truncate → record
    actual chars. **No over-budget external text ever reaches model context**, even if the
    provider ignores the hint.
22. **A model cannot name a server, capability, operation, or endpoint.**
23. The adapter maps `lookup_docs` onto `resolve-library-id` + `query-docs` as specified in
    §6.3, skipping the resolve hop for a `/org/project` input.
24. Observable: every call, denial and failure appears in `SessionLog` and
    `context_sources`.
25. Every failure is a tool observation; none aborts a session.

**Architecture**
26. No duplicated session loop; `CodingSession` gains no new decision branch.
27. No agent imports an MCP SDK or a provider SDK (Rules G, I); `capabilities/` imports no
    agent (Rule H).
28. `verification/`, `eval/`, `runtime/`, `state/`, `orchestrator/` byte-identical.
29. `verdict.gate` semantics, severity thresholds, judge and verification prompts, and the
    benchmark fixtures unchanged.
30. `CommandPolicy` is not widened in this phase.

---

## 17. Risks

| Risk | Mitigation |
|---|---|
| Snapshot masks a legitimately updated skill in a long session | sessions are minutes; overlap mutation is reported; the next run re-snapshots |
| Eager reference reading wastes I/O for never-loaded skills | ~320 KB worst case at startup; the alternative is lazy trust, which is the vulnerability |
| `max_skill_body_chars` at 20 000 admits a large imported skill | `max_loaded_skills = 2`; truncation flagged; realistic first-party case is ~9 000 chars total |
| Catalogue inflates every prompt for skills never used | double cap; ~2 000-char floor; defaults are ceilings revisited from evidence |
| Skills become a second prompt-tuning surface drifting from judges | skills are agent-side only and never reach a judge lens (§13.12) |
| Detected suite silently replaces a good explicit one | detection not consulted when explicit; asserted by test |
| JS/TS detection read as runnable | `executable=False` + `blocked_reason`; cannot reach `freeze_suite` |
| Context7 interface changes upstream | the two-hop mapping is confined to `context7.py` behind `DocsPort`; a single-step provider changes the adapter only |
| `EgressPolicy` grows into a framework | one capability, one operation, until a second real one exists |
| `Limits` grows ~11 fields | ceilings on one dataclass, the pattern the repo already chose |
| Capability layer drifts toward importing agents | Rule H fails the build |

---

## 18. Resolved decisions

**A. Catalogue placement — RESOLVED: system prompt, bounded metadata only.**
A concise static "Available skills" section in the session system prompt carrying the
skill's `name`, a short description, and its when-to-use line — nothing else. Capped per
skill (`max_skill_metadata_chars`) and in total (`max_skills_catalogue_chars`). It sits with
the generated tool catalogue so the two cannot drift. **No `SKILL.md` content ever appears
there**; full content enters context only through `load_skill`.

**B. Skill location — RESOLVED: repo-root `skills/`, trusted by snapshot, not by path.**
`skills/` at the repo root is the authored, git-tracked, reviewable first-party library.
When the target workspace *is* the AgentGate repository, that directory is simultaneously a
skill root and a writable workspace subtree — and that is safe, because
`SkillRegistry.snapshot()` reads every byte it will serve **before `build_capability_tools`
is called**, and `build_capability_tools` requires the snapshotted registry as an argument.
A mutating tool therefore cannot exist before the content was read; afterwards the registry
holds no path it will read from again, and `load_skill` performs no filesystem access at
all. Path separation is explicitly **not** relied upon (§4.1).

**C. Does `load_skill` consume `max_tool_calls`? — RESOLVED: YES.**
It is a model-directed capability action and spends the ordinary tool-call budget.
`max_loaded_skills` is kept **as well**: the two bound different things — tool calls bound
*actions*, `max_loaded_skills` bounds *context*. Without the first, skill loading is a free
unlimited side channel; without the second, a session could spend its whole tool budget on
context. A refused or duplicate load still costs a tool call and does not re-spend
`max_loaded_skills`.

**D. `max_loaded_skills` — RESOLVED: 2.**
Testing plus one task-specific skill is enough for Coding, Debug and Refactoring MVP use. A
deterministic context bound, not adaptive tuning; raisable from evidence later.

---

## 19. Revision history

**rev 3 — standards/reference validation.** Changes driven by the external references:

| § | Change | Driver |
|---|---|---|
| 4.3 | **Contradiction fixed.** `load_skill` now performs **zero** filesystem access; the rev-2 "may re-stat/re-digest to detect mutation" is removed. Mutation is derived from `workspace.changed_files` for overlapping roots; provenance digests only otherwise. | internal contradiction |
| 4.5 | Rewritten as an explicit **standard vs extension** table. `when_to_use` and `version` moved out of top-level frontmatter into `metadata.agentgate.when_to_use` / `metadata.version`; `license` and `compatibility` added; `tools:` replaced by the standard's `allowed-tools`, recorded but never honoured. | `agentskills.io/specification` |
| 4.5 | `name` constraints corrected: 1–64 chars (was 32) and **consecutive hyphens now rejected**; `description` capped at 1024. | spec |
| 4.6, 4.9 | `assets/` added to the directory model — names recorded, contents never read. | spec |
| 4.7 | Progressive-disclosure levels mapped explicitly to the spec's three levels; `max_skill_body_chars` raised 6 000 → **20 000** so a spec-conformant skill is not truncated. | spec (< 5 000 tokens recommended) |
| 6.2 | **`EgressLedger` ordering defined**: reserve → call → validate → truncate → record actual accepted chars; `fail_call()` for a spent-but-empty slot. | ordering defect |
| 6.3 | Real Context7 interface recorded (`resolve-library-id(query, libraryName)`, `query-docs(libraryId, query)`) and the wrapper mapping specified, including the `/org/project` fast path and the no-server-side-size-parameter consequence. | upstash/context7 README |
| 8 | New section: Hermes comparison — borrowed, differed, and why instructions never grant authority. | Hermes docs |
| 9 | `max_loaded_references` 4 → 3; body ceiling raised; context budget recomputed with a realistic case beside the worst case. | spec + budget |
| 13 | Deferred list extended: `assets/` loading, honouring `allowed-tools`, skill-declared config, general external-root mutation detection, full YAML. Marketplace deferral now cites the catalogues' lack of a verification model. | spec, Hermes, catalogues |
| 14, 16 | Standard-conformance test group and criteria 1–4, 8, 9, 21, 23 added. | all |

**rev 3.1 — file-integrity and conformance-claim pass.** Verified the on-disk file
programmatically: 51 real headings, no duplicate headings and no duplicate numbered
sections (§0–§19, no gaps); `max_skill_loads` absent; no live "startup error" or
"root inside the workspace" rule; `resolve-library-id`/`query-docs` present and
`get-library-docs` absent; no top-level `when_to_use:` or `tools:` skill field. One
substantive correction: **the fixed-key frontmatter reader was replaced with
`yaml.safe_load`** (Option A). A fixed-key reader could reject syntactically valid skills
using only standard fields — folded scalars in particular, which a 1024-character
`description` makes routine — so claiming Agent Skills conformance while shipping one
would have been false. PyYAML is added as a declared dependency, guarded by a size cap, an
anchor/alias refusal (closing the alias-expansion DoS that `safe_load` does not cover), and
post-parse shape validation. §0.7, §3, §4.6, §9, §12, §13.14, §14, §16 updated.

**rev 2 — trust-boundary hardening.** Introduced the `SkillPackage` immutable snapshot,
trust tiers, `EgressPolicy`, `executable`/`blocked_reason` on `TestEnvironment`, and
resolved the four open decisions. Reversed rev 1's rule that a skill root inside the
workspace is a startup error: that broke self-hosting and relied on path separation rather
than on a trust property. The current position is §4.1–§4.2 — overlap is permitted,
recorded, and neutralised by snapshot ordering.

**rev 1 — initial blueprint.**
