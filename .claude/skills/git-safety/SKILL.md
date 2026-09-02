---
name: git-safety
description: Enforces git and file-safety discipline for engine-review-benchmark — verifies a clean working tree and captures the exact commit SHA before any benchmark run, protects the measured benchmark path from unapproved edits, distinguishes read-only inspection from mutation, and requires explicit per-turn approval before any commit, push, or history-altering command. Use before running a benchmark, before editing anything under src/engine/, and whenever a git operation that changes state is being considered.
---

# Git Safety

This repository's value is its 19-run measurement history. That history is only
interpretable if the code that produced each run is exactly identifiable. These rules
protect that property.

Scope note: `.claude/skills/` holds instructions for this assistant.
`src/engine/orchestrator/agents/*.md` are the engine's own runtime sub-agent prompts and
are product code inside the measured tree. Same word, different things — never treat an
edit to one as equivalent to an edit to the other.

## The measured path

Editing any of these changes what the benchmark measures and breaks comparability with
every prior run:

```
src/engine/eval/dataset.py
src/engine/eval/runner.py
src/engine/verification/judge.py        (LENSES, RESPONSE_INSTRUCTION)
src/engine/verification/rubric.py
src/engine/verification/schema.py
src/engine/verification/verdict.py
src/engine/verification/pipeline.py
src/engine/runtime/gateway.py
src/engine/runtime/budget.py
src/engine/config.py                    (DEFAULT_MODELS -- judge model selection)
```

**Never edit these without explicit approval in the current turn**, and never as a
side effect of another task. If a task appears to require touching one, stop and say so
before writing anything.

**Why `config.py` is on this list** (added 2026-09-02, after the fact). `cli.py`'s bench
path reads `DEFAULT_MODELS[provider]["judge"]` to decide which model *every* judge lens
runs on. That choice is as decisive for the measured configuration as the lens prompts
themselves, and changing it silently starts a new configuration cluster in which no prior
run is a valid baseline. Commit `83a4000` ("Experiment: upgrade judge to Sonnet 5") did
exactly that — moving the judge from `claude-haiku-4-5-20251001`, which produced every one
of runs 1-42, to `claude-sonnet-5` — without tripping any approval gate, because the file
was not listed here. The consequences were not small: cost and wall time rose ~4.4x and
~3x, and every off-lens, severity and stability figure in `BASELINE.md` became a statement
about a model the benchmark no longer runs. Only `DEFAULT_MODELS` carries this weight;
the rest of `config.py` reads environment variables, and editing those parts is ordinary
work. Treat a change to any model string as a measured-path change requiring approval and
a `BASELINE.md` note.

## Pre-run gate

Before every benchmark run, in this order:

1. `git status --porcelain` → must be **empty**.
2. `git rev-parse HEAD` → record the SHA alongside the run.
3. Confirm the recorded SHA matches what the experiment plan says should be running.

**Why the clean-tree check is non-negotiable:** `get_git_commit_sha()` in
`src/engine/eval/runner.py` records **`HEAD`, not the working tree**. An uncommitted edit
produces a run permanently stamped with a commit that does not describe what actually
executed — and that corruption is undetectable afterward, because nothing else captures
the file contents. This is the single highest-risk failure mode in the whole benchmark.

If the tree is dirty, either commit (with approval) or revert before running. Do not run
"just this once" against a dirty tree.

Note that `.claude/settings.local.json` is excluded by a global ignore rule
(`**/.claude/settings.local.json`), but `.claude/skills/` is **not** covered by it. New or
edited skill files will show up as changes and must be committed before a run, or the gate
fails.

## Read-only vs. mutating

Classify every operation before running it.

**Read-only — free to use:**
`git log`, `git show`, `git diff`, `git status`, `git ls-files`, `git rev-parse`,
`git check-ignore`, `git blame`; `Read`, `Grep`, `Glob`; copying files into a scratchpad.

**Mutating — needs explicit approval:**
`Edit` / `Write` to anything under `src/engine/`, `tests/`, `pyproject.toml`, `.gitignore`,
or `BASELINE.md`; `git add`, `git commit`, `git push`, `git checkout`, `git switch`,
`git restore`, `git reset`, `git stash`, `git rebase`, `git merge`, `git clean`,
`git tag`; anything with `--force`.

**Running the benchmark is a mutating operation.** `engine bench` spends money, calls a
live API, and appends permanent rows to `.engine/state.db` — a run cannot be undone or
un-recorded. It requires explicit user approval in the current turn, and the pre-run gate
above must pass first. The same applies to `engine run`, `engine serve`, `docker compose
up`, and running the test suite. Analysing results or designing an experiment never
implies permission to execute one.

When in doubt, treat it as mutating.

## Approval rules

- **Never `git commit` or `git push` without the user asking for it in that turn.**
  "Do not commit yet" persists until it is withdrawn.
- **Approval is scoped.** Permission to edit BASELINE.md is not permission to edit
  `dataset.py`. Permission to create files in `.claude/` is not permission to commit them.
- **Approval is per-turn.** Approval given for one commit does not carry to the next.
- **Never** `reset --hard`, `push --force`, `checkout --`, or `clean -fd` on this
  repository. If one of these looks necessary, describe the situation and let the user
  decide.

## Working with `.engine/`

`.engine/state.db` holds the entire run history and is gitignored — **there is no version
control backup**. Treat it as append-only, written solely by `engine bench`. For analysis,
copy it to a scratchpad and query the copy (see `benchmark-analysis`). Never delete
`.engine/`, never reset the database, never edit rows.

## Reporting

When reporting work, state plainly what was changed and what was only read. If a step was
skipped or a check failed, say so with the output rather than summarizing it away.
