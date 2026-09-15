---
name: refactoring-architecture
description: Refactor and review architecture without changing behaviour -- map dependencies before editing, name coupling/duplication/layering/dead-code/oversized-module issues as observed facts kept separate from suggestions, and change in small reversible steps validated by the narrowest relevant test first. Use when asked to refactor, clean up, restructure, reduce duplication, or review a module's or a codebase's architecture.
license: Apache-2.0
metadata:
  agentgate.when_to_use: Before refactoring or reviewing architecture, and whenever a cleanup task risks moving behaviour rather than just structure.
---

# Refactoring and architecture review

The one rule everything else here serves: **a refactor changes structure, not behaviour.**
If a change alters what the program does, it is a feature or a fix wearing a refactor's
name, and it needs the scrutiny those get -- not this skill's.

## 1. Map before you touch anything

Editing before you know who depends on what is how a local cleanup becomes a remote
breakage. If a `repo_graph` tool is available, use it before editing:

- `find_symbol` / `find_references` — where a thing is defined and where it is used.
  `find_references` matches names, not resolved types, so treat a hit as a lead to read,
  not as proof.
- `find_dependents` / `related_files` — what imports the module you are about to touch,
  and what it imports. This is your blast radius.
- `show_module_graph` — the shape of a module's neighbourhood, or the whole scan, when
  you need to see layering rather than one file at a time.

If it is unavailable, do the equivalent by reading: find callers by searching the symbol
name, and read the module's own imports. Either way, do this **before** forming a plan --
a plan built without knowing the callers is a guess.

## 2. Separate what you observed from what you suggest

Two different kinds of statement, and a reader needs to tell them apart:

- **Observed fact**: "`Config` is imported by 14 modules across three packages" or
  "`process()` and `process_v2()` duplicate the same 40 lines." Verifiable from the code,
  true regardless of what happens next.
- **Suggestion**: "extracting the shared 40 lines into a helper would remove the
  duplication." An opinion about what to do with the fact.

State facts first, plainly, with evidence (a symbol, a file, a line, a dependent count).
Only then propose. Never fold the two into one sentence that reads as settled when it is
actually a recommendation.

## 3. What to look for

- **Coupling** — a module reaching into another's internals, or two modules that change
  together far more often than their interfaces suggest they should.
- **Duplication** — the same logic in more than one place, especially when the copies have
  already drifted.
- **Layering issues** — a lower layer importing from a higher one, or a dependency that
  crosses a boundary the codebase otherwise respects everywhere else.
- **Dead code** — a symbol `find_references` finds no live caller for. Confirm with a
  second signal (an export list, a plugin registry, a test that imports it only) before
  calling something dead — an unused-looking symbol can still be a public interface.
- **Oversized modules or functions** — a unit doing several unrelated things, where the
  size itself is what makes the next change risky to make safely.

Every item you name should point at what you observed (per step 2), not a general
impression.

## 4. Use static analysis as evidence, not as the answer

If an `analyze_code` tool is available, its findings are advisory: read them alongside
what you already found, weigh them the way you would a colleague's comment, and never
report a finding as settled just because a tool produced it.

## 5. Change in small, reversible steps

- Prefer several small changes you could revert independently over one large rewrite.
- Do not rewrite what already works correctly just because it could be written
  differently -- a rewrite is justified by a concrete problem (per step 3), not by taste.
- Preserve public interfaces -- function signatures, exported names, on-disk formats,
  configuration keys -- unless the task explicitly asks for the interface itself to
  change. A caller you have not mapped may depend on the exact shape you are tempted to
  tidy.
- After each step, the program should still do what it did before. If you cannot state
  what would prove that, the step is too large.

## 6. Validate every step

Use the `testing` skill's procedure: narrow test first, then the affected area, then the
full suite before you call the work done. `detect_tests` is evidence about what suite
exists and whether it is runnable here -- not a suggestion to skip validation if it comes
back uncertain.

Never weaken, delete, or skip a test to make a refactor look green. A test that starts
failing after a structural change is telling you the change moved behaviour, not just
structure -- treat that as the refactor being wrong, not the test.

## 7. Report

State, separately: what you observed (step 2), what you changed and why it preserves
behaviour, and what you validated it against (which test scope, and whether it passed).
An architecture review that proposes no edit is a complete, useful result on its own --
say so plainly rather than manufacturing a change to justify the review.

## Scope

Procedure only. This skill does not run anything itself and grants no authority beyond
what the environment's tools and command policy already permit; if a tool it names is
unavailable, do the nearest manual equivalent and say that you did.
