"""First-party Agent Skills shipped with the engine.

A data package, deliberately: it holds ``SKILL.md`` files and their references
and contains no code at all. It lives inside ``engine/`` rather than at the
repository root so that one location serves both a source checkout and an
installed wheel -- the alternative was a repo-root directory plus a packaged
copy, which is two copies and a drift problem.

Nothing imports this module for its contents. ``capabilities.skills.roots``
locates it through ``importlib.resources`` and hands the resulting directory to
``SkillRegistry.snapshot`` like any other root, so first-party skills go through
the same parser, the same bounds and the same snapshot ordering as an
operator-supplied one. There is deliberately no shortcut path for built-in
content.
"""
