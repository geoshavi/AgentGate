"""GitHub, behind a port: one read verb over the official GitHub MCP server.

The provider's real interface, taken from ``github/github-mcp-server`` rather
than assumed. The remote server is Streamable HTTP at
``https://api.githubcopilot.com/mcp/`` with ``Authorization: Bearer <PAT>``, and
it publishes a **read-only endpoint variant** as a ``/readonly`` path suffix
(``https://api.githubcopilot.com/mcp/readonly``) alongside per-toolset variants
under ``/x/{toolset}``. Which of those an operator points at is operator
business; this module never composes a URL and never sees one.

**No second framework.** ``McpToolCaller`` is the same transport seam C7 wrote,
so ``McpHttpTransport`` serves this adapter unchanged -- same egress chokepoint,
same ``EgressPolicy``, same ``EgressLedger``. This file adds a provider, not a
mechanism.

**Read-only by construction, in two independent layers.**

1. ``RESOURCES`` is a closed table mapping AgentGate resource names to official
   tool names. Every entry names a documented read tool; ``create_or_update_file``,
   ``push_files``, ``merge_pull_request``, ``issue_write`` and the rest have no
   row, and a tool name is never taken from an argument. A model holding this
   capability cannot *say* a write tool, which is a stronger boundary than
   refusing one.
2. The operator points ``server`` at the published ``/readonly`` endpoint, so the
   server itself refuses a write even if layer 1 were wrong.

**Scope is operator-owned too.** The credential is the operator's, so the model
does not get to aim it: ``repos`` is a configured allowlist, and the canonical
spelling from that list -- never the caller's -- is what reaches the wire. Code
search is scoped by appending a ``repo:`` qualifier, and a query carrying its own
``repo:``/``org:``/``user:`` qualifier is refused, because a second qualifier ORs
and would widen the scope past the allowlist.

Provider output is **untrusted data**: it is rendered to bounded text and never
interpreted.
"""

import json
import re
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol

from engine.capabilities.errors import CapabilityError, GitHubUnavailable
from engine.capabilities.external.context7 import McpToolCaller

GITHUB_PROVIDER = "github"
GITHUB_LOOKUP = "lookup_github"

# Bounds on what a caller may ask for. MAX_QUERY_CHARS is the provider's own
# documented ceiling for code search, so an over-long query is refused here
# rather than spending a reserved call slot to be refused there.
MAX_REPO_CHARS = 128
MAX_PATH_CHARS = 400
MAX_QUERY_CHARS = 256
MAX_REF_CHARS = 128

# One page, deliberately small. The ledger bounds characters either way, but a
# smaller page means the truncation point lands after whole records more often.
PAGE_SIZE = 20

_REPO_PATTERN = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")
_REF_PATTERN = re.compile(r"^[A-Za-z0-9._/-]+$")
# Qualifiers that would widen a code search beyond the configured allowlist.
_SCOPE_QUALIFIER = re.compile(r"(?:^|\s)(?:repo|org|user):", re.IGNORECASE)


@dataclass(frozen=True)
class _Resource:
    """One admitted read, and exactly how the official server spells it.

    ``method`` serves the consolidated tools (``issue_read``,
    ``pull_request_read``, ``actions_list``), which take the operation as an
    argument. Fixing it here rather than passing it through is the point: each
    admitted read method is its own AgentGate resource, so a write method is not
    reachable by supplying one.
    """

    tool: str
    method: str = ""
    needs: str = ""  # "", "path", "query" or "number"
    number_key: str = ""
    number_as_text: bool = False
    page_key: str = ""  # "" means the tool is not paginated
    # ``search_code`` takes a query and nothing else -- its scope lives in the
    # query's own qualifiers -- so it is the one read that must not be sent
    # owner/repo arguments the published schema does not define.
    takes_repo: bool = True


# The whole allowlist. Names on the left are AgentGate's and are what a model
# chooses between; names on the right are the official server's and are never
# built from an argument.
RESOURCES: Mapping[str, _Resource] = MappingProxyType(
    {
        "file": _Resource("get_file_contents", needs="path"),
        "code_search": _Resource(
            "search_code", needs="query", page_key="perPage", takes_repo=False
        ),
        "commits": _Resource("list_commits", page_key="perPage"),
        "branches": _Resource("list_branches", page_key="perPage"),
        "issues": _Resource("list_issues", page_key="perPage"),
        "issue": _Resource(
            "issue_read", method="get", needs="number", number_key="issue_number"
        ),
        "pull_requests": _Resource("list_pull_requests", page_key="perPage"),
        "pull_request": _Resource(
            "pull_request_read", method="get", needs="number", number_key="pullNumber"
        ),
        "pull_request_diff": _Resource(
            "pull_request_read", method="get_diff", needs="number", number_key="pullNumber"
        ),
        "ci_runs": _Resource(
            "actions_list", method="list_workflow_runs", page_key="per_page"
        ),
        "ci_jobs": _Resource(
            "actions_list",
            method="list_workflow_jobs",
            needs="number",
            number_key="resource_id",
            number_as_text=True,
            page_key="per_page",
        ),
    }
)

