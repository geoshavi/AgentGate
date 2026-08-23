"""Deterministic failure evidence: what a reproduction command actually did.

Every value here is an observable fact about a child process -- its argv, its
status, the bytes it wrote, and the workspace files its traceback named. There
is no field for an explanation and no code path that could put one here. Naming
a root cause is D2's job and needs a model; this module needs none, and its
signatures say so by taking no gateway, budget or connection.

**Purity is the point.** ``build_evidence`` is a function of the strings a
command produced, so the same failure yields byte-identical evidence on every
run. That is what lets the offline tests assert exact frame lists instead of
approximate ones, and what makes evidence comparable across repair rounds.

Two rules earn their own emphasis:

**Tails, not heads.** A pytest failure puts the useful part at the end of the
output. Truncating from the front would reliably discard the traceback and keep
the collection banner, which is the opposite of useful.

**Traceback paths are untrusted input.** A path in a traceback is a string a
child process wrote; it is not evidence that a file is in the workspace, and it
is a directory-traversal vector. Every one goes through ``Workspace.resolve``,
which is the same guard the file tools use, and a path that escapes, names a
credential-shaped file, or does not exist is dropped rather than reported.
"""

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from engine.codeagent.limits import DEFAULT_LIMITS, Limits
from engine.codeagent.workspace import Workspace, WorkspaceError

# `  File "<path>", line <N>, in <fn>` -- CPython's traceback frame line.
_FRAME_RE = re.compile(
    r'^\s*File "(?P<file>.+?)", line (?P<line>\d+), in (?P<function>.+?)\s*$',
    re.MULTILINE,
)

# The `ExceptionType: message` line that closes a traceback, and pytest's
# `E   ValueError: ...` echo of it.
#
# The final dotted component must start with a capital, which is what keeps an
# ordinary output line like `make: *** [all] Error 2` from being read as an
# exception. Frame lines cannot match: they are indented, and this is anchored
# to the start of the line with only pytest's `E` marker allowed before it.
_EXCEPTION_RE = re.compile(
    r"^(?:E\s+)?"
    r"(?P<type>(?:[A-Za-z_][A-Za-z0-9_]*\.)*[A-Z][A-Za-z0-9_]*)"
    r"\s*:\s?(?P<message>.*)$",
    re.MULTILINE,
)

# Hard ceiling on the one-line summary, independent of max_evidence_text_chars
# so that a generous text budget still cannot produce a paragraph.
MAX_SUMMARY_CHARS = 200


@dataclass(frozen=True)
class Frame:
    """One traceback frame that survived the workspace guard.

    ``file`` is workspace-relative and posix-style, so it can be handed
    straight to ``read_file`` without a second round of path handling.
    """

    file: str
    line: int
    function: str


@dataclass(frozen=True)
class FailureEvidence:
    """What the reproduction command did. Observable facts only."""

    argv: list[str]
    reproduced: bool
    exit_code: int | None
    timed_out: bool
    duration_ms: int
    stdout_tail: str
    stderr_tail: str
    exception_type: str | None = None
    exception_message: str | None = None
    frames: list[Frame] = field(default_factory=list)
    suspect: Frame | None = None
    referenced_files: list[str] = field(default_factory=list)
    summary: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def tail(text: str, limit: int) -> str:
    """The last ``limit`` characters of ``text``.

    Deliberately not ``truncate`` from tools/base.py: that one keeps the head
    and appends a marker, which is right for a tool observation and wrong for a
    failure log. No marker is added, because the marker would itself consume
    part of a small budget and the length is already reported by the bound.
    """
    if limit <= 0:
        return ""
    return text if len(text) <= limit else text[-limit:]


def to_workspace_file(raw: str, workspace: Workspace) -> str | None:
    """Turn an untrusted path from command output into a workspace-relative one.

    Returns None -- never raises, and never a path -- when the string does not
    denote a real, permitted file inside the workspace. Absolute paths are made
    relative to the root before the guard runs, because ``Workspace.resolve``
    refuses absolute input by design and a traceback only ever emits absolute
    paths.
    """
    text = raw.strip().strip('"')
    if not text:
        return None

    candidate = Path(text)
    if candidate.is_absolute() or candidate.drive:
        try:
            resolved = candidate.resolve()
        except (OSError, ValueError):
            return None
        if not resolved.is_relative_to(workspace.root):
            return None
        relative = resolved.relative_to(workspace.root).as_posix()
    else:
        relative = text

    try:
        # The real guard: '..', symlink escape, and credential-shaped names.
        target = workspace.resolve(relative)
    except WorkspaceError:
        return None

    # A traceback can name a file that exists on another machine but not here.
    # Reporting it would send the agent to read something that is not there.
    if not target.is_file():
        return None
    return workspace.relative(target)


