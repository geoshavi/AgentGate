DIMENSIONS: tuple[str, ...] = ("CORRECTNESS", "SECURITY", "CODE-QUALITY")

SEVERITIES: frozenset[str] = frozenset({"CRITICAL", "HIGH", "MEDIUM", "LOW"})
BLOCKING: frozenset[str] = frozenset({"CRITICAL", "HIGH"})

DEFECT_KEYS: frozenset[str] = frozenset({"id", "category", "severity", "location", "fix"})
CRITIC_KEYS: frozenset[str] = frozenset({"defects", "verdict"})

# Adjudication evidence. Deliberately NOT folded into DEFECT_KEYS: that set is
# what enforce_critic_schema *requires*, and requiring these is precisely what
# the reverted structured-grounding contract did (9d20c33). Making the evidence
# mandatory gave the judge a reason to move severity instead of supplying it,
# which produced run 57's false pass. These stay optional forever -- a defect
# carrying none of them is unadjudicated, not malformed, and keeps its blocking
# authority. enforce_critic_schema already tolerates extra defect-level keys.
ADJUDICATION_EVIDENCE_KEYS: frozenset[str] = frozenset(
    {
        "grounded_in_clause",
        "excluded_by_clause",
        "minimal_trigger",
        "grounding_route",
        "runtime_probe",
    }
)

GROUNDING_ROUTES: frozenset[str] = frozenset(
    {"explicit_requirement", "permitted_input", "stated_purpose", "none/unclear"}
)

# Every value admissibility.Decision.rule may take. Only the middle three can
# remove blocking authority; the rest are the safe outcomes.
ADMISSIBILITY_RULES: frozenset[str] = frozenset(
    {
        "not-applicable",
        "stated-purpose-protected",
        "declared-interface",
        "explicit-guarantee",
        "factual-premise",
        "fail-closed-unresolved",
    }
)
