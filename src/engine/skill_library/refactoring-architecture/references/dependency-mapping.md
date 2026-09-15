# Mapping dependencies before a refactor

Step 1 of the skill says to map before you touch anything. This is how, using the
`repo_graph` tool when it is available.

## The five queries and what each answers

- **`find_symbol`** — where is this defined? Start here for any symbol you are about to
  move, rename, or change the signature of. More than one definition with the same name
  means read every one before assuming which the caller means.
- **`find_references`** — where is this name used? Matches the bare identifier, not a
  type-resolved reference, so a hit for a common name (`run`, `process`, `Config`) can be
  an unrelated symbol. Open enough of the surrounding hits to tell real matches from
  coincidental ones before you rely on the count.
- **`find_dependents`** — which modules import this file? This is the direct blast radius
  of a change to the file's public surface. A file with many dependents needs a more
  conservative change than one with none.
- **`related_files`** — the union of what a module imports and what imports it: its
  immediate neighbourhood. Useful for getting oriented in an unfamiliar area before
  deciding where a boundary actually is.
- **`show_module_graph`** — one module's direct edges, or a whole-scan summary (most
  fan-in, module and symbol counts) when no path is given. Use the summary form to find
  hub modules before assuming which ones matter.

## Reading the answers honestly

Every result is bounded and may be truncated -- a `showing: N of M` line means there is
more than what is displayed. Do not treat a truncated list as the complete set of
dependents; widen the query or read further before concluding "nothing else uses this."

The graph is a local, deterministic AST/import scan. It knows the *syntax* of imports and
definitions; it does not know what a dynamic import, a string-built attribute lookup, or a
plugin registry does at runtime. Treat a "no dependents found" result as evidence, not
proof — a module reached only through such a mechanism will show zero dependents here and
still break if you change it. When in doubt, search text as a second signal.

## When it is unavailable

Do the same mapping by hand:

1. Search the codebase for the symbol's name to find likely callers.
2. Read the target module's own `import` statements to see what it depends on.
3. Read one or two of the found callers in full, not just the matching line -- a grep hit
   tells you a name appears, not how it is used.

The order of operations is what matters, not the tool: understand who depends on
something before you change its shape.

## Using the map

A dependency map changes what "small" means for a given step. A private helper with one
caller can be changed freely. A function with a dozen dependents across several packages
needs either a narrower first step (add the new shape alongside the old, migrate callers
one at a time) or an explicit note in your report that the change touches all of them.
