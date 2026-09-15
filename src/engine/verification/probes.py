"""Closed registry of pure, deterministic standard-library predicates.

A probe exists to let the adjudicator *refute* a factual premise a judge
asserted -- never to establish one. It evaluates a registered predicate over a
literal argument and returns the answer together with the interpreter version
that produced it, because an address-classification answer is only ever true of
a specific interpreter (see the frozen adjudication spec's runtime-scope rule).

No model-supplied code is executed, ever. The judge names a registry key; the
function behind it is written here. An unregistered key, a bad argument or any
exception yields an unsuccessful result, which the caller must treat as
UNRESOLVED -- it may never suppress a finding.
"""

import ipaddress
import platform
from collections.abc import Callable
from dataclasses import dataclass

_IP_FLAGS: tuple[str, ...] = (
    "is_private",
    "is_loopback",
    "is_link_local",
    "is_reserved",
    "is_multicast",
    "is_unspecified",
)


def _ip_flag(attribute: str) -> Callable[[str], bool]:
    def check(argument: str) -> bool:
        return bool(getattr(ipaddress.ip_address(argument), attribute))

    return check


# Deliberately tiny. Every entry is a pure stdlib property read over a literal:
# no I/O, no network, no subprocess, no filesystem. Widening this beyond that
# shape requires its own design review, not a one-line addition here.
PROBE_REGISTRY: dict[str, Callable[[str], bool]] = {
    f"ipaddress.{flag}": _ip_flag(flag) for flag in _IP_FLAGS
}


@dataclass(frozen=True)
class ProbeResult:
    predicate: str
    argument: str
    ok: bool
    value: bool | None
    error: str
    interpreter_version: str


def run_probe(predicate: str, argument: str) -> ProbeResult:
    """Evaluate a registered predicate. Never raises."""
    version = platform.python_version()

    check = PROBE_REGISTRY.get(predicate)
    if check is None:
        return ProbeResult(
            predicate=predicate,
            argument=argument,
            ok=False,
            value=None,
            error=f"unknown predicate: {predicate!r}",
            interpreter_version=version,
        )

    try:
        value = check(argument)
    except Exception as exc:  # noqa: BLE001 -- a probe failure must never propagate
        return ProbeResult(
            predicate=predicate,
            argument=argument,
            ok=False,
            value=None,
            error=f"{type(exc).__name__}: {exc}",
            interpreter_version=version,
        )

    return ProbeResult(
        predicate=predicate,
        argument=argument,
        ok=True,
        value=value,
        error="",
        interpreter_version=version,
    )