# Every official tool this capability can reach, derived from the table rather
# than restated -- so the two cannot drift, and a test can assert the whole set
# against the documented read-only tools.
READ_ONLY_TOOLS = frozenset(spec.tool for spec in RESOURCES.values())


@dataclass(frozen=True)
class GitHubRequest:
    """What a caller may ask for. There is no field for a server or a tool."""

    resource: str
    repo: str
    path: str = ""
    query: str = ""
    number: int | None = None
    ref: str = ""


@dataclass(frozen=True)
class GitHubAnswer:
    """One bounded GitHub read.

    ``content`` is **untrusted text**: issue bodies, pull request descriptions
    and file contents are written by anyone. It informs the agent and has no
    structural effect on anything.

    ``repo`` is echoed as the allowlist spells it, so a reader of the transcript
    sees which repository was actually read rather than which one was asked for.
    """

    repo: str
    resource: str
    selector: str
    content: str
    source: str
    truncated: bool = False


class GitHubPort(Protocol):
    """Read GitHub. That is the entire interface -- no write verb exists."""

    def fetch(
        self, request: GitHubRequest, *, timeout_s: float, max_chars: int
    ) -> GitHubAnswer: ...


class GitHubAdapter:
    """A ``GitHubPort`` over the official server's read tools."""

    provider = GITHUB_PROVIDER

    def __init__(
        self,
        caller: McpToolCaller,
        *,
        repos: Iterable[str],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._caller = caller
        # Casefolded key, operator spelling as the value: the lookup is
        # case-insensitive because GitHub is, but what goes on the wire is the
        # operator's string, never the caller's.
        self._repos = {
            repo.casefold(): repo
            for repo in repos
            if isinstance(repo, str) and _REPO_PATTERN.match(repo)
        }
        self._clock = clock

    @property
    def repos(self) -> tuple[str, ...]:
        return tuple(sorted(self._repos.values()))

    def fetch(
        self, request: GitHubRequest, *, timeout_s: float, max_chars: int
    ) -> GitHubAnswer:
        """Validate, call one read tool, and return an answer bounded to ``max_chars``.

        Raises:
            GitHubUnavailable: an unknown resource, a repository outside the
                allowlist, a malformed argument, an exhausted timeout, or any
                transport or server fault. All of them are one thing to the
                caller -- the lookup produced nothing -- and the next move is the
                same in every case: continue from repository evidence.
        """
        if max_chars <= 0:
            raise GitHubUnavailable("no character allowance remains for a GitHub lookup")

        spec = RESOURCES.get(request.resource)
        if spec is None:
            raise GitHubUnavailable(
                f"unknown resource {request.resource!r}; available: {sorted(RESOURCES)}"
            )

        repo = self._allowed(request.repo)
        owner, name = repo.split("/", 1)
        arguments = _arguments(spec, request, owner, name)

        deadline = self._clock() + timeout_s
        raw = self._call(spec.tool, arguments, deadline)
        content = _render(raw)

        clipped = content[:max_chars]
        return GitHubAnswer(
            repo=repo,
            resource=request.resource,
            selector=_selector(spec, request),
            content=clipped,
            source=GITHUB_PROVIDER,
            truncated=len(content) > max_chars,
        )

    def _allowed(self, repo: object) -> str:
        """The allowlist. An empty one admits nothing, which is the closed default."""
        if not isinstance(repo, str) or not repo.strip():
            raise GitHubUnavailable("repo must be a non-empty 'owner/name' string")
        found = self._repos.get(repo.strip().casefold())
        if found is None:
            raise GitHubUnavailable(
                f"repository {repo.strip()!r} is not configured for this run; "
                f"available: {sorted(self._repos.values()) or 'none'}"
            )
        return found

    def _call(self, name: str, arguments: Mapping[str, object], deadline: float) -> object:
        remaining = deadline - self._clock()
        if remaining <= 0:
            raise GitHubUnavailable(f"GitHub lookup timed out before {name}")
        try:
            return self._caller.call_tool(name, arguments, remaining)
        except GitHubUnavailable:
            raise
        except CapabilityError as exc:
            # The shared transport speaks in its own refusal type. Re-raised here
            # so a caller catches one thing per capability.
            raise GitHubUnavailable(f"GitHub lookup failed during {name}: {exc}") from exc
        except Exception as exc:
            raise GitHubUnavailable(
                f"GitHub lookup failed during {name}: {type(exc).__name__}"
            ) from exc


# -- argument construction ---------------------------------------------------


def _arguments(
    spec: _Resource, request: GitHubRequest, owner: str, name: str
) -> dict[str, object]:
    """The official tool's arguments, built from a validated request.

    Every key is written here from the table and the request's typed fields; no
    key is ever copied in from caller-supplied data, so an extra argument cannot
    ride along into the provider call.
    """
    arguments: dict[str, object] = {"owner": owner, "repo": name} if spec.takes_repo else {}
    if spec.method:
        arguments["method"] = spec.method
    if spec.page_key:
        arguments[spec.page_key] = PAGE_SIZE

    if spec.needs == "path":
        arguments["path"] = _path(request.path)
        ref = _ref(request.ref)
        if ref:
            arguments["ref"] = ref
    elif spec.needs == "query":
        # Scoped to the allowlisted repository by construction. The qualifier is
        # appended rather than trusted from the caller.
        arguments["query"] = f"{_query(request.query)} repo:{owner}/{name}"
    elif spec.needs == "number":
        number = _number(request.number)
        arguments[spec.number_key] = str(number) if spec.number_as_text else number

    return arguments


def _selector(spec: _Resource, request: GitHubRequest) -> str:
    """A short label for what was asked for, for the transcript and the report."""
    if spec.needs == "path":
        return _path(request.path)
    if spec.needs == "query":
        return _query(request.query)
    if spec.needs == "number":
        return f"#{_number(request.number)}"
    return ""


def _path(value: object) -> str:
    text = _text(value, "path", MAX_PATH_CHARS)
    if text.startswith("/") or ".." in text:
        raise GitHubUnavailable("path must be repository-relative and must not contain '..'")
    return text


def _query(value: object) -> str:
    text = _text(value, "query", MAX_QUERY_CHARS)
    if _SCOPE_QUALIFIER.search(text):
        raise GitHubUnavailable(
            "query must not carry a repo:, org: or user: qualifier; the search is "
            "already scoped to the configured repository"
        )
    return text


def _ref(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    text = _text(value, "ref", MAX_REF_CHARS)
    if not _REF_PATTERN.match(text):
        raise GitHubUnavailable("ref may contain only letters, digits, '.', '_', '-' and '/'")
    return text


def _number(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise GitHubUnavailable("this resource requires a positive integer 'number'")
    return value


def _text(value: object, label: str, ceiling: int) -> str:
    """Single-line, non-empty and bounded.

    Control characters are refused because every one of these fields is a
    single-line value, so a newline or a NUL is either a mistake or an attempt to
    smuggle structure into a string field.
    """
    if not isinstance(value, str):
        raise GitHubUnavailable(f"{label} must be a string, got {type(value).__name__}")
    text = value.strip()
    if not text:
        raise GitHubUnavailable(f"{label} must not be empty")
    if len(text) > ceiling:
        raise GitHubUnavailable(f"{label} is {len(text)} characters; the maximum is {ceiling}")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in text):
        raise GitHubUnavailable(f"{label} must not contain control characters")
    return text


# -- untrusted response rendering --------------------------------------------


def _render(raw: object) -> str:
    """The provider's payload as bounded text.

    The transport already unwraps an MCP result to a string, a mapping or a list.
    A string is used as it stands; anything else is rendered as sorted, indented
    JSON so the same response always produces the same characters. An empty
    answer is a failure: reporting success with nothing in it would spend a call
    slot and tell the caller it had context.
    """
    if isinstance(raw, str):
        text = raw
    else:
        try:
            text = json.dumps(raw, indent=2, sort_keys=True, default=str)
        except (TypeError, ValueError) as exc:
            raise GitHubUnavailable("GitHub returned an unusable response") from exc
    if not text.strip() or text.strip() in {"{}", "[]", "null"}:
        raise GitHubUnavailable("GitHub lookup returned an empty response")
    return text


__all__ = [
    "GITHUB_LOOKUP",
    "GITHUB_PROVIDER",
    "MAX_PATH_CHARS",
    "MAX_QUERY_CHARS",
    "MAX_REF_CHARS",
    "MAX_REPO_CHARS",
    "PAGE_SIZE",
    "READ_ONLY_TOOLS",
    "RESOURCES",
    "GitHubAdapter",
    "GitHubAnswer",
    "GitHubPort",
    "GitHubRequest",
]
