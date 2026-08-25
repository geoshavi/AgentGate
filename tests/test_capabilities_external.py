"""C6: the bounded external-capability layer, entirely offline.

No network, no MCP process, no SDK. Every provider interaction goes through a
scripted fake, which is the point: the transport arrives in C7 and everything
that decides what may leave this machine must already be proven without it.

Four properties carry the phase:

    policy      what may be called at all, and by whom -- never the model
    ledger      what a call costs, reserved before the call and recorded after
                truncation, so an over-budget response cannot reach context
    vocabulary  the port names one read operation, so arbitrary MCP is not
                refused so much as unsayable
    authority   returned documentation is untrusted text. It may inform; it may
                not change a tool, a policy, or a frozen command.
"""

import pytest

from engine.capabilities.errors import DocsUnavailable, EgressDenied
from engine.capabilities.external import (
    CONTEXT7_PROVIDER,
    MAX_LIBRARY_CHARS,
    MAX_TOPIC_CHARS,
    QUERY_TOOL,
    RESOLVE_TOOL,
    Context7Adapter,
    DocsAnswer,
    DocsPort,
    EgressLedger,
    EgressPolicy,
    ExternalCapability,
    is_context7_id,
)

LOOKUP = "lookup_docs"


def capability(**overrides: object) -> ExternalCapability:
    base = {
        "name": CONTEXT7_PROVIDER,
        "operations": frozenset({LOOKUP}),
        "max_calls": 5,
        "max_chars_per_call": 6_000,
        "max_chars_total": 20_000,
        "timeout_seconds": 10.0,
    }
    base.update(overrides)
    return ExternalCapability(**base)  # type: ignore[arg-type]


def policy(**overrides: object) -> EgressPolicy:
    return EgressPolicy.of(capability(**overrides))


class FakeCaller:
    """A scripted stand-in for whatever C7 puts on the wire.

    Records every hop so a test can assert the exact tool names and argument
    keys the adapter used -- the mapping is the contract with the provider, and
    a silent rename there would be invisible from the outside.
    """

    def __init__(self, *, resolve: object = None, query: object = None, raises: Exception | None = None):
        self._resolve = resolve
        self._query = query
        self._raises = raises
        self.calls: list[tuple[str, dict[str, object], float]] = []

    def call_tool(self, name: str, arguments: dict[str, object], timeout_s: float) -> object:
        self.calls.append((name, dict(arguments), timeout_s))
        if self._raises is not None:
            raise self._raises
        return self._resolve if name == RESOLVE_TOOL else self._query


def adapter(**kwargs: object) -> tuple[Context7Adapter, FakeCaller]:
    caller = FakeCaller(**kwargs)  # type: ignore[arg-type]
    return Context7Adapter(caller), caller


def answer_for(library: str = "pydantic", topic: str = "validators", **kwargs: object) -> DocsAnswer:
    port, _ = adapter(
        resolve=[{"id": "/pydantic/pydantic"}], query={"content": "DOCS BODY"}, **kwargs
    )
    return port.lookup(library=library, topic=topic, timeout_s=5.0, max_chars=1_000)


# -- policy -------------------------------------------------------------------


def test_an_empty_policy_admits_nothing() -> None:
    empty = EgressPolicy.none()

    assert empty.empty
    with pytest.raises(EgressDenied):
        empty.check(capability=CONTEXT7_PROVIDER, operation=LOOKUP)


def test_a_known_capability_and_operation_is_admitted() -> None:
    admitted = policy().check(capability=CONTEXT7_PROVIDER, operation=LOOKUP)

    assert admitted.name == CONTEXT7_PROVIDER
    assert admitted.max_calls == 5


def test_an_unknown_capability_is_denied() -> None:
    with pytest.raises(EgressDenied) as excinfo:
        policy().check(capability="some-other-server", operation=LOOKUP)

    assert "some-other-server" in str(excinfo.value)


def test_an_unknown_operation_is_denied() -> None:
    with pytest.raises(EgressDenied):
        policy().check(capability=CONTEXT7_PROVIDER, operation="write_docs")


