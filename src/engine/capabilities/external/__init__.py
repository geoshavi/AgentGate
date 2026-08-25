"""Bounded, read-only external capabilities.

Two optional capabilities: documentation lookup through Context7, and read-only
GitHub context through the official GitHub MCP server. The shape of this package
is the point -- what may leave the machine is decided by ``policy``, what one
departure costs is tracked by ``EgressLedger``, and what an agent-side module is
allowed to *say* is fixed by a port that names read verbs and no way to express
arbitrary MCP.

The second capability is what the first one's boundary was built for: GitHub
arrives as a table of provider tool names and one more ``ExternalCapability``
row, reusing ``EgressPolicy``, ``EgressLedger`` and ``McpHttpTransport``
unchanged. It is a configuration entry, not a second security system -- which is
the failure ``policy`` exists to prevent.

The wire lives in ``transport`` and nowhere else (architecture Rule I), so every
other module here is provably incapable of opening a connection, and both
capabilities can be accepted entirely offline by substituting one opener.

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
from engine.capabilities.external.github import (
    GITHUB_LOOKUP,
    GITHUB_PROVIDER,
    READ_ONLY_TOOLS,
    RESOURCES,
    GitHubAdapter,
    GitHubAnswer,
    GitHubPort,
    GitHubRequest,
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

# The one documentation operation this layer admits. Named here rather than
# spelled as a literal at each call site, so the tool, the policy and the report
# cannot drift into disagreeing about what was authorised. ``GITHUB_LOOKUP`` is
# the same idea for the GitHub capability and lives beside its table.
DOCS_LOOKUP = "lookup_docs"

__all__ = [
    "CONTEXT7_PROVIDER",
    "DOCS_LOOKUP",
    "GITHUB_LOOKUP",
    "GITHUB_PROVIDER",
    "MAX_LIBRARY_CHARS",
    "MAX_TOPIC_CHARS",
    "QUERY_TOOL",
    "READ_ONLY_TOOLS",
    "RESOLVE_TOOL",
    "RESOURCES",
    "Context7Adapter",
    "DocsAnswer",
    "DocsPort",
    "EgressLedger",
    "EgressPolicy",
    "ExternalCapability",
    "GitHubAdapter",
    "GitHubAnswer",
    "GitHubPort",
    "GitHubRequest",
    "McpToolCaller",
    "is_context7_id",
    "validate_query",
]
