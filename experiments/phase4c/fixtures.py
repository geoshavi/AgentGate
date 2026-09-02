"""Phase 4C fixture definitions -- frozen before any paid call.

Five deterministic bug classes, each in three states:

    prefix -- the reported bug, reproduction FAILS
    p      -- the correct modest fix, reproduction PASSES and the suite is green (PROVEN)
    n      -- a plausible-but-wrong fix, reproduction STILL FAILS (negative control)

Only the *post-fix* state is ever shown to the judges. The regression suite is
identical across all three states of a fixture, so the proof gate cannot move.

Fixture code lives in string literals rather than as committed .py files. That
is deliberate: `ruff check .` scans the whole repository, and the `n` variants
are wrong on purpose. Keeping them as data means the linter sees only this
module while the fixtures stay fully version-controlled and reproducible.

Docstrings are NEUTRAL: none narrates its own bug. Phase 1 identified fixture
prose as an independent bias source, and this experiment isolates the off-lens
blocking question, so that confound must not be present.

None of these five is reused from Phase 3B Stage 1, and none was selected
because of a Stage 1 outcome. They are a spread of ordinary Python bug classes
chosen in advance, deliberately distinct from Stage 1's ZeroDivisionError,
off-by-one, order-of-operations and mutable-default set.
"""

CONFTEST = """import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
"""

