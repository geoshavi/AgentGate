"""Evidence-first context: what the diagnosing model is allowed to see.

The selection rule is the whole point of this module. A debugger that is handed
the repository has to guess where to look; a debugger handed the two files the
traceback named does not. So the input is D1's ``FailureEvidence``, and the
files inspected are the ones the *failure itself* referenced -- suspect frame
first, because it is the deepest workspace code before the throw.

Deterministic and model-free: no gateway, no budget, no randomness. The same
evidence over the same workspace renders byte-identical context, which is what
lets a scripted test assert on the prompt the model actually received.

**Reads go through the existing tools, not around them.** ``ReadFileTool`` and
``ListFilesTool`` already own path resolution, truncation, credential refusal
and the inspected-files ledger. Calling them with a tightened ``Limits`` is how
this module gets a smaller read without a second implementation of any of that
-- and it is why a ``.env`` in the workspace cannot reach a prompt from here.
"""

from dataclasses import dataclass, field

from engine.codeagent.limits import DEFAULT_LIMITS, Limits
from engine.codeagent.policy import DEFAULT_POLICY, CommandPolicy
from engine.codeagent.state import ToolResult
from engine.codeagent.tools.base import ToolContext
from engine.codeagent.tools.fs import ListFilesTool, ReadFileTool
from engine.codeagent.tools.search import SearchFilesTool
from engine.codeagent.workspace import Workspace, WorkspaceError
from engine.debugagent.evidence import FailureEvidence, render_evidence


@dataclass(frozen=True)
class InspectedFile:
    """One file shown to the model, read under the inspection bound.

    ``source`` records *why* it is here -- ``"evidence"`` for a file the
    traceback named, ``"search"`` for one discovered by symbol search. The
    distinction matters when reading a report: an evidence file is a fact about
    the failure, a searched file is a lead.
    """

    path: str
    body: str
    source: str = "evidence"


@dataclass(frozen=True)
class DebugContext:
    """Everything the diagnosing model sees, and nothing else."""

    evidence_text: str
    files: list[InspectedFile] = field(default_factory=list)
    listing: str = ""
    truncated: bool = False
    search_terms: list[str] = field(default_factory=list)

    @property
    def inspected_files(self) -> list[str]:
        return [item.path for item in self.files]

    def render(self) -> str:
        parts = [self.evidence_text]
        if self.listing.strip():
            parts.append(f"WORKSPACE (names and sizes only)\n{self.listing.strip()}")
        for item in self.files:
            parts.append(f"FILE {item.path}\n{item.body}")
        return "\n\n".join(parts)


def build_context(
    *,
    evidence: FailureEvidence,
    workspace: Workspace,
    policy: CommandPolicy = DEFAULT_POLICY,
    limits: Limits = DEFAULT_LIMITS,
) -> DebugContext:
    """Assemble bounded, evidence-first context for one diagnosis.

    Never raises and never writes. A file that cannot be read -- deleted between
    the reproduction and now, or refused by the guard -- is skipped rather than
    reported as empty, because an empty body would read as "this file has no
    relevant code".
    """
    # A tightened view of the limits, used only for inspection reads. The tools
    # enforce it, so the bound applies wherever they apply it.
    read_limits = _replace_read_bounds(limits)
    ctx = ToolContext(workspace=workspace, policy=policy, limits=read_limits)

    from_evidence = _selection(evidence, limits)
    terms = _search_terms(evidence, limits)
    discovered = _discover(terms, from_evidence, ctx, limits)

    files: list[InspectedFile] = []
    # Evidence files first, always: a fact about the failure outranks a lead,
    # and the whole-context bound drops from the tail.
    for relative, source in [(p, "evidence") for p in from_evidence] + [
        (p, "search") for p in discovered
    ]:
        if len(files) >= max(0, limits.max_inspected_files):
            break
        result = ReadFileTool().run({"path": relative}, ctx)
        if not result.ok or not result.output.strip():
            continue
        files.append(InspectedFile(path=relative, body=result.output, source=source))

    context = DebugContext(
        evidence_text=render_evidence(evidence),
        files=files,
        listing=_listing(ctx),
        search_terms=terms,
    )
    return _bounded(context, limits)


def _search_terms(evidence: FailureEvidence, limits: Limits) -> list[str]:
    """Symbols worth searching for, taken from the traceback itself.

    Function names, deepest frame first, because the deepest frame is the most
    specific thing the failure told us. This is what keeps the expansion
    evidence-first: the terms are facts the failure produced, not guesses about
    the repository.

    Synthetic frame names (``<module>``, ``<lambda>``, ``<listcomp>``) are
    skipped -- they are not symbols, and searching for them matches nothing
    useful. Very short names are skipped because a two-character identifier
    matches half a codebase.
    """
    terms: list[str] = []
    for frame in reversed(evidence.frames):
        name = frame.function.strip()
        if name.startswith("<") or len(name) < 3 or name in terms:
            continue
        terms.append(name)
        if len(terms) >= max(0, limits.max_search_terms):
            break
    return terms[: max(0, limits.max_search_terms)]


