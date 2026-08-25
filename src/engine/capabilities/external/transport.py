"""The wire. The only module in the tree allowed to open a network connection.

Architecture Rule I holds this to one file, exactly as Rule B holds provider SDK
imports to ``runtime/gateway.py``: one egress chokepoint a grep can prove, rather
than a promise spread across a package.

**Streamable HTTP, not stdio.** MCP defines both. stdio would mean launching
``npx -y @upstash/context7-mcp`` as a subprocess -- which needs ``npx`` and
``node`` on ``CommandPolicy``'s allowlist, and C7 does not widen it -- and would
add a process-spawning egress path beside the network one. HTTP is the smaller
boundary and needs no new dependency: ``urllib.request`` is stdlib, so nothing
here pulls in an SDK whose own transports would be outside this file.

Protocol, from the 2025-06-18 specification:

    POST the JSON-RPC message to the single MCP endpoint
    Accept: application/json, text/event-stream   (both, always)
    initialize -> notifications/initialized -> tools/call
    Mcp-Session-Id comes back on InitializeResult and is echoed on every
    subsequent request
    MCP-Protocol-Version accompanies requests after initialisation

The session is established lazily and once, so an ordinary lookup is a single
round trip rather than three.

``opener`` is injected. Every test drives this class through a fake and no test
opens a socket -- which is why C7 can be fully accepted offline.
"""

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

from engine.capabilities.errors import DocsUnavailable

PROTOCOL_VERSION = "2025-06-18"
CLIENT_NAME = "agentgate"
CLIENT_VERSION = "0.1.0"

JSON_MEDIA = "application/json"
SSE_MEDIA = "text/event-stream"
ACCEPT = f"{JSON_MEDIA}, {SSE_MEDIA}"

# request -> (status, headers, body bytes). Injected so the whole transport is
# testable without a socket; production passes `urlopen_adapter`.
Opener = Callable[[urlrequest.Request, float], tuple[int, Mapping[str, str], bytes]]


def urlopen_adapter(
    req: urlrequest.Request, timeout: float
) -> tuple[int, Mapping[str, str], bytes]:
    """The real opener. The single line in this repository that reaches a network."""
    with urlrequest.urlopen(req, timeout=timeout) as response:
        return response.status, dict(response.headers), response.read()


