"""Operator-owned configuration: the only thing that can admit an egress.

Everything a model must not choose lives here -- which server, which URL, which
credential, which budgets -- and it is read from a file outside the workspace,
before any session exists. A model cannot write this file (it is not in the
workspace), cannot name it, and cannot reach anything it produces.

The default posture is closed. A missing file, ``enabled = false``, a malformed
document, an unknown server key, or a missing credential all produce an **empty**
``EgressPolicy`` and no port, so ``build_capabilities`` registers no tool and the
model never learns one might have existed. A configuration mistake therefore
fails safe rather than failing open.

Credentials are named, never carried: the config holds an environment variable
*name*, and the value is read at construction and put straight into a request
header. It is never logged, never reported, and never written back.
"""

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from engine.capabilities.external.context7 import CONTEXT7_PROVIDER, Context7Adapter
from engine.capabilities.external.policy import EgressPolicy, ExternalCapability
from engine.capabilities.external.port import DocsPort
from engine.capabilities.external.transport import McpHttpTransport, Opener, urlopen_adapter

DOCS_LOOKUP = "lookup_docs"
MAX_CONFIG_BYTES = 64_000

DEFAULTS = {
    "timeout_seconds": 10.0,
    "max_calls": 5,
    "max_chars_per_call": 6_000,
    "max_chars_total": 20_000,
}


@dataclass(frozen=True)
class ExternalConfig:
    """What the operator admitted, ready to hand to ``build_capabilities``.

    ``docs`` is None whenever the capability is not fully configured, and
    ``policy`` is then empty. The two always agree, so a caller cannot end up
    with a port it may not use or a permission with nothing behind it.
    """

    policy: EgressPolicy = field(default_factory=EgressPolicy.none)
    docs: DocsPort | None = None

    @property
    def enabled(self) -> bool:
        return self.docs is not None and not self.policy.empty


def load_external_config(path: Path | str | None, *, opener: Opener = urlopen_adapter) -> ExternalConfig:
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

    section = _mapping(_mapping(data.get("external")).get(CONTEXT7_PROVIDER))
    if not section.get("enabled"):
        return ExternalConfig()

    # `server` is a key into the operator's own server table, never a URL: a URL
    # in this field would be one edit away from a URL the model could influence.
    server = _mapping(data.get("mcp_servers")).get(str(section.get("server", "")))
    url = _mapping(server).get("url")
    if not isinstance(url, str) or not url.startswith("https://"):
        return ExternalConfig()

    headers: dict[str, str] = {}
    key_var = _mapping(server).get("api_key_env")
    if isinstance(key_var, str) and key_var:
        secret = os.environ.get(key_var, "")
        if not secret:
            # Named but absent: admitting the capability would produce a run that
            # fails on its first lookup, which is worse than not offering it.
            return ExternalConfig()
        headers["Authorization"] = f"Bearer {secret}"

    capability = ExternalCapability(
        name=CONTEXT7_PROVIDER,
        operations=frozenset({DOCS_LOOKUP}),
        max_calls=_int(section, "max_calls"),
        max_chars_per_call=_int(section, "max_chars_per_call"),
        max_chars_total=_int(section, "max_chars_total"),
        timeout_seconds=_float(section, "timeout_seconds"),
    )
    transport = McpHttpTransport(url=url, headers=headers, opener=opener)
    return ExternalConfig(policy=EgressPolicy.of(capability), docs=Context7Adapter(transport))


def _mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


def _int(section: dict[str, object], key: str) -> int:
    value = section.get(key, DEFAULTS[key])
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else int(DEFAULTS[key])  # type: ignore[arg-type]


def _float(section: dict[str, object], key: str) -> float:
    value = section.get(key, DEFAULTS[key])
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else float(DEFAULTS[key])  # type: ignore[arg-type]


__all__ = ["DEFAULTS", "MAX_CONFIG_BYTES", "ExternalConfig", "load_external_config"]