def _discover(
    terms: list[str], already: list[str], ctx: ToolContext, limits: Limits
) -> list[str]:
    """Files that mention an evidence symbol but were not on the stack.

    The case this exists for: a second caller of the buggy helper, a sibling
    definition, a subclass. Such a file is genuinely relevant and can never
    appear in a traceback for the run that did not go through it.

    Search goes through ``SearchFilesTool``, which already skips credential-
    shaped names and unsearchable suffixes; every hit is then re-resolved
    through the workspace guard anyway, because a path parsed out of tool
    output is still a string and defence in depth is cheap here.
    """
    if not terms:
        return []

    found: list[str] = []
    for term in terms:
        result = SearchFilesTool().run({"pattern": term, "suffix": ".py"}, ctx)
        if not result.ok:
            continue
        for line in result.output.splitlines():
            relative, _, _ = line.partition(":")
            relative = relative.strip()
            if not relative or relative in already or relative in found:
                continue
            try:
                resolved = ctx.workspace.resolve(relative)
            except WorkspaceError:
                continue
            if not resolved.is_file():
                continue
            found.append(ctx.workspace.relative(resolved))
            if len(found) >= max(0, limits.max_searched_files):
                return found
    return found


def _selection(evidence: FailureEvidence, limits: Limits) -> list[str]:
    """Which files to inspect, most relevant first.

    ``suspect`` leads because it is the deepest in-workspace frame -- the code
    nearest the throw. The remaining referenced files follow in traceback order,
    which puts callers after callees.
    """
    ordered: list[str] = []
    if evidence.suspect is not None:
        ordered.append(evidence.suspect.file)
    for relative in evidence.referenced_files:
        if relative not in ordered:
            ordered.append(relative)
    return ordered[: max(0, limits.max_inspected_files)]


def _listing(ctx: ToolContext) -> str:
    """A shallow name-and-size listing, for orientation only.

    Contents are never included: knowing that ``helper.py`` exists is useful
    context, and inlining it would be exactly the blind repository dump this
    module exists to avoid.
    """
    result: ToolResult = ListFilesTool().run({"path": ".", "max_depth": 2}, ctx)
    return result.output if result.ok else ""


def _replace_read_bounds(limits: Limits) -> Limits:
    from dataclasses import replace

    return replace(
        limits,
        max_read_bytes=limits.max_inspect_file_bytes,
        max_tool_output_bytes=limits.max_inspect_file_bytes,
    )


def _bounded(context: DebugContext, limits: Limits) -> DebugContext:
    """Enforce the whole-context ceiling by dropping trailing files.

    Files are dropped rather than clipped mid-body: half a function is a
    reliable way to make a model diagnose code that does not exist, whereas a
    missing file is visibly missing. When even one file will not fit, the last
    survivor's body is clipped -- at that point something must give, and losing
    the tail of the most relevant file beats losing the evidence with it.
    """
    ceiling = limits.max_debug_context_chars
    if len(context.render()) <= ceiling:
        return context

    for count in range(len(context.files) - 1, 0, -1):
        trimmed = DebugContext(
            evidence_text=context.evidence_text,
            files=context.files[:count],
            listing=context.listing,
            truncated=True,
            search_terms=context.search_terms,
        )
        if len(trimmed.render()) <= ceiling:
            return trimmed

    head = DebugContext(
        evidence_text=context.evidence_text,
        files=context.files[:1],
        listing=context.listing,
        truncated=True,
    )
    overflow = len(head.render()) - ceiling
    if overflow > 0 and head.files:
        body = head.files[0].body
        head = DebugContext(
            evidence_text=context.evidence_text,
            files=[InspectedFile(path=head.files[0].path, body=body[: max(0, len(body) - overflow)])],
            listing=context.listing,
            truncated=True,
            search_terms=context.search_terms,
        )
    if len(head.render()) <= ceiling:
        return head

    # Even the evidence and listing alone overflow. Keep the evidence: it is the
    # one part that cannot be re-derived from the workspace.
    return DebugContext(
        evidence_text=context.evidence_text[:ceiling],
        files=[],
        listing="",
        truncated=True,
        search_terms=context.search_terms,
    )


__all__ = ["DebugContext", "InspectedFile", "build_context"]