def test_the_policy_is_immutable() -> None:
    live = policy()

    with pytest.raises((AttributeError, TypeError)):
        live.capabilities = {}  # type: ignore[misc]
    with pytest.raises(TypeError):
        live.capabilities["evil"] = capability()  # type: ignore[index]
    with pytest.raises((AttributeError, TypeError)):
        live.check(capability=CONTEXT7_PROVIDER, operation=LOOKUP).max_calls = 999  # type: ignore[misc]


# -- ledger -------------------------------------------------------------------


def test_begin_call_returns_the_per_call_allowance() -> None:
    ledger = EgressLedger()

    assert ledger.begin_call(capability()) == 6_000


def test_the_allowance_shrinks_to_the_remaining_total() -> None:
    """The per-call cap is not the only bound: once most of the total is spent,
    the next call may accept far less than max_chars_per_call."""
    cap = capability(max_chars_per_call=6_000, max_chars_total=7_000)
    ledger = EgressLedger()

    ledger.begin_call(cap)
    ledger.record_chars(6_000)

    assert ledger.begin_call(cap) == 1_000


def test_the_call_cap_is_enforced_before_the_adapter() -> None:
    cap = capability(max_calls=1)
    ledger = EgressLedger()
    ledger.begin_call(cap)

    with pytest.raises(EgressDenied) as excinfo:
        ledger.begin_call(cap)

    assert "1" in str(excinfo.value)


def test_an_exhausted_total_is_denied_before_the_adapter() -> None:
    cap = capability(max_chars_total=100)
    ledger = EgressLedger()
    ledger.begin_call(cap)
    ledger.record_chars(100)

    with pytest.raises(EgressDenied):
        ledger.begin_call(cap)


def test_a_failed_call_keeps_its_slot_and_records_no_chars() -> None:
    """A timeout consumed real budget and latency. Refunding it would let a
    flapping provider be retried without bound."""
    cap = capability()
    ledger = EgressLedger()

    ledger.begin_call(cap)
    ledger.fail_call("timed out")

    assert ledger.calls == 1
    assert ledger.chars == 0
    assert ledger.failures == ("timed out",)


def test_only_accepted_characters_are_recorded() -> None:
    """Post-truncation, never what the provider sent: the ledger measures what
    entered the model's context."""
    ledger = EgressLedger()
    ledger.begin_call(capability())

    ledger.record_chars(120)

    assert ledger.chars == 120


def test_the_ledger_is_per_session_not_global() -> None:
    cap = capability(max_calls=1)
    first, second = EgressLedger(), EgressLedger()

    first.begin_call(cap)

    assert second.begin_call(cap) == cap.max_chars_per_call


# -- the port's vocabulary ----------------------------------------------------


def test_the_port_names_exactly_one_read_operation() -> None:
    """Arbitrary MCP is not refused here so much as unsayable: there is no verb
    for it in the vocabulary an agent-side module is given."""
    members = {name for name in dir(DocsPort) if not name.startswith("_")}

    assert members == {"lookup"}
    for forbidden in ("execute", "fetch", "fetch_url", "call_tool", "list_servers", "write", "upload"):
        assert forbidden not in members


def test_a_docs_answer_is_immutable() -> None:
    answer = answer_for()

    with pytest.raises((AttributeError, TypeError)):
        answer.content = "rewritten"  # type: ignore[misc]


# -- context7 mapping ---------------------------------------------------------


def test_a_bare_name_resolves_then_queries() -> None:
    port, caller = adapter(resolve=[{"id": "/pydantic/pydantic"}], query={"content": "DOCS"})

    result = port.lookup(library="pydantic", topic="validators", timeout_s=5.0, max_chars=100)

    assert [name for name, _, _ in caller.calls] == [RESOLVE_TOOL, QUERY_TOOL]
    resolve_args = caller.calls[0][1]
    assert resolve_args == {"libraryName": "pydantic", "query": "validators"}
    query_args = caller.calls[1][1]
    assert query_args == {"libraryId": "/pydantic/pydantic", "query": "validators"}
    assert result.resolved_id == "/pydantic/pydantic"
    assert result.content == "DOCS"
    assert result.source == CONTEXT7_PROVIDER


