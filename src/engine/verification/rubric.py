DIMENSIONS: tuple[str, ...] = ("CORRECTNESS", "SECURITY", "CODE-QUALITY")

SEVERITIES: frozenset[str] = frozenset({"CRITICAL", "HIGH", "MEDIUM", "LOW"})
BLOCKING: frozenset[str] = frozenset({"CRITICAL", "HIGH"})

# How a defect's claim relates to what the task and the supplied code actually
# establish. A closed enum, not free text: the point of the field is that the
# classification can be cross-checked against severity by code, and a bare
# non-empty string is satisfied by any characters at all.
# See docs/benchmark/STRUCTURED_GROUNDING_REGISTRATION.md.
GROUNDING_STATUSES: frozenset[str] = frozenset(
    {
        "in_contract_reachable",
        "out_of_contract",
        "contradicts_explicit_guarantee",
        "factually_unverified",
    }
)

# The only status a blocking severity may carry. The other three each describe a
# claim that cannot support blocking: usage the interface excludes, a premise the
# task rules out, or behavior not demonstrated from the supplied code.
GROUNDED_STATUS: str = "in_contract_reachable"

# Required on every defect, at any severity.
DEFECT_KEYS: frozenset[str] = frozenset(
    {"id", "category", "severity", "location", "fix", "grounding_status"}
)

# Additionally required, and non-empty after stripping, on CRITICAL/HIGH defects.
# Their conjunction *is* the "grounding evidence" requirement -- a separate free-text
# evidence field would add schema-failure surface without adding a check, and that
# choice is registered rather than silently taken.
BLOCKING_GROUNDING_KEYS: frozenset[str] = frozenset(
    {"violated_requirement", "code_path", "trigger"}
)

CRITIC_KEYS: frozenset[str] = frozenset({"defects", "verdict"})