def extract_frames(text: str, workspace: Workspace, limits: Limits) -> list[Frame]:
    """In-workspace traceback frames, deepest last, bounded.

    When the bound bites, the *deepest* frames are kept: the frame nearest the
    throw is the one worth reading, and the outer frames are usually test
    harness scaffolding.
    """
    frames: list[Frame] = []
    for match in _FRAME_RE.finditer(text):
        relative = to_workspace_file(match.group("file"), workspace)
        if relative is None:
            continue
        frames.append(
            Frame(
                file=relative,
                line=int(match.group("line")),
                function=match.group("function").strip(),
            )
        )
    if limits.max_evidence_frames >= 0:
        frames = frames[-limits.max_evidence_frames :] if limits.max_evidence_frames else []
    return frames


def extract_exception(text: str, limits: Limits) -> tuple[str | None, str | None]:
    """The last ``Type: message`` line, or (None, None).

    Last rather than first: a pytest run can echo several, and the closing one
    is the failure that stopped the command.
    """
    matches = list(_EXCEPTION_RE.finditer(text))
    if not matches:
        return None, None
    last = matches[-1]
    message = last.group("message").strip()[: limits.max_evidence_text_chars]
    return last.group("type"), message


def build_evidence(
    *,
    argv: list[str],
    stdout: str,
    stderr: str,
    exit_code: int | None,
    timed_out: bool,
    duration_ms: int,
    workspace: Workspace,
    limits: Limits = DEFAULT_LIMITS,
) -> FailureEvidence:
    """Assemble evidence from one command's observable results.

    Parsing runs over the *bounded* tails rather than the raw streams, so
    ``max_repro_output_bytes`` bounds the parser's input as well as the stored
    text -- there is no second limit for "lines scanned" because there cannot be
    more input than the tails hold.
    """
    stdout_tail = tail(stdout, limits.max_repro_output_bytes)
    stderr_tail = tail(stderr, limits.max_repro_output_bytes)
    # stderr first: a traceback is written there, and when both streams carry
    # one the stderr copy is the authoritative one.
    scanned = f"{stderr_tail}\n{stdout_tail}"

    frames = extract_frames(scanned, workspace, limits)
    exception_type, exception_message = extract_exception(scanned, limits)
    suspect = frames[-1] if frames else None

    referenced: list[str] = []
    for frame in frames:
        if frame.file not in referenced:
            referenced.append(frame.file)
    referenced = referenced[: limits.max_referenced_files]

    reproduced = exit_code is not None and exit_code != 0 and not timed_out

    return FailureEvidence(
        argv=list(argv),
        reproduced=reproduced,
        exit_code=exit_code,
        timed_out=timed_out,
        duration_ms=duration_ms,
        stdout_tail=stdout_tail,
        stderr_tail=stderr_tail,
        exception_type=exception_type,
        exception_message=exception_message,
        frames=frames,
        suspect=suspect,
        referenced_files=referenced,
        summary=_summarize(
            exit_code=exit_code,
            timed_out=timed_out,
            duration_ms=duration_ms,
            exception_type=exception_type,
            exception_message=exception_message,
            suspect=suspect,
        ),
    )


def _summarize(
    *,
    exit_code: int | None,
    timed_out: bool,
    duration_ms: int,
    exception_type: str | None,
    exception_message: str | None,
    suspect: Frame | None,
) -> str:
    """A one-line description derived only from what was observed.

    Never a diagnosis. It says what happened, not why -- naming a cause is D2's
    job and requires a model.
    """
    if timed_out:
        text = f"reproduction command timed out after {duration_ms}ms"
    elif exit_code is None:
        text = "reproduction command did not execute"
    elif exception_type is not None:
        text = exception_type
        if exception_message:
            text = f"{text}: {exception_message}"
        if suspect is not None:
            text = f"{text} ({suspect.file}:{suspect.line} in {suspect.function})"
    else:
        text = f"reproduction command exited {exit_code}"
    return text[:MAX_SUMMARY_CHARS]


def render_evidence(evidence: FailureEvidence) -> str:
    """The evidence as text for a prompt. Pure -- no clock, no counter."""
    heading = "REPRODUCED FAILURE" if evidence.reproduced else "FAILURE NOT REPRODUCED"
    lines = [
        heading,
        f"command : {' '.join(evidence.argv)}",
        f"exit    : {'(none)' if evidence.exit_code is None else evidence.exit_code}",
        f"summary : {evidence.summary}",
    ]
    if evidence.suspect is not None:
        lines.append(
            f"suspect : {evidence.suspect.file}:{evidence.suspect.line} "
            f"in {evidence.suspect.function}"
        )
    if evidence.frames:
        trail = " -> ".join(f"{f.file}:{f.line} in {f.function}" for f in evidence.frames)
        lines.append(f"frames  : {trail}")
    if evidence.stdout_tail.strip():
        lines.append(f"--- stdout (tail) ---\n{evidence.stdout_tail.rstrip()}")
    if evidence.stderr_tail.strip():
        lines.append(f"--- stderr (tail) ---\n{evidence.stderr_tail.rstrip()}")
    return "\n".join(lines)


__all__ = [
    "FailureEvidence",
    "Frame",
    "build_evidence",
    "extract_exception",
    "extract_frames",
    "render_evidence",
    "tail",
    "to_workspace_file",
]