@pytest.mark.parametrize("library", ["/mongodb/docs", "/vercel/next.js", "/org/project/v2.1"])
def test_a_context7_id_skips_the_resolve_hop(library: str) -> None:
    port, caller = adapter(query={"content": "DOCS"})

    result = port.lookup(library=library, topic="routing", timeout_s=5.0, max_chars=100)

    assert [name for name, _, _ in caller.calls] == [QUERY_TOOL]
    assert caller.calls[0][1] == {"libraryId": library, "query": "routing"}
    assert result.resolved_id == library


@pytest.mark.parametrize(
    "value",
    ["pydantic", "/onlyone", "org/project", "//", "/org/", "/org/project/v1/extra", "/org/pro ject"],
)
def test_only_a_well_formed_id_skips_resolution(value: str) -> None:
    assert is_context7_id(value) is False


def test_the_first_structurally_valid_candidate_wins() -> None:
    """Deterministic and documented: provider order is the ranking, and this
    layer only filters out candidates that are not usable ids. It does not
    re-rank, because the resolve hop exists to do that."""
    port, _ = adapter(
        resolve=[
            {"id": "not-an-id"},
            {"id": "/first/valid"},
            {"id": "/second/valid"},
        ],
        query={"content": "DOCS"},
    )

    assert port.lookup(library="x", topic="y", timeout_s=5.0, max_chars=100).resolved_id == "/first/valid"


@pytest.mark.parametrize(
    "resolve",
    [
        [],
        [{"id": "not-an-id"}],
        [{"no_id_key": "/a/b"}],
        ["a bare string"],
        {"unexpected": "shape"},
        None,
        42,
    ],
)
def test_an_unusable_resolver_response_is_a_lookup_failure(resolve: object) -> None:
    port, caller = adapter(resolve=resolve, query={"content": "DOCS"})

    with pytest.raises(DocsUnavailable):
        port.lookup(library="pydantic", topic="v", timeout_s=5.0, max_chars=100)

    # It never guessed an id and never made the second hop.
    assert [name for name, _, _ in caller.calls] == [RESOLVE_TOOL]


@pytest.mark.parametrize("query", [None, 42, {}, {"content": 5}, {"other": "x"}, []])
def test_an_unusable_docs_response_is_a_lookup_failure(query: object) -> None:
    port, _ = adapter(resolve=[{"id": "/a/b"}], query=query)

    with pytest.raises(DocsUnavailable):
        port.lookup(library="a", topic="b", timeout_s=5.0, max_chars=100)


def test_a_provider_exception_becomes_a_lookup_failure() -> None:
    port, _ = adapter(raises=RuntimeError("socket exploded"))

    with pytest.raises(DocsUnavailable):
        port.lookup(library="a", topic="b", timeout_s=5.0, max_chars=100)


def test_a_dict_shaped_resolver_response_is_accepted() -> None:
    port, _ = adapter(resolve={"results": [{"id": "/a/b"}]}, query={"content": "D"})

    assert port.lookup(library="a", topic="b", timeout_s=5.0, max_chars=10).resolved_id == "/a/b"


def test_a_plain_string_docs_response_is_accepted() -> None:
    port, _ = adapter(resolve=[{"id": "/a/b"}], query="PLAIN DOCS")

    assert port.lookup(library="a", topic="b", timeout_s=5.0, max_chars=100).content == "PLAIN DOCS"


# -- bounds -------------------------------------------------------------------


def test_the_adapter_truncates_an_oversized_response() -> None:
    """The provider has no size parameter AgentGate can trust, so bounding is
    entirely this side's job."""
    port, _ = adapter(resolve=[{"id": "/a/b"}], query={"content": "x" * 5_000})

    result = port.lookup(library="a", topic="b", timeout_s=5.0, max_chars=100)

    assert len(result.content) == 100
    assert result.truncated is True


def test_a_provider_ignoring_max_chars_still_cannot_overrun() -> None:
    port, caller = adapter(resolve=[{"id": "/a/b"}], query={"content": "y" * 100_000})

    result = port.lookup(library="a", topic="b", timeout_s=5.0, max_chars=250)

    assert len(result.content) == 250
    # max_chars is a hint to the provider; the guarantee is the truncation above.
    assert all("max_chars" not in args for _, args, _ in caller.calls)


