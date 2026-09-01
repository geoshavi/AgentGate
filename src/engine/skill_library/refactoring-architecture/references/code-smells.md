# Identifying coupling, duplication, layering, dead code, and size issues

Step 3 of the skill names five things to look for. This is what to check for each, and
what counts as evidence rather than impression.

## Coupling

Evidence: a module reaching past another's public interface into its internals (a private
name, an implementation detail its own tests don't cover), or two modules whose diffs
keep appearing together in history for reasons their public interfaces don't explain.
`find_dependents` and `related_files` show *that* two modules are connected; read both
sides to see *how tightly* — through a narrow, stable interface, or through details that
could change under either module's own local reasoning.

Not evidence: two modules simply calling into each other through a small, stable
interface. That is normal structure, not coupling to fix.

## Duplication

Evidence: the same logic, not just the same shape, appearing in more than one place.
Search for distinctive literals, error messages, or a sequence of calls unlikely to occur
by coincidence. Two independent implementations of the same idea that have already
drifted (one fixed a bug the other still has) are the clearest case — the drift itself is
proof they were never actually kept in sync.

Not evidence: two functions that happen to be the same length, or two similar-looking
validations that check genuinely different things. Structural similarity is not logical
duplication.

## Layering issues

Evidence: an import that runs the wrong direction against a layering the codebase
otherwise respects everywhere else — a lower-level module (storage, protocol, utility)
importing from a higher-level one (business logic, orchestration, presentation), or a
boundary a project's own structure implies (a `capabilities/` that is meant to be a leaf,
a `core/` that other packages depend on but that depends on none of them). Use
`show_module_graph` with no path to see fan-in across the whole scan, then check whether
the direction of the highest-fan-in edges matches the codebase's own apparent intent.

Confirm the intended layering before calling a specific import a violation — read how the
codebase describes its own structure (a module docstring, an architecture note) rather
than inferring a rule from one file and applying it everywhere.

## Dead code

Evidence: `find_references` returns no hits for a symbol, confirmed by a second signal --
it is not in an `__all__` / export list, not registered in a plugin or command table, not
referenced by a string (a dynamic dispatch, a CLI command name, a config key), and not
exercised only by a test that would itself be the last reference.

A symbol with a docstring calling it a public interface, or one exported from a package's
`__init__`, is not dead just because nothing in this repository calls it — it may exist
for external callers. Say so rather than proposing removal.

## Oversized modules or functions

Evidence: a function or module doing several things that do not share a reason to change
together — not merely a high line count. A 200-line function that is one long sequential
algorithm with no reasonable split point is not automatically oversized; a 40-line
function that mixes validation, a database call, and formatting for three different
callers usually is, because each concern would change for a different reason.

## Reporting a smell

For every item: name the file and symbol, state the observed evidence (not "this feels
tangled" but "X is imported by Y, Z, W and reaches into `_private_helper`"), and only then
suggest what could be done about it. A reader should be able to check your evidence
against the code without taking your conclusion on faith.
