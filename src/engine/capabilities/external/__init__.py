"""Bounded, read-only external capabilities.

One optional capability so far: documentation lookup through Context7. The shape
of this package is the point -- what may leave the machine is decided by
``policy``, what one departure costs is tracked by ``EgressLedger``, and what an
agent-side module is allowed to *say* is fixed by ``DocsPort``, which names a
single read verb and no way to express arbitrary MCP.

**No transport lives here yet.** ``McpToolCaller`` is an inert Protocol driven by
a scripted fake; the wire arrives in C7. That ordering is deliberate: the
boundary that decides what may leave is written and proven before the thing that
leaves it exists.

A leaf, like the rest of ``capabilities/`` (architecture Rule H): no agent
package, no ``Tool``, no ``Workspace``, no ``CommandPolicy``, no provider SDK.
"""

from engine.capabilities.external.context7 import (
    CONTEXT7_PROVIDER,
    QUERY_TOOL,
    RESOLVE_TOOL,
    Context7Adapter,
    McpToolCaller,
    is_context7_id,
)
from engine.capabilities.external.policy import (
    EgressLedger,
    EgressPolicy,
    ExternalCapability,
)
from engine.capabilities.external.port import (
    MAX_LIBRARY_CHARS,
    MAX_TOPIC_CHARS,
    DocsAnswer,
    DocsPort,
    validate_query,
)

# The one operation this layer admits. Named here rather than spelled as a
# literal at each call site, so the tool, the policy and the report cannot drift
# into disagreeing about what was authorised.
DOCS_LOOKUP = "lookup_docs"

__all__ = [
    "CONTEXT7_PROVIDER",
    "DOCS_LOOKUP",
    "MAX_LIBRARY_CHARS",
    "MAX_TOPIC_CHARS",
    "QUERY_TOOL",
    "RESOLVE_TOOL",
    "Context7Adapter",
    "DocsAnswer",
    "DocsPort",
    "EgressLedger",
    "EgressPolicy",
    "ExternalCapability",
    "McpToolCaller",
    "is_context7_id",
    "validate_query",
]
