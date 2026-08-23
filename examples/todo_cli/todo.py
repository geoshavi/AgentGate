"""A tiny due-date helper, deliberately incomplete.

``parse_due_date`` crashes on empty input instead of reporting a clear error.
This is the demo fixture for the Coding Agent: small enough that a real
provider run costs almost nothing, and broken in exactly one obvious way.
"""


def parse_due_date(raw: str) -> tuple[int, int, int]:
    """Parse an ISO date of the form YYYY-MM-DD into (year, month, day)."""
    parts = raw.split("-")
    return int(parts[0]), int(parts[1]), int(parts[2])
