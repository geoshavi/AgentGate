"""The whole vocabulary an agent-side module gets for external documentation.

One verb, one return type. Arbitrary MCP is not *refused* here so much as
unsayable: there is no ``execute``, no ``fetch_url``, no ``call_tool``, no
``list_servers``, so a module holding a ``DocsPort`` has no way to express those
ideas, whatever a model asks it to do. A vocabulary is a stronger boundary than a
check, because a check can be forgotten and a missing verb cannot.

The port also hides which provider is behind it and how many round trips a lookup
takes. Context7's two-hop protocol lives inside its adapter; if a future provider
answers in one hop, the adapter changes and nothing above it does.

Input validation lives here rather than only in the tool, so any caller of the
port gets the same bounds. The model-facing tool adds its own argument checks on
top -- there, the question is also *which keys were supplied*, which is a
different question from *are these two strings usable*.
"""

from dataclasses import dataclass
from typing import Protocol

from engine.capabilities.errors import DocsUnavailable

# Bounds on what a caller may ask for. Small on purpose: a library name is a
# name, and a topic is a question, not a document.
MAX_LIBRARY_CHARS = 128
MAX_TOPIC_CHARS = 400


@dataclass(frozen=True)
class DocsAnswer:
    """One documentation answer, already bounded.

    ``content`` is **untrusted text**. It may inform the agent; it has no
    structural effect on anything -- see ``codeagent/tools/docs.py``.

    ``resolved_id`` is echoed so a caller can see which library the provider
    actually matched, and pass it back verbatim on a retry to skip resolution.
    That is the one place a model influences the protocol, and it influences
    *which library*, never which server.
    """

    library: str
    resolved_id: str
    topic: str
    content: str
    source: str
    truncated: bool = False


class DocsPort(Protocol):
    """Read documentation. That is the entire interface."""

    def lookup(
        self, *, library: str, topic: str, timeout_s: float, max_chars: int
    ) -> DocsAnswer: ...


def validate_query(library: str, topic: str, max_chars: int) -> tuple[str, str]:
    """Bound the request before any provider is contacted.

    Refusing here rather than after the first hop matters: a malformed request
    that reached the provider would still have spent a reserved call slot, and
    the caller would have paid for a mistake it could have caught for free.

    Raises:
        DocsUnavailable: empty, oversized, non-string, or containing control
            characters. Control characters are refused because a library name
            and a topic are single-line values; anything carrying a newline or a
            NUL is either a mistake or an attempt to smuggle structure into a
            string field.
    """
    cleaned: list[str] = []
    for label, value, ceiling in (
        ("library", library, MAX_LIBRARY_CHARS),
        ("topic", topic, MAX_TOPIC_CHARS),
    ):
        if not isinstance(value, str):
            raise DocsUnavailable(f"{label} must be a string, got {type(value).__name__}")
        stripped = value.strip()
        if not stripped:
            raise DocsUnavailable(f"{label} must not be empty")
        if len(stripped) > ceiling:
            raise DocsUnavailable(
                f"{label} is {len(stripped)} characters; the maximum is {ceiling}"
            )
        if any(ord(char) < 0x20 or ord(char) == 0x7F for char in stripped):
            raise DocsUnavailable(f"{label} must not contain control characters")
        cleaned.append(stripped)

    if max_chars <= 0:
        raise DocsUnavailable("no character allowance remains for a documentation lookup")
    return cleaned[0], cleaned[1]


__all__ = ["MAX_LIBRARY_CHARS", "MAX_TOPIC_CHARS", "DocsAnswer", "DocsPort", "validate_query"]
