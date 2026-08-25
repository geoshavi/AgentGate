"""Operator-owned configuration: the only thing that can admit an egress.

Everything a model must not choose lives here -- which server, which URL, which
credential, which repositories, which budgets -- and it is read from a file
outside the workspace, before any session exists. A model cannot write this file
(it is not in the workspace), cannot name it, and cannot reach anything it
produces.

The default posture is closed, per capability and independently. A missing file,
``enabled = false``, a malformed document, an unknown server key, a missing
credential, or -- for GitHub -- an empty repository allowlist all produce **no
port and no capability row**, so ``build_capabilities`` registers no tool and the
model never learns one might have existed. A configuration mistake in one
capability leaves the other exactly as it was.

Credentials are named, never carried: the config holds an environment variable
*name*, and the value is read at construction and put straight into a request
header. It is never logged, never reported, and never written back.

A worked example::

    [mcp_servers.context7]
    url = "https://mcp.context7.com/mcp"
    api_key_env = "CONTEXT7_API_KEY"

    [mcp_servers.github]
    # The official server's published read-only endpoint. Belt to the
    # allowlist's braces: the tool table cannot name a write tool, and this
    # endpoint would refuse one anyway.
    url = "https://api.githubcopilot.com/mcp/readonly"
    api_key_env = "GITHUB_MCP_PAT"

    [external.context7]
    enabled = true
    server = "context7"

    [external.github]
    enabled = true
    server = "github"
    repos = ["octocat/hello-world"]
"""

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from engine.capabilities.external.context7 import CONTEXT7_PROVIDER, Context7Adapter
from engine.capabilities.external.github import (
    GITHUB_LOOKUP,
    GITHUB_PROVIDER,
    GitHubAdapter,
    GitHubPort,
)
from engine.capabilities.external.policy import EgressPolicy, ExternalCapability
from engine.capabilities.external.port import DocsPort
from engine.capabilities.external.transport import McpHttpTransport, Opener, urlopen_adapter

DOCS_LOOKUP = "lookup_docs"
MAX_CONFIG_BYTES = 64_000

# Shared by both capabilities. One set of budget defaults rather than one per
# provider: the numbers answer "how much external context may a session take
# on", which is a property of the session, not of who answers.
DEFAULTS = {
    "timeout_seconds": 10.0,
    "max_calls": 5,
    "max_chars_per_call": 6_000,
    "max_chars_total": 20_000,
}


@dataclass(frozen=True)
class ExternalConfig:
    """What the operator admitted, ready to hand to ``build_capabilities``.

    A port is None whenever its capability is not fully configured, and
    ``policy`` then carries no row for it. The two always agree, so a caller
    cannot end up with a port it may not use or a permission with nothing behind
    it.
    """

    policy: EgressPolicy = field(default_factory=EgressPolicy.none)
    docs: DocsPort | None = None
    github: GitHubPort | None = None

    @property
    def enabled(self) -> bool:
        return (self.docs is not None or self.github is not None) and not self.policy.empty


def load_external_config(
    path: Path | str | None, *, opener: Opener = urlopen_adapter
) -> ExternalConfig:
    """Read ``capabilities.toml``, or return the closed default.

    Never raises. Every failure -- absent, oversized, unparsable, disabled,
    incomplete -- is the same closed posture, because an operator who
    misconfigured this should get a run with no external capability rather than
    a crashed run or, worse, an unintended one.
    """
    if path is None:
        return ExternalConfig()
    file = Path(path)
    try:
        if not file.is_file() or file.stat().st_size > MAX_CONFIG_BYTES:
            return ExternalConfig()
        data = tomllib.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError, tomllib.TOMLDecodeError):
        return ExternalConfig()

    external = _mapping(data.get("external"))
    servers = _mapping(data.get("mcp_servers"))

    admitted_docs = _docs(external, servers, opener)
    admitted_github = _github(external, servers, opener)

    rows = [row for row, _ in (admitted_docs, admitted_github) if row is not None]
    if not rows:
        return ExternalConfig()
    return ExternalConfig(
        policy=EgressPolicy.of(*rows),
        docs=admitted_docs[1],
        github=admitted_github[1],
    )


def _docs(
    external: dict[str, object], servers: dict[str, object], opener: Opener
) -> tuple[ExternalCapability | None, DocsPort | None]:
    section = _mapping(external.get(CONTEXT7_PROVIDER))
    if not section.get("enabled"):
        return None, None
    endpoint = _endpoint(section, servers)
    if endpoint is None:
        return None, None
    url, headers = endpoint
    row = _capability(section, CONTEXT7_PROVIDER, DOCS_LOOKUP)
    return row, Context7Adapter(McpHttpTransport(url=url, headers=headers, opener=opener))


def _github(
    external: dict[str, object], servers: dict[str, object], opener: Opener
) -> tuple[ExternalCapability | None, GitHubPort | None]:
    """The GitHub capability, or nothing.

    ``repos`` is required and must yield at least one well-formed ``owner/name``.
    The credential is the operator's, so the set of repositories it may be aimed
    at is operator business too -- and an allowlist that admitted everything by
    default would be exactly the failure this file exists to prevent. The
    adapter is the one place that decides what a well-formed slug is, so the
    check here is "did the adapter keep any", not a second pattern.
    """
    section = _mapping(external.get(GITHUB_PROVIDER))
    if not section.get("enabled"):
        return None, None
    endpoint = _endpoint(section, servers)
    if endpoint is None:
        return None, None
    url, headers = endpoint

    listed = section.get("repos")
    repos = [item for item in listed if isinstance(item, str)] if isinstance(listed, list) else []
    adapter = GitHubAdapter(
        McpHttpTransport(url=url, headers=headers, opener=opener), repos=repos
    )
    if not adapter.repos:
        return None, None
    return _capability(section, GITHUB_PROVIDER, GITHUB_LOOKUP), adapter


def _endpoint(
    section: dict[str, object], servers: dict[str, object]
) -> tuple[str, dict[str, str]] | None:
    """The operator's URL and auth header for this capability, or nothing.

    ``server`` stays a key into the operator's own server table rather than a
    URL: a URL in that field would be one edit away from a URL something else
    could influence.
    """
    server = _mapping(servers.get(str(section.get("server", ""))))
    url = server.get("url")
    if not isinstance(url, str) or not url.startswith("https://"):
        return None

    headers: dict[str, str] = {}
    key_var = server.get("api_key_env")
    if isinstance(key_var, str) and key_var:
        secret = os.environ.get(key_var, "")
        if not secret:
            # Named but absent: admitting the capability would produce a run that
            # fails on its first lookup, which is worse than not offering it.
            return None
        headers["Authorization"] = f"Bearer {secret}"
    return url, headers


def _capability(section: dict[str, object], name: str, operation: str) -> ExternalCapability:
    return ExternalCapability(
        name=name,
        operations=frozenset({operation}),
        max_calls=_int(section, "max_calls"),
        max_chars_per_call=_int(section, "max_chars_per_call"),
        max_chars_total=_int(section, "max_chars_total"),
        timeout_seconds=_float(section, "timeout_seconds"),
    )


def _mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


def _int(section: dict[str, object], key: str) -> int:
    value = section.get(key, DEFAULTS[key])
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else int(DEFAULTS[key])  # type: ignore[arg-type]


def _float(section: dict[str, object], key: str) -> float:
    value = section.get(key, DEFAULTS[key])
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else float(DEFAULTS[key])  # type: ignore[arg-type]


__all__ = ["DEFAULTS", "MAX_CONFIG_BYTES", "ExternalConfig", "load_external_config"]
