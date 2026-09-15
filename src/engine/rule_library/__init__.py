"""First-party Semgrep rules, shipped with the engine.

Inside the package rather than at the repository root for the same reason
``engine.skill_library`` is: one location serves a source checkout and an
installed wheel alike, and two copies of authored content is a drift problem
nobody notices until an installed agent behaves differently from a developed
one. Located at runtime through ``importlib.resources`` -- see
``capabilities/analysis/rules.py:builtin_ruleset``.

**Local files only.** Semgrep's registry entries (``p/default``, ``--config
auto``) are fetched over the network; a directory of local YAML is not. Keeping
the shipped ruleset here is what lets the analysis capability run with no
registry dependency at all.
"""