@dataclass
class McpHttpTransport:
    """One Context7 MCP endpoint, spoken to over Streamable HTTP.

    Satisfies ``McpToolCaller``, so ``Context7Adapter`` cannot tell it apart from
    the scripted fake C6 was proven against -- the adapter's mapping, bounds and
    validation are unchanged and untested here because they were tested there.
    """

    url: str
    headers: Mapping[str, str] = field(default_factory=dict)
    opener: Opener = urlopen_adapter
    _session_id: str | None = field(default=None, init=False, repr=False)
    _ready: bool = field(default=False, init=False, repr=False)

    def call_tool(
        self, name: str, arguments: Mapping[str, object], timeout_s: float
    ) -> object:
        """Invoke one MCP tool and return its unwrapped payload.

        Raises:
            DocsUnavailable: any transport, protocol or server-side fault. The
                adapter above turns every one of them into the same observation,
                so distinguishing them here would offer a choice nobody acts on.
        """
        self._ensure_session(timeout_s)
        result = self._request(
            "tools/call", {"name": name, "arguments": dict(arguments)}, timeout_s
        )
        return _unwrap(result)

    # -- lifecycle ----------------------------------------------------------

    def _ensure_session(self, timeout_s: float) -> None:
        """Initialise once, lazily, so a lookup costs one round trip."""
        if self._ready:
            return
        self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": CLIENT_NAME, "version": CLIENT_VERSION},
            },
            timeout_s,
            initialising=True,
        )
        self._notify("notifications/initialized", timeout_s)
        self._ready = True

    def _request(
        self,
        method: str,
        params: Mapping[str, object],
        timeout_s: float,
        *,
        initialising: bool = False,
    ) -> Mapping[str, Any]:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": dict(params)}
        status, headers, body = self._post(payload, timeout_s, initialising=initialising)
        if status >= 400:
            raise DocsUnavailable(f"documentation server returned HTTP {status}")

        # The session id arrives on the InitializeResult and is required on every
        # later request; a server that issues one and is not given it back
        # answers 400.
        session = _header(headers, "Mcp-Session-Id")
        if session:
            self._session_id = session

        message = _decode(headers, body)
        if "error" in message:
            raise DocsUnavailable(f"documentation server error: {_reason(message['error'])}")
        result = message.get("result")
        if not isinstance(result, dict):
            raise DocsUnavailable("documentation server returned an unusable message")
        return result

    def _notify(self, method: str, timeout_s: float) -> None:
        """A notification has no id and expects 202 with no body."""
        status, _, _ = self._post({"jsonrpc": "2.0", "method": method}, timeout_s)
        if status >= 400:
            raise DocsUnavailable(f"documentation server rejected {method} (HTTP {status})")

    def _post(
        self,
        payload: Mapping[str, object],
        timeout_s: float,
        *,
        initialising: bool = False,
    ) -> tuple[int, Mapping[str, str], bytes]:
        headers = {
            "Content-Type": JSON_MEDIA,
            "Accept": ACCEPT,
            **dict(self.headers),
        }
        if not initialising:
            headers["MCP-Protocol-Version"] = PROTOCOL_VERSION
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id

        req = urlrequest.Request(
            self.url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            return self.opener(req, timeout_s)
        except HTTPError as exc:
            # A 4xx/5xx is a server answer, not a broken connection, and its
            # status is the useful part.
            return exc.code, dict(getattr(exc, "headers", {}) or {}), b""
        except (URLError, TimeoutError, OSError) as exc:
            raise DocsUnavailable(
                f"documentation server unreachable: {type(exc).__name__}"
            ) from exc
        except Exception as exc:
            raise DocsUnavailable(
                f"documentation lookup failed: {type(exc).__name__}"
            ) from exc


# -- response decoding -------------------------------------------------------


def _reason(error: object) -> str:
    """A JSON-RPC error object rendered as one short line."""
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()[:200]
    return "unspecified"


def _header(headers: Mapping[str, str], name: str) -> str:
    """Case-insensitive lookup; HTTP header case is not guaranteed."""
    lowered = name.casefold()
    for key, value in headers.items():
        if key.casefold() == lowered:
            return str(value)
    return ""


def _decode(headers: Mapping[str, str], body: bytes) -> Mapping[str, Any]:
    """One JSON-RPC message from either response form.

    The specification lets a server answer a request with a single JSON object
    *or* with an SSE stream, and says a client must support both. The SSE branch
    takes the last ``data:`` frame that parses as a JSON-RPC message, which is
    the response the stream exists to deliver.
    """
    text = body.decode("utf-8", errors="replace")
    if SSE_MEDIA in _header(headers, "Content-Type"):
        message: Mapping[str, Any] | None = None
        for line in text.splitlines():
            if not line.startswith("data:"):
                continue
            try:
                candidate = json.loads(line[len("data:") :].strip())
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict) and "jsonrpc" in candidate:
                message = candidate
        if message is None:
            raise DocsUnavailable("documentation server sent no usable event")
        return message

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DocsUnavailable("documentation server returned invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise DocsUnavailable("documentation server returned an unusable message")
    return parsed


def _unwrap(result: Mapping[str, Any]) -> object:
    """The tool's payload, in whichever shape the server used.

    ``structuredContent`` when present, else the concatenated text blocks -- and
    if that text is itself JSON, the parsed value. Handing back both shapes keeps
    ``Context7Adapter``'s validation the single place that decides what is
    usable, rather than teaching this module what a library candidate looks like.
    """
    if result.get("isError"):
        raise DocsUnavailable("documentation server reported a tool error")

    structured = result.get("structuredContent")
    if isinstance(structured, (dict, list)):
        return structured

    blocks = result.get("content")
    if not isinstance(blocks, list):
        raise DocsUnavailable("documentation server returned no content")
    text = "\n".join(
        block["text"]
        for block in blocks
        if isinstance(block, dict) and isinstance(block.get("text"), str)
    )
    if not text.strip():
        raise DocsUnavailable("documentation server returned no content")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


__all__ = [
    "ACCEPT",
    "CLIENT_NAME",
    "PROTOCOL_VERSION",
    "McpHttpTransport",
    "Opener",
    "urlopen_adapter",
]
