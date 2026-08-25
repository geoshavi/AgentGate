# Choosing a test scope for a diff

How to pick the targeted and affected-area scopes described in step 2 of the skill. The
question this answers: given what I just changed, what is the smallest check that would
actually catch me being wrong, and what is the next one out?

## Targeted: find the test that already covers the change

In order of reliability:

1. **A test that names the thing.** Search the test tree for the function, class or
   module you edited. A test file named after the module is the usual convention in most
   repositories.
2. **A test that imports the thing.** If nothing is named for it, search for imports of
   the module. That finds indirect coverage the naming convention missed.
3. **A test for the reported behaviour.** For a bug fix, the reproduction is the targeted
   test — the one that failed before the change and should pass after it.

If none of these exists, the change has no targeted coverage. That is worth saying, and
usually worth fixing by writing the test *first*, so you can watch it fail for the right
reason before the fix makes it pass. A test written after the fix and passing immediately
has not been shown to detect anything.

## Affected area: one step out

The affected area is whatever shares state or contract with what you changed:

- the module's own test file, in full — not just the one case you targeted
- tests for direct callers, which is where a changed signature or return type surfaces
- tests for the same subsystem, when you changed something they all route through
- tests for anything the diff touched incidentally, including fixtures and helpers

A quick way to find callers: search for the symbol name across the tree, then keep the
hits that are under a test path.

## When to go straight to the full suite

Narrow-first is about iteration speed, not about avoiding the suite. Some changes have no
meaningful narrow scope, and going straight to the full run is correct:

- a change to shared configuration, a base class, or a widely imported utility
- a dependency change, which can move behaviour anywhere
- a rename or signature change touching several call sites
- anything where you cannot name the blast radius with confidence

## Before you finish

Whatever you ran while iterating, the closing evidence should be the broad one. A green
targeted test and a green full suite are different claims; only the second says nothing
else moved.

Run the static gates too. Lint and type checks catch a class of error that no test does —
an unused import, an impossible branch, a type that cannot be what the caller passes —
and they cost a fraction of a suite run.

## Recording what you ran

Name the scope and the command in your summary, not just the outcome. "Targeted test
passes" and "full suite passes" are both useful; "tests pass" is not, because the reader
cannot tell which claim was made.
