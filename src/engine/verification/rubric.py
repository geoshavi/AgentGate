DIMENSIONS: tuple[str, ...] = ("CORRECTNESS", "SECURITY", "CODE-QUALITY")

SEVERITIES: frozenset[str] = frozenset({"CRITICAL", "HIGH", "MEDIUM", "LOW"})
BLOCKING: frozenset[str] = frozenset({"CRITICAL", "HIGH"})

DEFECT_KEYS: frozenset[str] = frozenset({"id", "category", "severity", "location", "fix"})
CRITIC_KEYS: frozenset[str] = frozenset({"defects", "verdict"})
