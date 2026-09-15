"""C7: the real MCP transport and its operator-owned configuration, offline.

The transport is real -- Streamable HTTP, the 2025-06-18 lifecycle, the actual
Context7 endpoint shape -- and no test opens a socket. Every one injects an
``opener``, which is the seam that makes full acceptance possible without a live
call.

What this suite protects:

    protocol    the headers, the lifecycle order and the session id are what the
                specification says, because a transport that is subtly wrong
                fails only in production
    closed      configuration fails safe: absent, disabled, malformed, unknown
                server or missing credential all yield no capability at all
    secrecy     a credential is named in config and never written down again
"""

import json
from pathlib import Path

import pytest

from engine.capabilities.errors import DocsUnavailable
from engine.capabilities.external.config import load_external_config
from engine.capabilities.external.transport import (
    ACCEPT,
    PROTOCOL_VERSION,
    McpHttpTransport,
)

ENDPOINT = "https://mcp.context7.com/mcp"


class FakeHttp:
    """Records requests and replays scripted responses. Opens no socket."""

    def __init__(self, *responses, content_type: str = "application/json"):  # type: ignore[no-untyped-def]
        self._responses = list(responses)
        self._content_type = content_type
        self.requests: list[dict] = []

    def __call__(self, req, timeout):  # type: ignore[no-untyped-def]
        body = json.loads(req.data.decode("utf-8")) if req.data else {}
        self.requests.append(
            {
                "url": req.full_url,
                "method": req.get_method(),
                "headers": {k.casefold(): v for k, v in req.headers.items()},
                "body": body,
                "timeout": timeout,
            }
        )
        if not self._responses:
            raise AssertionError(f"unscripted request: {body.get('method')}")
        status, headers, payload = self._responses.pop(0)
        if isinstance(payload, (dict, list)):
            payload = json.dumps(payload).encode("utf-8")
        # Per-response override, so a handshake can be JSON while the answer
        # streams -- which is exactly what a real server may do.
        media = headers.pop("__content_type__", self._content_type)
        return status, {"Content-Type": media, **headers}, payload


def ok(result: object, **headers: str):  # type: ignore[no-untyped-def]
    return (200, headers, {"jsonrpc": "2.0", "id": 1, "result": result})


def transport(*responses, **kwargs):  # type: ignore[no-untyped-def]
    http = FakeHttp(*responses, **kwargs)
    return McpHttpTransport(url=ENDPOINT, headers={"Authorization": "Bearer SECRET"}, opener=http), http


def text_result(payload: object):  # type: ignore[no-untyped-def]
    body = payload if isinstance(payload, str) else json.dumps(payload)
    return {"content": [{"type": "text", "text": body}]}


def handshake(session: str = "sess-1"):  # type: ignore[no-untyped-def]
    return [
        ok({"protocolVersion": PROTOCOL_VERSION}, **{"Mcp-Session-Id": session}),
        (202, {}, b""),
    ]


# -- protocol -----------------------------------------------------------------


def test_a_call_performs_the_specified_lifecycle_once() -> None:
    tr, http = transport(*handshake(), ok(text_result("DOCS")), ok(text_result("DOCS")))

    first = tr.call_tool("query-docs", {"libraryId": "/a/b", "query": "x"}, 5.0)
    second = tr.call_tool("query-docs", {"libraryId": "/a/b", "query": "y"}, 5.0)

    methods = [r["body"].get("method") for r in http.requests]
    assert methods[:3] == ["initialize", "notifications/initialized", "tools/call"]
    assert first == "DOCS"
    # The session is established once; a later lookup is a single round trip.
    assert len(http.requests) == 4
    assert second == "DOCS"


def test_every_request_carries_the_required_headers() -> None:
    tr, http = transport(*handshake(), ok(text_result("D")))

    tr.call_tool("query-docs", {}, 5.0)

    for record in http.requests:
        assert record["method"] == "POST"
        assert record["url"] == ENDPOINT
        assert record["headers"]["accept"] == ACCEPT
        assert record["headers"]["content-type"] == "application/json"


def test_the_session_id_is_echoed_on_every_later_request() -> None:
    tr, http = transport(*handshake("abc123"), ok(text_result("D")))

    tr.call_tool("query-docs", {}, 5.0)

    assert "mcp-session-id" not in http.requests[0]["headers"]  # none to send yet
    assert http.requests[1]["headers"]["mcp-session-id"] == "abc123"
    assert http.requests[2]["headers"]["mcp-session-id"] == "abc123"


def test_the_protocol_version_accompanies_post_initialisation_requests() -> None:
    tr, http = transport(*handshake(), ok(text_result("D")))

    tr.call_tool("query-docs", {}, 5.0)

    assert "mcp-protocol-version" not in http.requests[0]["headers"]
    assert http.requests[2]["headers"]["mcp-protocol-version"] == PROTOCOL_VERSION


def test_the_tool_name_and_arguments_are_sent_verbatim() -> None:
    tr, http = transport(*handshake(), ok(text_result("D")))

    tr.call_tool("resolve-library-id", {"libraryName": "pydantic", "query": "v"}, 5.0)

    params = http.requests[2]["body"]["params"]
    assert params == {
        "name": "resolve-library-id",
        "arguments": {"libraryName": "pydantic", "query": "v"},
    }


def test_the_caller_timeout_reaches_the_socket_layer() -> None:
    tr, http = transport(*handshake(), ok(text_result("D")))

    tr.call_tool("query-docs", {}, 3.5)

    assert all(record["timeout"] == 3.5 for record in http.requests)


