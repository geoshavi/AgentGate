# Triaging an unexpected test failure

Step 4 of the skill says to read a failure before reacting to it. This is how to read it,
and how to tell the three kinds apart, because they need different responses.

## First, read the actual failure

Before forming any theory, get these four facts out of the output:

- the **assertion or exception** — what was expected, what was received
- the **file and line** in the code under test, not just in the test
- the **test name**, which usually states the intended behaviour in words
- whether **one test failed or many**, which separates a local mistake from a broken
  import, fixture or shared setup

Many failures are fully explained by these four and need no theory at all.

## Then decide which kind it is

**Caused by your change.** The failing test covers something in your diff, and it passed
before. This is the common case and the easy one: the test is telling you the change is
incomplete or wrong. Fix the code.

**Pre-existing.** The test was already failing before you touched anything. Confirm it
rather than assuming it — stash or set aside your change, or run the test against the
unmodified file, and see. If it was already red, say so in your summary and keep it
separate from your own work. Repairing it may be out of scope; silently absorbing it into
your diff makes both changes harder to review.

**Flaky.** The test passes and fails without the code changing. Usual causes: dependence
on wall-clock time, ordering between tests, a shared temporary path, an unseeded random
value, or a real race. A repeat run that flips the result is evidence of flakiness, but it
is not a licence to move on — record it, and if the flake is in the area you are working
on, it is part of the work.

Distinguishing these matters more than fixing any of them quickly, because the wrong
classification sends the next hour in the wrong direction.

## Narrowing a failure you do not understand

- Re-run just the failing test to remove noise from the output.
- Read the test body. It states the intended contract more precisely than any name.
- Check the boundaries first: empty input, zero, `None`, an unexpected type. A large
  share of real failures live there.
- Compare against a passing sibling test. The difference between them is usually the
  cause.
- Add a temporary assertion or print to observe the actual value, and remove it before
  you finish.

## Things that are not fixes

Making the message go away is not the same as making the problem go away. A test that
fails and then does not, without the code changing, has been silenced rather than
repaired — and the next person has no way to know. Do not reach for skip markers,
loosened assertions, deselection or a disabled rule to reach green; if the failure is
genuinely out of scope, leave it failing and say so.

Re-running an unchanged command is also not a fix. If nothing changed between the two
runs, the second result carries no more information than the first.

## When you cannot resolve it

Stop and report. Say which test fails, what the assertion was, what you tried, and what
you believe the cause is. A precise description of an unsolved failure is a genuinely
useful result — it is where the next person starts, and it costs them far less than
discovering the problem again from a summary that claimed success.
