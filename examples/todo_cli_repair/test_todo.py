from todo import parse_due_date


def test_parses_iso_date() -> None:
    assert parse_due_date("2026-08-21") == (2026, 8, 21)


def test_tolerates_surrounding_whitespace() -> None:
    assert parse_due_date("  2026-08-21  ") == (2026, 8, 21)