@pytest.mark.parametrize("library,topic", [("", "topic"), ("lib", ""), ("   ", "t"), ("l", "  ")])
def test_empty_input_is_refused_before_any_hop(library: str, topic: str) -> None:
    port, caller = adapter(resolve=[{"id": "/a/b"}], query={"content": "D"})

    with pytest.raises(DocsUnavailable):
        port.lookup(library=library, topic=topic, timeout_s=5.0, max_chars=100)

    assert caller.calls == []


def test_oversized_input_is_refused_before_any_hop() -> None:
    port, caller = adapter(resolve=[{"id": "/a/b"}], query={"content": "D"})

    with pytest.raises(DocsUnavailable):
        port.lookup(library="l" * (MAX_LIBRARY_CHARS + 1), topic="t", timeout_s=5.0, max_chars=100)
    with pytest.raises(DocsUnavailable):
        port.lookup(library="l", topic="t" * (MAX_TOPIC_CHARS + 1), timeout_s=5.0, max_chars=100)

    assert caller.calls == []


@pytest.mark.parametrize("bad", ["lib\x00rary", "lib\nrary", "lib\rrary", "lib\x1brary"])
def test_control_characters_are_refused_before_any_hop(bad: str) -> None:
    port, caller = adapter(resolve=[{"id": "/a/b"}], query={"content": "D"})

    with pytest.raises(DocsUnavailable):
        port.lookup(library=bad, topic="t", timeout_s=5.0, max_chars=100)

    assert caller.calls == []


def test_a_zero_allowance_is_refused_before_any_hop() -> None:
    port, caller = adapter(resolve=[{"id": "/a/b"}], query={"content": "D"})

    with pytest.raises(DocsUnavailable):
        port.lookup(library="a", topic="b", timeout_s=5.0, max_chars=0)

    assert caller.calls == []


# -- timeout ------------------------------------------------------------------


def test_the_timeout_covers_both_hops_not_each() -> None:
    """One wrapper call, one budget. The second hop gets what the first left,
    which is the seam C7 needs to enforce a real wall clock."""
    ticks = iter([0.0, 0.0, 3.0, 3.0, 3.0])
    port, caller = adapter(resolve=[{"id": "/a/b"}], query={"content": "D"})
    port = Context7Adapter(caller, clock=lambda: next(ticks))

    port.lookup(library="a", topic="b", timeout_s=10.0, max_chars=100)

    first_timeout = caller.calls[0][2]
    second_timeout = caller.calls[1][2]
    assert first_timeout == 10.0
    assert second_timeout == pytest.approx(7.0)
    assert second_timeout < first_timeout


def test_a_budget_spent_by_the_first_hop_fails_before_the_second() -> None:
    ticks = iter([0.0, 0.0, 99.0, 99.0])
    _, caller = adapter(resolve=[{"id": "/a/b"}], query={"content": "D"})
    port = Context7Adapter(caller, clock=lambda: next(ticks))

    with pytest.raises(DocsUnavailable) as excinfo:
        port.lookup(library="a", topic="b", timeout_s=10.0, max_chars=100)

    assert "timed out" in str(excinfo.value).lower()
    assert [name for name, _, _ in caller.calls] == [RESOLVE_TOOL]


# -- no SDK, no transport, no network ----------------------------------------


def test_the_external_package_imports_no_transport_or_sdk() -> None:
    """C6 ships the boundary, not the wire. A network import here would mean the
    thing that decides what may leave the machine was written after the thing
    that leaves it.

    Checked over the import graph rather than the raw text: a prose mention of
    "subprocess" while explaining what CommandPolicy governs is not an import,
    and a text scan cannot tell the two apart.
    """
    import ast
    from pathlib import Path

    import engine.capabilities.external as pkg

    banned = {"socket", "ssl", "http", "httpx", "requests", "urllib", "subprocess", "mcp", "asyncio"}
    violations: list[str] = []
    for path in sorted(Path(pkg.__path__[0]).glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            else:
                continue
            for name in names:
                if name.split(".")[0] in banned:
                    violations.append(f"{path.name}: imports {name!r}")

    assert not violations, "transport reached the external capability core:\n" + "\n".join(violations)
