"""Capability layer: skills, test detection, and external lookups.

A leaf package. It must not import ``engine.codeagent`` or ``engine.debugagent``
(architecture Rule H), which is what lets every agent -- including ones that do
not exist yet -- use it without another agent on its import path, and what makes
"a skill cannot reach a policy object" structurally true rather than promised.

Everything here trades in plain values: paths, strings, integers and frozen
dataclasses. Bounds arrive as this package's own ``SkillBounds`` rather than as
``codeagent.limits.Limits``, and the mapping between the two lives at the caller
seam, which is also the only place it can drift.
"""
