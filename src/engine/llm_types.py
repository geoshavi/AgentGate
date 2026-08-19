"""The gateway <-> provider data contract, owned by neither side.

``Message`` and ``GenerationResult`` are the input and output types of
``LLMGateway.generate()``, so every caller of the Gateway needs them. They
used to live in ``providers/base.py``, which forced a choice between two bad
options: either every caller imports the provider package just to build the
Gateway's arguments (defeating the point of Rule B -- the Gateway is supposed
to be the only thing reaching into providers/), or Rule B carries a permanent
allowlist exception for ``providers.base``. The repo took the second option
and documented it; this module removes the need for either.

They cannot live in ``runtime/`` instead, because Rule C forbids providers/
from importing runtime/ and the provider implementations need these types to
satisfy the ``Provider`` protocol. A neutral leaf that both sides may import
is the only placement that keeps every rule exception-free.

Deliberately a leaf: this module imports nothing from ``engine.*`` and must
stay that way, so it can never become a back-channel between layers that the
architecture rules otherwise keep apart. Enforced by Rule F in
tests/test_architecture.py.

The ``Provider`` protocol itself stays in ``providers/base.py`` -- it
describes how a provider is implemented, which is genuinely provider-layer
concern, and nothing outside providers/ and the Gateway needs it.
"""

from dataclasses import dataclass, field
from typing import Any, Literal

# Reasoning depth for one call. Spelled as a Literal rather than ``str`` so a
# typo is a type error instead of a provider-side 400, and defined here rather
# than imported from the SDK because Rule A forbids anything outside runtime/
# and providers/ from importing a provider SDK. ``None`` means "say nothing" --
# the request omits the field entirely and the provider's own default applies.
Effort = Literal["low", "medium", "high", "xhigh", "max"]


@dataclass(frozen=True)
class Message:
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class GenerationResult:
    text: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    # Termination and reasoning metadata, defaulted so a provider that cannot
    # report them is indistinguishable from the pre-9C.2 shape. ``None`` means
    # "not reported", never "ended normally" -- those are different claims and
    # conflating them is what made Phase 9C's truncations inferable only from
    # ``output_tokens == max_tokens``. ``thinking_tokens`` is a count, not
    # content: the reasoning text itself is deliberately never carried here.
    stop_reason: str | None = None
    thinking_tokens: int = 0
    raw: Any = field(default=None, repr=False)
