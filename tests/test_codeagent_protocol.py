import json

from engine.codeagent import protocol
from engine.codeagent.state import ToolResult
from engine.codeagent.tools.registry import TOOL_REGISTRY


def _tool_block(name: str, args: dict | None = None) -> str:
    payload = {"name": name, "args": args if args is not None else {}}
    return f"```tool\n{json.dumps(payload)}\n```"


def _final_block(summary: str = "done", files: list[str] | None = None) -> str:
    payload = {"summary": summary, "files_changed": files or []}
    return f"```final\n{json.dumps(payload)}\n```"


# -- well-formed turns ------------------------------------------------------


def test_parses_a_single_tool_block() -> None:
    parsed = protocol.parse(_tool_block("read_file", {"path": "todo.py"}))

    assert isinstance(parsed, protocol.ToolRequest)
    assert parsed.call.name == "read_file"
    assert parsed.call.args == {"path": "todo.py"}


def test_parses_a_tool_block_surrounded_by_prose() -> None:
    text = f"I need to look at the file first.\n\n{_tool_block('read_file', {'path': 'a.py'})}\n"
    parsed = protocol.parse(text)

    assert isinstance(parsed, protocol.ToolRequest)
    assert parsed.call.name == "read_file"


def test_parses_a_final_block() -> None:
    parsed = protocol.parse(_final_block("fixed the bug", ["todo.py"]))

    assert isinstance(parsed, protocol.FinalResponse)
    assert parsed.summary == "fixed the bug"
    assert parsed.files_changed == ["todo.py"]


def test_missing_args_defaults_to_empty() -> None:
    parsed = protocol.parse('```tool\n{"name": "run_tests"}\n```')

    assert isinstance(parsed, protocol.ToolRequest)
    assert parsed.call.args == {}


def test_final_block_defaults_are_empty() -> None:
    parsed = protocol.parse("```final\n{}\n```")

    assert isinstance(parsed, protocol.FinalResponse)
    assert parsed.summary == ""
    assert parsed.files_changed == []


def test_a_long_summary_is_capped() -> None:
    parsed = protocol.parse(_final_block("x" * 5_000))

    assert isinstance(parsed, protocol.FinalResponse)
    assert len(parsed.summary) == protocol.MAX_SUMMARY_CHARS


# -- prose is never a tool call ---------------------------------------------


def test_prose_alone_is_a_parse_error() -> None:
    parsed = protocol.parse("I will now read todo.py and fix parse_due_date.")

    assert isinstance(parsed, protocol.ParseError)
    assert "no ```tool or ```final block" in parsed.message


def test_an_empty_response_is_a_parse_error() -> None:
    for text in ("", "   \n  "):
        parsed = protocol.parse(text)
        assert isinstance(parsed, protocol.ParseError)
        assert "empty" in parsed.message


def test_a_tool_name_mentioned_in_prose_is_not_executed() -> None:
    parsed = protocol.parse("Let me call read_file with path=todo.py to see what is there.")

    assert isinstance(parsed, protocol.ParseError)


def test_a_non_tool_fence_is_not_a_tool_call() -> None:
    parsed = protocol.parse('Here is the fix:\n\n```python\nprint("hi")\n```\n')

    assert isinstance(parsed, protocol.ParseError)


# -- ambiguity is refused, never resolved -----------------------------------


def test_two_tool_blocks_are_refused_without_running_either() -> None:
    text = f"{_tool_block('read_file', {'path': 'a.py'})}\n{_tool_block('run_tests')}"
    parsed = protocol.parse(text)

    assert isinstance(parsed, protocol.ParseError)
    assert "found 2 blocks" in parsed.message
    assert "No block was executed" in parsed.message


def test_a_tool_block_and_a_final_block_together_are_refused() -> None:
    parsed = protocol.parse(f"{_tool_block('run_tests')}\n{_final_block()}")

    assert isinstance(parsed, protocol.ParseError)
    assert "found 2 blocks" in parsed.message


# -- malformed bodies -------------------------------------------------------


def test_invalid_json_is_a_parse_error() -> None:
    parsed = protocol.parse('```tool\n{"name": "read_file", args: broken}\n```')

    assert isinstance(parsed, protocol.ParseError)
    assert "not valid JSON" in parsed.message


def test_a_non_object_body_is_a_parse_error() -> None:
    parsed = protocol.parse('```tool\n["read_file"]\n```')

    assert isinstance(parsed, protocol.ParseError)
    assert "must be a JSON object" in parsed.message


