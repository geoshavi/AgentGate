"""Due-date helper whose contract includes tolerating surrounding whitespace.

The repair-demo fixture: the obvious guard for "reject empty input" is a
length check, and a length check breaks ``test_tolerates_surrounding_whitespace``.
The agent has to run the tests, see the failure, and correct its own fix.
"""


def parse_due_date(raw: str) -> tuple[int, int, int]:
    """Parse an ISO date of the form YYYY-MM-DD.

    Surrounding whitespace is tolerated: ``int`` accepts it on each part.
    """
    parts = raw.split("-")
    return int(parts[0]), int(parts[1]), int(parts[2])