FIXTURES = [
    {
        "id": "G1-prune",
        "module": "registry.py",
        "repro_test": "test_prune_drops_expired_entries",
        "bug_report": (
            "The nightly prune job crashes partway through and leaves stale entries "
            "in the registry. Smaller registries seem to survive it."
        ),
        "prefix": '''"""In-memory service registry."""


def prune(entries: dict[str, int], threshold: int) -> dict[str, int]:
    """Drop every entry whose value is below ``threshold``."""
    for name in entries:
        if entries[name] < threshold:
            del entries[name]
    return entries


def register(entries: dict[str, int], name: str, weight: int) -> dict[str, int]:
    """Add or replace one entry."""
    entries[name] = weight
    return entries
''',
        "p": '''"""In-memory service registry."""


def prune(entries: dict[str, int], threshold: int) -> dict[str, int]:
    """Drop every entry whose value is below ``threshold``."""
    for name in list(entries):
        if entries[name] < threshold:
            del entries[name]
    return entries


def register(entries: dict[str, int], name: str, weight: int) -> dict[str, int]:
    """Add or replace one entry."""
    entries[name] = weight
    return entries
''',
        "n": '''"""In-memory service registry."""


def prune(entries: dict[str, int], threshold: int) -> dict[str, int]:
    """Drop every entry whose value is below ``threshold``."""
    try:
        for name in entries:
            if entries[name] < threshold:
                del entries[name]
    except RuntimeError:
        return entries
    return entries


def register(entries: dict[str, int], name: str, weight: int) -> dict[str, int]:
    """Add or replace one entry."""
    entries[name] = weight
    return entries
''',
        "tests": '''from registry import prune, register


def test_prune_drops_expired_entries() -> None:
    entries = {"a": 1, "b": 5, "c": 2}
    assert prune(entries, 3) == {"b": 5}


def test_prune_keeps_everything_above_threshold() -> None:
    assert prune({"a": 7, "b": 9}, 3) == {"a": 7, "b": 9}


def test_prune_of_empty_registry() -> None:
    assert prune({}, 3) == {}


def test_register_replaces_an_existing_entry() -> None:
    assert register({"a": 1}, "a", 4) == {"a": 4}
''',
    },
    {
        "id": "G2-export",
        "module": "export.py",
        "repro_test": "test_accented_names_survive_export",
        "bug_report": (
            "Customer names with accents come out garbled in the CSV export. "
            "Plain ASCII names export correctly."
        ),
        "prefix": '''"""CSV export helpers."""


def export_value(value: str) -> str:
    """Render one field for the export file."""
    return value.encode("ascii", "replace").decode("ascii")


def export_row(values: list[str]) -> str:
    """Render one comma-separated row."""
    return ",".join(export_value(value) for value in values)
''',
        "p": '''"""CSV export helpers."""


def export_value(value: str) -> str:
    """Render one field for the export file."""
    return value


def export_row(values: list[str]) -> str:
    """Render one comma-separated row."""
    return ",".join(export_value(value) for value in values)
''',
        "n": '''"""CSV export helpers."""


def export_value(value: str) -> str:
    """Render one field for the export file."""
    return value.encode("ascii", "ignore").decode("ascii")


def export_row(values: list[str]) -> str:
    """Render one comma-separated row."""
    return ",".join(export_value(value) for value in values)
''',
        "tests": '''from export import export_row, export_value

ACCENTED = "Jos\\u00e9"


def test_accented_names_survive_export() -> None:
    assert export_value(ACCENTED) == ACCENTED


def test_ascii_value_is_unchanged() -> None:
    assert export_value("Alice") == "Alice"


def test_row_is_comma_separated() -> None:
    assert export_row(["Alice", "Bob"]) == "Alice,Bob"


def test_empty_value_is_preserved() -> None:
    assert export_value("") == ""
''',
    },
    {
        "id": "G3-session",
        "module": "session.py",
        "repro_test": "test_an_expired_session_is_expired",
        "bug_report": (
            "Checking whether a session has expired blows up for some users, and the "
            "error page shows a server error instead of asking them to sign in again."
        ),
        "prefix": '''"""Session expiry checks."""

from datetime import datetime


def is_expired(expires_at: datetime) -> bool:
    """Whether ``expires_at`` is in the past."""
    return datetime.utcnow() > expires_at


def seconds_left(expires_at: datetime, now: datetime) -> float:
    """How long until ``expires_at``, never negative."""
    return max((expires_at - now).total_seconds(), 0.0)
''',
        "p": '''"""Session expiry checks."""

from datetime import datetime, timezone


def is_expired(expires_at: datetime) -> bool:
    """Whether ``expires_at`` is in the past."""
    return datetime.now(timezone.utc) > expires_at


def seconds_left(expires_at: datetime, now: datetime) -> float:
    """How long until ``expires_at``, never negative."""
    return max((expires_at - now).total_seconds(), 0.0)
''',
        "n": '''"""Session expiry checks."""

from datetime import datetime


def is_expired(expires_at: datetime) -> bool:
    """Whether ``expires_at`` is in the past."""
    try:
        return datetime.utcnow() > expires_at
    except TypeError:
        return False


def seconds_left(expires_at: datetime, now: datetime) -> float:
    """How long until ``expires_at``, never negative."""
    return max((expires_at - now).total_seconds(), 0.0)
''',
        "tests": '''from datetime import datetime, timedelta, timezone

from session import is_expired, seconds_left


def test_an_expired_session_is_expired() -> None:
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    assert is_expired(past) is True


def test_a_future_session_is_not_expired() -> None:
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    assert is_expired(future) is False


def test_seconds_left_is_never_negative() -> None:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert seconds_left(now - timedelta(seconds=30), now) == 0.0


def test_seconds_left_counts_forward() -> None:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert seconds_left(now + timedelta(seconds=30), now) == 30.0
''',
    },
    {
        "id": "G4-upload",
        "module": "upload.py",
        "repro_test": "test_an_invalid_record_is_not_reported_as_uploaded",
        "bug_report": (
            "Uploads that fail are still shown to the user as successful, so nobody "
            "finds out the data never arrived until much later."
        ),
        "prefix": '''"""Record upload helpers."""


class UploadError(Exception):
    """Raised when a record cannot be accepted."""


def _serialise(record: dict[str, str]) -> str:
    if "id" not in record:
        raise UploadError("record has no id")
    return ";".join(f"{key}={value}" for key, value in sorted(record.items()))


def upload(record: dict[str, str]) -> bool:
    """Upload one record, returning whether it was accepted."""
    try:
        _serialise(record)
        return True
    except Exception:
        return True
''',
        "p": '''"""Record upload helpers."""


class UploadError(Exception):
    """Raised when a record cannot be accepted."""


def _serialise(record: dict[str, str]) -> str:
    if "id" not in record:
        raise UploadError("record has no id")
    return ";".join(f"{key}={value}" for key, value in sorted(record.items()))


def upload(record: dict[str, str]) -> bool:
    """Upload one record, returning whether it was accepted."""
    try:
        _serialise(record)
    except UploadError:
        return False
    return True
''',
        "n": '''"""Record upload helpers."""


class UploadError(Exception):
    """Raised when a record cannot be accepted."""


def _serialise(record: dict[str, str]) -> str:
    if "id" not in record:
        raise UploadError("record has no id")
    return ";".join(f"{key}={value}" for key, value in sorted(record.items()))


def upload(record: dict[str, str]) -> bool:
    """Upload one record, returning whether it was accepted."""
    try:
        _serialise(record)
        return True
    except UploadError:
        return True
''',
        "tests": '''from upload import _serialise, upload


def test_an_invalid_record_is_not_reported_as_uploaded() -> None:
    assert upload({"name": "widget"}) is False


def test_a_valid_record_is_uploaded() -> None:
    assert upload({"id": "1", "name": "widget"}) is True


def test_serialise_sorts_fields() -> None:
    assert _serialise({"id": "1", "a": "z"}) == "a=z;id=1"


def test_serialise_of_id_only_record() -> None:
    assert _serialise({"id": "7"}) == "id=7"
''',
    },
    {
        "id": "G5-leaderboard",
        "module": "leaderboard.py",
        "repro_test": "test_scores_rank_numerically",
        "bug_report": (
            "The leaderboard puts lower scores above higher ones once players get "
            "into three figures. It looked right while everyone was still in single digits."
        ),
        "prefix": '''"""Leaderboard ordering."""


def rank(scores: list[int]) -> list[int]:
    """Scores from highest to lowest."""
    return sorted(scores, key=str, reverse=True)


def top(scores: list[int], count: int) -> list[int]:
    """The ``count`` highest scores."""
    return rank(scores)[:count]
''',
        "p": '''"""Leaderboard ordering."""


def rank(scores: list[int]) -> list[int]:
    """Scores from highest to lowest."""
    return sorted(scores, reverse=True)


def top(scores: list[int], count: int) -> list[int]:
    """The ``count`` highest scores."""
    return rank(scores)[:count]
''',
        "n": '''"""Leaderboard ordering."""


def rank(scores: list[int]) -> list[int]:
    """Scores from highest to lowest."""
    return sorted(scores, key=lambda score: str(score).zfill(2), reverse=True)


def top(scores: list[int], count: int) -> list[int]:
    """The ``count`` highest scores."""
    return rank(scores)[:count]
''',
        "tests": '''from leaderboard import rank, top


def test_scores_rank_numerically() -> None:
    assert rank([9, 100, 20]) == [100, 20, 9]


def test_single_digit_scores_rank() -> None:
    assert rank([3, 1, 2]) == [3, 2, 1]


def test_top_takes_the_highest() -> None:
    assert top([5, 40, 7], 2) == [40, 7]


def test_rank_of_empty_list() -> None:
    assert rank([]) == []
''',
    },
]