def test_an_sse_response_is_decoded() -> None:
    """The specification lets a server answer with either form; a client must
    support both."""
    frame = (
        b"event: message\n"
        b'data: {"jsonrpc":"2.0","id":1,"result":'
        + json.dumps(text_result("STREAMED")).encode()
        + b"}\n\n"
    )
    http = FakeHttp(
        (200, {"Mcp-Session-Id": "s"}, {"jsonrpc": "2.0", "id": 1, "result": {}}),
        (202, {}, b""),
        (200, {"__content_type__": "text/event-stream"}, frame),
    )
    tr = McpHttpTransport(url=ENDPOINT, opener=http)

    assert tr.call_tool("query-docs", {}, 5.0) == "STREAMED"


def test_structured_content_is_preferred_over_text() -> None:
    tr, _ = transport(*handshake(), ok({"structuredContent": [{"id": "/a/b"}]}))

    assert tr.call_tool("resolve-library-id", {}, 5.0) == [{"id": "/a/b"}]


def test_json_text_content_is_parsed() -> None:
    tr, _ = transport(*handshake(), ok(text_result([{"id": "/a/b"}])))

    assert tr.call_tool("resolve-library-id", {}, 5.0) == [{"id": "/a/b"}]


# -- faults are one outcome ---------------------------------------------------


@pytest.mark.parametrize(
    "response",
    [
        (500, {}, b"boom"),
        (400, {}, b""),
        (200, {}, b"not json"),
        (200, {}, {"jsonrpc": "2.0", "id": 1, "error": {"code": -1, "message": "nope"}}),
        (200, {}, {"jsonrpc": "2.0", "id": 1, "result": {"isError": True, "content": []}}),
        (200, {}, {"jsonrpc": "2.0", "id": 1, "result": {"content": []}}),
        (200, {}, {"jsonrpc": "2.0", "id": 1}),
    ],
)
def test_every_server_fault_becomes_one_outcome(response: tuple) -> None:
    tr, _ = transport(*handshake(), response)

    with pytest.raises(DocsUnavailable):
        tr.call_tool("query-docs", {}, 5.0)


def test_an_unreachable_server_becomes_one_outcome() -> None:
    def explode(req, timeout):  # type: ignore[no-untyped-def]
        raise OSError("no route to host")

    tr = McpHttpTransport(url=ENDPOINT, opener=explode)

    with pytest.raises(DocsUnavailable) as excinfo:
        tr.call_tool("query-docs", {}, 5.0)

    assert "unreachable" in str(excinfo.value)


# -- configuration fails closed ----------------------------------------------


def write_config(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "capabilities.toml"
    path.write_text(body, encoding="utf-8")
    return path


FULL = """
[external.context7]
enabled = true
server = "context7"
timeout_seconds = 7.0
max_calls = 2
max_chars_per_call = 100
max_chars_total = 150

[mcp_servers.context7]
url = "https://mcp.context7.com/mcp"
"""


def test_a_complete_configuration_admits_the_capability(tmp_path: Path) -> None:
    config = load_external_config(write_config(tmp_path, FULL))

    assert config.enabled
    capability = config.policy.check(capability="context7", operation="lookup_docs")
    assert capability.max_calls == 2
    assert capability.max_chars_total == 150
    assert capability.timeout_seconds == 7.0


@pytest.mark.parametrize(
    "body",
    [
        "",
        "[external.context7]\nenabled = false\n",
        "[external.context7]\nenabled = true\nserver = \"context7\"\n",  # no server table
        FULL.replace('server = "context7"', 'server = "typo"'),
        FULL.replace("https://mcp.context7.com/mcp", "http://insecure.example/mcp"),
        "this is not toml [[[",
    ],
)
def test_an_incomplete_or_disabled_configuration_admits_nothing(
    tmp_path: Path, body: str
) -> None:
    config = load_external_config(write_config(tmp_path, body))

    assert config.enabled is False
    assert config.docs is None
    assert config.policy.empty


def test_a_missing_file_admits_nothing(tmp_path: Path) -> None:
    assert load_external_config(tmp_path / "absent.toml").enabled is False
    assert load_external_config(None).enabled is False


def test_a_named_but_absent_credential_admits_nothing(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Admitting it would produce a run that fails on its first lookup, which is
    worse than not offering the capability at all."""
    monkeypatch.delenv("C7_TEST_KEY", raising=False)
    body = FULL + '\napi_key_env = "C7_TEST_KEY"\n'

    assert load_external_config(write_config(tmp_path, body)).enabled is False


def test_a_credential_is_read_from_the_environment_and_never_stored(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("C7_TEST_KEY", "super-secret-value")
    body = FULL + '\napi_key_env = "C7_TEST_KEY"\n'

    config = load_external_config(write_config(tmp_path, body))

    assert config.enabled
    # The secret is in the request header and nowhere else a report could reach.
    assert "super-secret-value" not in write_config(tmp_path, body).read_text(encoding="utf-8")
    assert "super-secret-value" not in repr(config.policy)


def test_the_configured_url_is_never_reachable_from_the_policy(tmp_path: Path) -> None:
    """A model that somehow read the policy still learns no endpoint: the URL
    lives in the transport, which the policy does not reference."""
    config = load_external_config(write_config(tmp_path, FULL))

    assert "mcp.context7.com" not in repr(config.policy)
    assert "url" not in repr(config.policy).casefold()
