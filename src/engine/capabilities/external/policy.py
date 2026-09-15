"""What may leave this machine, and what one departure costs.

``CommandPolicy`` governs subprocesses and does not reach an in-process network
call, so an external capability needs its own boundary. Rather than bolt limits
onto one provider, this is a small general one with ``CommandPolicy``'s shape and
idioms: ``check()`` raises on violation and returns the permitted thing, so the
two read the same way and a reviewer's intuition transfers.

The split is deliberate and mirrors ``Limits`` versus ``Usage``:

    EgressPolicy   the rules. Frozen, built from operator configuration, shared.
    EgressLedger   the consumption. Mutable, one per session, never shared.

**Deliberately not a framework.** For now the policy admits one capability with
one operation. It exists so the *second* external capability is a configuration
entry rather than a second security system -- which is the failure this module is
here to prevent -- and it gains features when a second real capability arrives.

Nothing a model, a skill or a detection produces can reach any of this. The
policy is frozen, it is built before a session exists, and no tool takes a
capability or operation name as an argument.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from engine.capabilities.errors import EgressDenied


@dataclass(frozen=True)
class ExternalCapability:
    """One admitted external capability and everything it is allowed to spend.

    ``max_chars_per_call`` bounds a single answer; ``max_chars_total`` bounds the
    session. Both are needed: the first stops one enormous response, the second
    stops many ordinary ones, and neither implies the other.
    """

    name: str
    operations: frozenset[str]
    max_calls: int
    max_chars_per_call: int
    max_chars_total: int
    timeout_seconds: float

    def permits(self, operation: str) -> bool:
        return operation in self.operations


@dataclass(frozen=True)
class EgressPolicy:
    """The allowlist. Empty means no external capability exists at all."""

    capabilities: Mapping[str, ExternalCapability] = field(default_factory=lambda: MappingProxyType({}))

    @classmethod
    def none(cls) -> "EgressPolicy":
        """The default posture: nothing admitted."""
        return cls()

    @classmethod
    def of(cls, *capabilities: ExternalCapability) -> "EgressPolicy":
        return cls(MappingProxyType({cap.name: cap for cap in capabilities}))

    @property
    def empty(self) -> bool:
        return not self.capabilities

    def admits(self, capability: str, operation: str) -> bool:
        """Non-raising form, for deciding whether to register a tool at all.

        Absence is the safer interface: a capability that is not admitted should
        produce no tool, rather than a tool that always answers "unavailable".
        """
        found = self.capabilities.get(capability)
        return found is not None and found.permits(operation)

    def check(self, *, capability: str, operation: str) -> ExternalCapability:
        """Authorise one operation, or refuse.

        Raises:
            EgressDenied: unknown capability, or an operation that capability
                does not admit. The message names what *is* admitted so an
                operator reading a log can see the gap.
        """
        found = self.capabilities.get(capability)
        if found is None:
            raise EgressDenied(
                f"external capability {capability!r} is not admitted; "
                f"admitted: {sorted(self.capabilities) or 'none'}"
            )
        if not found.permits(operation):
            raise EgressDenied(
                f"capability {capability!r} does not admit operation {operation!r}; "
                f"admitted operations: {sorted(found.operations)}"
            )
        return found


class EgressLedger:
    """One session's external spend. Mutable, and never shared between sessions.

    The ordering is the whole design, because a response's size is unknown until
    it arrives:

        1. ``begin_call``   reserves the slot and returns the allowance for THIS
                            call, computed from what is left *before* the call
        2. the adapter runs
        3. the caller truncates to that allowance
        4. ``record_chars`` records what was actually accepted

    Step 4 takes the post-truncation count, never what the provider sent: the
    ledger measures what entered the model's context, which is the thing the
    budget exists to bound.

    A failed call keeps its slot. Refunding one would let a flapping provider be
    retried without bound, and the latency and connection were spent either way.
    """

    def __init__(self) -> None:
        self._calls = 0
        self._chars = 0
        self._failures: list[str] = []

    @property
    def calls(self) -> int:
        return self._calls

    @property
    def chars(self) -> int:
        """Characters accepted into context, after truncation."""
        return self._chars

    @property
    def failures(self) -> tuple[str, ...]:
        return tuple(self._failures)

    def begin_call(self, capability: ExternalCapability) -> int:
        """Reserve a call slot and return this call's character allowance.

        Raises:
            EgressDenied: the call cap is spent, or nothing of the total budget
                remains. Raised *before* the adapter runs, so an exhausted budget
                costs no latency and no provider round trip.
        """
        if self._calls >= capability.max_calls:
            raise EgressDenied(
                f"external capability budget exhausted "
                f"({capability.max_calls} call(s) for {capability.name!r})"
            )
        allowance = min(capability.max_chars_per_call, capability.max_chars_total - self._chars)
        if allowance <= 0:
            raise EgressDenied(
                f"external context budget exhausted "
                f"({capability.max_chars_total} chars for {capability.name!r})"
            )
        self._calls += 1
        return allowance

    def record_chars(self, accepted: int) -> None:
        """Record characters accepted into context. Post-truncation only."""
        self._chars += max(0, accepted)

    def fail_call(self, reason: str) -> None:
        """Note that a reserved call produced nothing. The slot stays spent."""
        self._failures.append(reason)


__all__ = ["EgressLedger", "EgressPolicy", "ExternalCapability"]
