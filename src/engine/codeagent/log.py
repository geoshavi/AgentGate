"""Structured session events.

One append-only stream of typed records, held in memory and optionally mirrored
to JSONL on disk. In memory is what tests read; the file is what a later
observability layer reads. Both hold the same records, so a test that asserts on
events is asserting on what would actually be written.

What may be recorded is fixed by the blueprint (§15): plans, tool calls, tool
arguments, tool results, verification output, metrics, and *counts* of model
text. What may not be recorded is the model's prose. That rule is why a
``model_call`` event carries ``text_chars`` and never ``text``, and why a
``parse_error`` event carries the fault description and the response length but
not the response.

The cap below bounds a single logged value, not agent behaviour, which is why it
lives here rather than in ``limits.py``: a session's semantics do not change if
a log line is shortened.
"""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

MAX_LOGGED_VALUE_CHARS = 1_000


@dataclass(frozen=True)
class SessionEvent:
    seq: int
    kind: str
    turn: int
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return dict(asdict(self))


class SessionLog:
    """Append-only event sink.

    ``path`` is optional so a session can run with no filesystem side effect at
    all -- which is how every offline test runs it. When a path is given each
    event is appended and flushed immediately rather than buffered: a session
    that dies mid-turn should still leave every event that happened before it,
    and the volume (tens of events) makes the cost irrelevant.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = Path(path) if path is not None else None
        self._events: list[SessionEvent] = []
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text("", encoding="utf-8")

    @property
    def events(self) -> list[SessionEvent]:
        return list(self._events)

    def of_kind(self, kind: str) -> list[SessionEvent]:
        return [event for event in self._events if event.kind == kind]

    def emit(self, kind: str, turn: int = 0, **payload: Any) -> SessionEvent:
        event = SessionEvent(
            seq=len(self._events) + 1,
            kind=kind,
            turn=turn,
            payload={key: _sanitize(value) for key, value in payload.items()},
        )
        self._events.append(event)
        if self._path is not None:
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event.to_dict(), default=str) + "\n")
        return event


def _sanitize(value: Any) -> Any:
    """Bound every logged value so one oversized argument -- a whole file passed
    to write_file, say -- cannot turn an event stream into a content archive.
    """
    if isinstance(value, str):
        if len(value) <= MAX_LOGGED_VALUE_CHARS:
            return value
        return f"{value[:MAX_LOGGED_VALUE_CHARS]}... [{len(value)} chars total]"
    if isinstance(value, dict):
        return {str(key): _sanitize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value