def test_a_missing_or_blank_name_is_a_parse_error() -> None:
    for body in ('{"args": {}}', '{"name": "", "args": {}}', '{"name": 7}'):
        parsed = protocol.parse(f"```tool\n{body}\n```")
        assert isinstance(parsed, protocol.ParseError), body
        assert "'name'" in parsed.message


def test_non_object_args_is_a_parse_error() -> None:
    parsed = protocol.parse('```tool\n{"name": "read_file", "args": ["a.py"]}\n```')

    assert isinstance(parsed, protocol.ParseError)
    assert "'args' must be a JSON object" in parsed.message


def test_a_malformed_final_block_is_a_parse_error() -> None:
    parsed = protocol.parse('```final\n{"summary": 5}\n```')
    assert isinstance(parsed, protocol.ParseError)

    parsed = protocol.parse('```final\n{"files_changed": "todo.py"}\n```')
    assert isinstance(parsed, protocol.ParseError)
    assert "list of strings" in parsed.message


def test_an_unknown_tool_name_parses_and_is_left_to_the_session() -> None:
    """Deliberate departure from blueprint §7 rule 3: the protocol judges
    syntax, the registry judges names."""
    parsed = protocol.parse(_tool_block("teleport"))

    assert isinstance(parsed, protocol.ToolRequest)
    assert parsed.call.name == "teleport"


# -- no chain-of-thought ----------------------------------------------------


def test_parse_errors_describe_the_fault_without_quoting_the_response() -> None:
    secret_reasoning = "FIRST I WILL SECRETLY PLAN EVERYTHING IN DETAIL"
    parsed = protocol.parse(secret_reasoning)

    assert isinstance(parsed, protocol.ParseError)
    assert secret_reasoning not in parsed.message


def test_a_json_fault_message_does_not_echo_the_body() -> None:
    parsed = protocol.parse('```tool\n{"name": "x", "reasoning": "SECRET PLAN", oops}\n```')

    assert isinstance(parsed, protocol.ParseError)
    assert "SECRET PLAN" not in parsed.message


# -- rendering is deterministic ---------------------------------------------


def test_render_task_is_stable() -> None:
    assert protocol.render_task("  fix the bug  ") == protocol.render_task("fix the bug")
    assert "fix the bug" in protocol.render_task("fix the bug")


def test_render_observation_reports_success() -> None:
    rendered = protocol.render_observation("read_file", ToolResult(ok=True, output="1| x = 1"))

    assert "TOOL RESULT: read_file" in rendered
    assert "status: ok" in rendered
    assert "1| x = 1" in rendered


def test_render_observation_reports_failure_and_exit_code() -> None:
    rendered = protocol.render_observation(
        "run_tests", ToolResult(ok=False, error="not a file: nope.py", exit_code=2)
    )

    assert "status: error" in rendered
    assert "exit_code: 2" in rendered
    assert "not a file: nope.py" in rendered


def test_render_observation_flags_truncation() -> None:
    rendered = protocol.render_observation("read_file", ToolResult(ok=True, output="x", truncated=True))

    assert "truncated: true" in rendered


def test_render_observation_never_prints_none_as_a_diagnosis() -> None:
    rendered = protocol.render_observation("read_file", ToolResult(ok=False, error=None))

    assert "None" not in rendered
    assert "without a message" in rendered


def test_renderers_are_pure_functions() -> None:
    result = ToolResult(ok=True, output="same")
    assert protocol.render_observation("read_file", result) == protocol.render_observation(
        "read_file", result
    )
    assert protocol.render_parse_error("boom", remaining=2) == protocol.render_parse_error(
        "boom", remaining=2
    )


def test_render_parse_error_states_the_remaining_budget() -> None:
    rendered = protocol.render_parse_error("no block found", remaining=2)

    assert "no block found" in rendered
    assert "2 malformed" in rendered
    assert "Nothing was executed" in rendered


# -- system prompt ----------------------------------------------------------


def test_system_prompt_lists_every_registered_tool() -> None:
    prompt = protocol.build_system_prompt(TOOL_REGISTRY)

    for name in TOOL_REGISTRY:
        assert name in prompt


def test_system_prompt_is_generated_from_the_registry_not_a_fixed_list() -> None:
    prompt = protocol.build_system_prompt({"only_this": TOOL_REGISTRY["read_file"]})

    assert "only_this" in prompt
    assert "run_tests" not in prompt


def test_system_prompt_documents_the_grammar() -> None:
    prompt = protocol.build_system_prompt(TOOL_REGISTRY)

    assert "```tool" in prompt
    assert "```final" in prompt
    assert "Exactly one block per turn" in prompt
