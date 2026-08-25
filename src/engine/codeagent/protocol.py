"""The text tool protocol: how a model turn becomes a machine-readable request,
and how the loop's side of the conversation is rendered.

Why a text protocol at all is argued in the blueprint (§7): the Provider
contract carries ``list[Message]`` of plain strings and returns flattened text,
so native tool-use would mean editing ``runtime/gateway.py`` -- measured path,
shared with every judge lens call. This module is the cost of that decision,
and it pays for it by being strict.

Strict means: a turn contains exactly one fenced ``tool`` or ``final`` block,
that block's body is a JSON object, and anything else is a ``ParseError``.
Prose is never scanned for intent. There is no "it probably meant read_file"
path, no first-block-wins, and no repair of nearly-valid JSON -- a malformed
turn is reported, counted, and bounded by the session.

**This module judges syntax only.** It does not know which tools exist. An
unknown tool name parses successfully and fails later as a tool observation,
which is a deliberate departure from blueprint §7 rule 3 (which made it a
ParseError). Two reasons: the registry is a semantic concern that belongs with
the thing that owns it, and a syntactically perfect call to a misremembered
name deserves an observation naming the real tools, not a generic scolding
that spends the protocol-error budget.

Nothing here persists model prose. ``ParseError.message`` describes the fault
and never quotes the response, because a fault message is written to the
session log and the response body is exactly the reasoning text the blueprint
forbids storing.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any

from engine.codeagent.state import ToolCall, ToolResult
from engine.codeagent.tools.base import Tool

# A block is a fence whose info string is exactly `tool` or `final`, anchored to
# the start of a line so a fence inside a JSON string or an echoed tool result
# cannot open one. Non-greedy, so the first closing fence ends the block.
_BLOCK_RE = re.compile(
    r"^[ \t]*```([A-Za-z0-9_+-]+)[ \t]*\r?\n(.*?)^[ \t]*```", re.DOTALL | re.MULTILINE
)


def find_blocks(text: str, kinds: tuple[str, ...]) -> list[tuple[str, str]]:
    """Every fenced block in ``text`` whose info string is one of ``kinds``.

    The single definition of what counts as a block, shared by the turn parser
    below and by the planner (``plan.py``), so the two cannot drift into
    disagreeing about what the model is allowed to emit.

    Non-matching fences (```python and friends) are scanned and discarded
    rather than ignored, which keeps the scan positions identical to matching
    them directly -- a ```python block containing a stray fence still cannot
    open a tool block.
    """
    return [(kind, body) for kind, body in _BLOCK_RE.findall(text) if kind in kinds]

# Upper bound on a persisted final summary. It is a structured deliverable, not
# reasoning, but it is still model-authored text and an unbounded field in a
# report is how a log becomes a transcript.
MAX_SUMMARY_CHARS = 2_000


@dataclass(frozen=True)
class ToolRequest:
    call: ToolCall


@dataclass(frozen=True)
class FinalResponse:
    summary: str = ""
    files_changed: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ParseError:
    message: str


ParsedTurn = ToolRequest | FinalResponse | ParseError


def parse(text: str) -> ParsedTurn:
    """Turn one assistant turn into a request, a finish, or a fault."""
    if not isinstance(text, str) or not text.strip():
        return ParseError("the response was empty; emit exactly one ```tool block")

    blocks = find_blocks(text, ("tool", "final"))
    if not blocks:
        return ParseError(
            "no ```tool or ```final block found; every turn must contain exactly one, "
            "opened at the start of a line"
        )
    if len(blocks) > 1:
        kinds = ", ".join(kind for kind, _ in blocks)
        return ParseError(
            f"found {len(blocks)} blocks ({kinds}); emit exactly one per turn. "
            "No block was executed."
        )

    kind, body = blocks[0]
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        return ParseError(f"the ```{kind} block body is not valid JSON: {exc.msg} (line {exc.lineno})")

    if not isinstance(payload, dict):
        return ParseError(
            f"the ```{kind} block body must be a JSON object, got {type(payload).__name__}"
        )

    if kind == "final":
        return _parse_final(payload)
    return _parse_tool(payload)


def _parse_tool(payload: dict[str, Any]) -> ParsedTurn:
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip():
        return ParseError("the ```tool block needs a non-empty string 'name'")

    args = payload.get("args", {})
    if args is None:
        args = {}
    if not isinstance(args, dict):
        return ParseError(f"'args' must be a JSON object, got {type(args).__name__}")
    if not all(isinstance(key, str) for key in args):
        return ParseError("every key in 'args' must be a string")

    return ToolRequest(ToolCall(name=name.strip(), args=args))


def _parse_final(payload: dict[str, Any]) -> ParsedTurn:
    summary = payload.get("summary", "")
    if not isinstance(summary, str):
        return ParseError(f"'summary' must be a string, got {type(summary).__name__}")

    claimed = payload.get("files_changed", [])
    if claimed is None:
        claimed = []
    if not isinstance(claimed, list) or not all(isinstance(item, str) for item in claimed):
        return ParseError("'files_changed' must be a list of strings")

    return FinalResponse(summary=summary[:MAX_SUMMARY_CHARS], files_changed=list(claimed))


# -- rendering --------------------------------------------------------------
#
# Every renderer is a pure function of its arguments: no clock, no counter, no
# randomness. Two identical inputs produce two identical prompts, which is what
# makes a scripted offline test meaningful.


def build_system_prompt(tools: dict[str, Tool], *, skills_catalogue: str = "") -> str:
    """Assemble the agent contract from the live registry.

    Generated rather than stored as a file so the advertised tool list cannot
    drift from the registered one -- a prompt naming a tool that no longer
    exists is a parse-error generator.

    ``skills_catalogue`` is bounded metadata -- one line per advertised skill,
    its name and when to use it -- and never a skill body: full instructions
    enter context only through an explicit ``load_skill`` call. Defaulted to ""
    so every existing caller produces a byte-identical prompt, which is what
    makes "a run with no skills behaves exactly as before" checkable rather than
    merely asserted.
    """
    catalogue = "\n".join(f"- {name}: {tools[name].description}" for name in sorted(tools))
    skills = (
        ""
        if not skills_catalogue
        else f"\n\nAvailable skills (call load_skill to read one in full):\n{skills_catalogue}"
    )
    return f"""You are a coding agent working inside a fixed workspace.

Work by calling exactly one tool per turn. End every message with exactly one
fenced block and nothing after it.

To call a tool:

```tool
{{"name": "<tool>", "args": {{...}}}}
```

To finish, once the task is done and you have verified it:

```final
{{"summary": "<what you changed and why>", "files_changed": ["<path>", ...]}}
```

Rules:
- Exactly one block per turn. Two blocks are rejected and neither runs.
- The block body must be a JSON object.
- Read a file before editing it. Anchors for replace_exact must match exactly
  once, so copy them verbatim, including indentation.
- All paths are relative to the workspace. Paths outside it are refused, as are
  credential files.
- Commands are argv lists, never shell strings, and only allowlisted programs
  run.
- A tool error is information, not a dead end: read it and adjust.

Available tools:
{catalogue}{skills}"""


def render_task(task_text: str) -> str:
    return f"TASK\n{task_text.strip()}\n\nBegin by inspecting the workspace."


def render_observation(tool_name: str, result: ToolResult) -> str:
    lines = [f"TOOL RESULT: {tool_name}", f"status: {'ok' if result.ok else 'error'}"]
    if result.exit_code is not None:
        lines.append(f"exit_code: {result.exit_code}")
    if result.truncated:
        lines.append("truncated: true")
    lines.append("---")
    if result.ok:
        lines.append(result.output or "(no output)")
    else:
        # `error` is set by every failure path in the tool layer, but a None
        # here would render the string "None" as if it were the diagnosis.
        lines.append(result.error or "(the tool failed without a message)")
    return "\n".join(lines)


def render_parse_error(message: str, *, remaining: int) -> str:
    return (
        "PROTOCOL ERROR\n"
        f"{message}\n"
        f"Nothing was executed. {remaining} malformed response(s) remain before this "
        "session is aborted. Reply with exactly one ```tool or ```final block."
    )
