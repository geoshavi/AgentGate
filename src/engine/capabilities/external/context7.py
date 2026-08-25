"""Context7, behind the port: two provider hops, one bounded answer.

The provider's real interface, as published and validated in C0:

    resolve-library-id   query (required), libraryName (required)
    query-docs           libraryId (required), query (required)

with the documented rule that resolution must happen first unless the caller
already holds an id in ``/org/project`` or ``/org/project/version`` form. There
is **no server-side topic parameter separate from the query, and no size
parameter this side can trust** -- so output bounding is entirely a client
responsibility, done here by truncation rather than by asking politely.

Both hops are one AgentGate lookup and one ledger slot. The two-step protocol is
a provider detail the port exists to hide: every extra model-facing step is
another place a model can loop, and a single-hop provider would change this file
and nothing above it.

**The transport is not here.** ``McpToolCaller`` is an inert Protocol; C6 drives
it with a scripted fake and C7 supplies the real one. Nothing in this module
imports a socket, a subprocess or an SDK, which is deliberate: the thing that
decides what may leave the machine is written and proven before the thing that
leaves it.

Provider output is **untrusted data**. Every response is structurally validated
before any part of it becomes an id or an answer, and a malformed one is an
ordinary lookup failure rather than a guess.
"""

import re
import time
from collections.abc import Callable, Mapping
from typing import Any, Protocol

from engine.capabilities.errors import DocsUnavailable
from engine.capabilities.external.port import DocsAnswer, validate_query

CONTEXT7_PROVIDER = "context7"
RESOLVE_TOOL = "resolve-library-id"
QUERY_TOOL = "query-docs"

# /org/project or /org/project/version. Anchored, no traversal, no whitespace,
# and exactly two or three segments -- a shape a malformed candidate cannot
# accidentally satisfy.
_ID_PATTERN = re.compile(r"^/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)?$")

# Keys a resolver response may carry its candidate list under, and keys a
# candidate may carry its id under. Narrow on purpose: an unrecognised shape is
# a failure, not something to search for an id inside.
_CANDIDATE_LISTS = ("results", "libraries", "candidates")
_ID_KEYS = ("id", "libraryId", "context7CompatibleLibraryID")
_CONTENT_KEYS = ("content", "text", "documentation")


def is_context7_id(value: object) -> bool:
    """True if ``value`` is already a Context7-compatible library id."""
    return isinstance(value, str) and bool(_ID_PATTERN.match(value))


class McpToolCaller(Protocol):
    """The transport seam. Internal to this adapter; no agent-side module holds
    one, and no model-facing argument reaches it."""

    def call_tool(
        self, name: str, arguments: Mapping[str, object], timeout_s: float
    ) -> object: ...


class Context7Adapter:
    """A ``DocsPort`` over Context7's two-tool protocol."""

    provider = CONTEXT7_PROVIDER

    def __init__(
        self, caller: McpToolCaller, *, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._caller = caller
        # Injected so a test can drive the shared timeout budget without
        # sleeping, and so C7 can enforce a real wall clock through the same
        # arithmetic rather than a second mechanism.
        self._clock = clock

    def lookup(
        self, *, library: str, topic: str, timeout_s: float, max_chars: int
    ) -> DocsAnswer:
        """Resolve if needed, fetch, and return an answer bounded to ``max_chars``.

        The timeout covers the **whole wrapper call**, both hops together: a
        per-hop budget would let a slow resolve be followed by an equally slow
        query and double the caller's stated wait.

        Raises:
            DocsUnavailable: bad input, an unusable provider response, no valid
                candidate, an exhausted timeout, or any transport error. All of
                them are one thing to the caller -- the lookup produced nothing --
                and the caller's next move is the same in every case.
        """
        library, topic = validate_query(library, topic, max_chars)
        deadline = self._clock() + timeout_s

        library_id = (
            library if is_context7_id(library) else self._resolve(library, topic, deadline)
        )
        raw = self._call(
            QUERY_TOOL, {"libraryId": library_id, "query": topic}, deadline
        )
        content = _extract_content(raw)

        clipped = content[:max_chars]
        return DocsAnswer(
            library=library,
            resolved_id=library_id,
            topic=topic,
            content=clipped,
            source=CONTEXT7_PROVIDER,
            truncated=len(content) > max_chars,
        )

    # -- hops ---------------------------------------------------------------

    def _resolve(self, library: str, topic: str, deadline: float) -> str:
        """Turn a name into an id, or fail.

        Selection rule, deterministic and deliberately dull: **the first
        structurally valid candidate in the order the provider returned them.**
        The provider ranked them against ``query`` -- that is what the resolve
        hop is for -- so this layer only filters out candidates that are not
        usable ids. It does not re-rank, because a second ranking here would be
        a guess competing with an informed one.
        """
        raw = self._call(RESOLVE_TOOL, {"libraryName": library, "query": topic}, deadline)
        for candidate in _candidates(raw):
            found = _candidate_id(candidate)
            if is_context7_id(found):
                return str(found)
        raise DocsUnavailable(
            f"no Context7 library matched {library!r}; continue from repository evidence"
        )

    def _call(self, name: str, arguments: Mapping[str, object], deadline: float) -> object:
        remaining = deadline - self._clock()
        if remaining <= 0:
            raise DocsUnavailable(f"documentation lookup timed out before {name}")
        try:
            return self._caller.call_tool(name, arguments, remaining)
        except DocsUnavailable:
            raise
        except Exception as exc:
            raise DocsUnavailable(
                f"documentation lookup failed during {name}: {type(exc).__name__}"
            ) from exc


# -- untrusted response parsing ---------------------------------------------


def _candidates(raw: object) -> list[object]:
    """Candidate list from a resolver response, or empty.

    Accepts a bare list, or a mapping carrying one under a known key. Anything
    else yields no candidates, which becomes an ordinary lookup failure -- never
    a search through an unknown structure for something id-shaped.
    """
    if isinstance(raw, list):
        return list(raw)
    if isinstance(raw, dict):
        for key in _CANDIDATE_LISTS:
            found = raw.get(key)
            if isinstance(found, list):
                return list(found)
    return []


def _candidate_id(candidate: object) -> Any:
    if isinstance(candidate, dict):
        for key in _ID_KEYS:
            if key in candidate:
                return candidate[key]
    return None


def _extract_content(raw: object) -> str:
    """The documentation text from a query response, or fail.

    A bare string, or a mapping with a string under a known key. An empty answer
    is a failure too: returning nothing while reporting success would spend a
    call slot and tell the caller it had documentation.
    """
    if isinstance(raw, str) and raw.strip():
        return raw
    if isinstance(raw, dict):
        for key in _CONTENT_KEYS:
            found = raw.get(key)
            if isinstance(found, str) and found.strip():
                return found
    raise DocsUnavailable("documentation lookup returned an unusable response")


__all__ = [
    "CONTEXT7_PROVIDER",
    "QUERY_TOOL",
    "RESOLVE_TOOL",
    "Context7Adapter",
    "McpToolCaller",
    "is_context7_id",
]
