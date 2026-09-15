import subprocess
import sys
from pathlib import Path

import pytest

from engine.codeagent.limits import Limits
from engine.codeagent.policy import DEFAULT_POLICY
from engine.codeagent.tools.base import ToolContext
from engine.codeagent.tools.registry import TOOL_REGISTRY, get_tool

_EXPECTED_TOOLS = {
    "list_files",
    "read_file",
    "search_files",
    "write_file",
    "replace_exact",
    "run_command",
    "run_tests",
    "git_diff",
    "git_status",
}


def _ctx(tmp_path: Path, **limit_overrides: object) -> ToolContext:
    root = tmp_path / "ws"
    root.mkdir(exist_ok=True)
    from engine.codeagent.workspace import Workspace

    return ToolContext(
        workspace=Workspace(root),
        policy=DEFAULT_POLICY,
        limits=Limits(**limit_overrides),  # type: ignore[arg-type]
    )


def _write(ctx: ToolContext, relative: str, content: str) -> Path:
    path = ctx.workspace.root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# -- registry ---------------------------------------------------------------


def test_registry_exposes_the_expected_tools() -> None:
    assert set(TOOL_REGISTRY) == _EXPECTED_TOOLS


def test_every_registered_tool_has_a_name_and_description() -> None:
    for key, tool in TOOL_REGISTRY.items():
        assert tool.name == key
        assert tool.description.strip()


def test_get_tool_raises_on_unknown_name() -> None:
    with pytest.raises(ValueError, match="unknown-tool"):
        get_tool("unknown-tool")


# -- list_files -------------------------------------------------------------


def test_list_files_lists_workspace_contents(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    _write(ctx, "todo.py", "x = 1\n")
    _write(ctx, "pkg/mod.py", "y = 2\n")

    result = get_tool("list_files").run({}, ctx)

    assert result.ok
    assert "todo.py" in result.output
    assert "pkg/" in result.output


def test_list_files_hides_secrets_and_noise(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    _write(ctx, "todo.py", "x = 1\n")
    _write(ctx, ".env", "ANTHROPIC_API_KEY=sk-secret\n")
    _write(ctx, "id_rsa", "PRIVATE KEY\n")
    _write(ctx, "__pycache__/mod.pyc", "junk\n")

    result = get_tool("list_files").run({}, ctx)

    assert "todo.py" in result.output
    assert ".env" not in result.output
    assert "id_rsa" not in result.output
    assert "__pycache__" not in result.output


def test_list_files_respects_the_entry_cap(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, max_list_entries=3)
    for i in range(10):
        _write(ctx, f"f{i}.py", "x = 1\n")

    result = get_tool("list_files").run({}, ctx)

    assert "capped at 3 entries" in result.output


def test_list_files_refuses_paths_outside_the_workspace(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    result = get_tool("list_files").run({"path": "../"}, ctx)

    assert not result.ok
    assert "WorkspaceEscape" in (result.error or "")


# -- read_file --------------------------------------------------------------


def test_read_file_returns_numbered_lines(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    _write(ctx, "todo.py", "alpha\nbeta\ngamma\n")

    result = get_tool("read_file").run({"path": "todo.py"}, ctx)

    assert result.ok
    assert "1| alpha" in result.output
    assert "3| gamma" in result.output


def test_read_file_supports_a_line_range(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    _write(ctx, "todo.py", "a\nb\nc\nd\n")

    result = get_tool("read_file").run({"path": "todo.py", "start": 2, "end": 3}, ctx)

    assert "2| b" in result.output
    assert "3| c" in result.output
    assert "a" not in result.output.replace("2| b", "")


def test_read_file_records_the_file_as_inspected(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    _write(ctx, "todo.py", "x = 1\n")

    get_tool("read_file").run({"path": "todo.py"}, ctx)

    assert ctx.workspace.inspected_files == ["todo.py"]


def test_read_file_truncates_above_the_byte_cap(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, max_read_bytes=40, max_tool_output_bytes=10_000)
    _write(ctx, "big.py", "x = 1\n" * 200)

    result = get_tool("read_file").run({"path": "big.py"}, ctx)

    assert result.ok
    assert "read capped at 40 B" in result.output


def test_read_file_refuses_secrets(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    _write(ctx, ".env", "ANTHROPIC_API_KEY=sk-secret\n")

    result = get_tool("read_file").run({"path": ".env"}, ctx)

    assert not result.ok
    assert "ForbiddenPath" in (result.error or "")
    assert "sk-secret" not in result.output


def test_read_file_reports_a_missing_file_without_raising(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    result = get_tool("read_file").run({"path": "nope.py"}, ctx)

    assert not result.ok
    assert "not a file" in (result.error or "")


def test_read_file_requires_a_path_argument(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    result = get_tool("read_file").run({}, ctx)

    assert not result.ok
    assert "missing required argument" in (result.error or "")


# -- search_files -----------------------------------------------------------


def test_search_files_finds_matches_with_locations(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    _write(ctx, "todo.py", "def parse_due_date(raw):\n    return raw\n")
    _write(ctx, "other.py", "x = 1\n")

    result = get_tool("search_files").run({"pattern": "parse_due_date"}, ctx)

    assert result.ok
    assert "todo.py:1:" in result.output
    assert "other.py" not in result.output


def test_search_files_never_surfaces_secret_files(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    _write(ctx, ".env", "TOKEN=sk-supersecret\n")
    _write(ctx, "app.py", "TOKEN = 'placeholder'\n")

    result = get_tool("search_files").run({"pattern": "TOKEN", "suffix": ""}, ctx)

    assert "sk-supersecret" not in result.output
    assert ".env" not in result.output


def test_search_files_supports_regex_and_reports_bad_patterns(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    _write(ctx, "todo.py", "def alpha():\n    pass\n")

    hit = get_tool("search_files").run({"pattern": r"def \w+", "regex": True}, ctx)
    assert hit.ok
    assert "todo.py:1:" in hit.output

    bad = get_tool("search_files").run({"pattern": "([", "regex": True}, ctx)
    assert not bad.ok
    assert "invalid regex" in (bad.error or "")


def test_search_files_caps_results(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, max_search_results=2, max_tool_output_bytes=10_000)
    _write(ctx, "todo.py", "needle\n" * 20)

    result = get_tool("search_files").run({"pattern": "needle"}, ctx)

    assert "capped at 2 matches" in result.output


# -- write_file -------------------------------------------------------------


def test_write_file_creates_a_new_file_and_records_the_change(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    result = get_tool("write_file").run({"path": "new.py", "content": "x = 1\n"}, ctx)

    assert result.ok
    assert (ctx.workspace.root / "new.py").read_text(encoding="utf-8") == "x = 1\n"
    assert ctx.workspace.changed_files == ["new.py"]


def test_write_file_refuses_to_clobber_without_overwrite(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    _write(ctx, "todo.py", "original\n")

    result = get_tool("write_file").run({"path": "todo.py", "content": "replaced\n"}, ctx)

    assert not result.ok
    assert "already exists" in (result.error or "")
    assert (ctx.workspace.root / "todo.py").read_text(encoding="utf-8") == "original\n"


def test_write_file_allows_explicit_overwrite(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    _write(ctx, "todo.py", "original\n")

    result = get_tool("write_file").run(
        {"path": "todo.py", "content": "replaced\n", "overwrite": True}, ctx
    )

    assert result.ok
    assert (ctx.workspace.root / "todo.py").read_text(encoding="utf-8") == "replaced\n"


def test_write_file_refuses_to_empty_a_non_empty_file(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    _write(ctx, "todo.py", "important code\n")

    result = get_tool("write_file").run(
        {"path": "todo.py", "content": "   ", "overwrite": True}, ctx
    )

    assert not result.ok
    assert "truncate" in (result.error or "")
    assert (ctx.workspace.root / "todo.py").read_text(encoding="utf-8") == "important code\n"


def test_write_file_respects_the_size_cap(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, max_write_bytes=10)
    result = get_tool("write_file").run({"path": "big.py", "content": "x" * 100}, ctx)

    assert not result.ok
    assert "max_write_bytes" in (result.error or "")
    assert not (ctx.workspace.root / "big.py").exists()


def test_write_file_refuses_to_escape_the_workspace(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    result = get_tool("write_file").run({"path": "../escape.py", "content": "x = 1\n"}, ctx)

    assert not result.ok
    assert not (tmp_path / "escape.py").exists()


def test_write_file_refuses_secret_targets(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    result = get_tool("write_file").run({"path": ".env", "content": "KEY=1\n"}, ctx)

    assert not result.ok
    assert "ForbiddenPath" in (result.error or "")
    assert not (ctx.workspace.root / ".env").exists()


def test_write_file_enforces_max_files_changed(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    from engine.codeagent.workspace import Workspace

    ctx = ToolContext(
        workspace=Workspace(root, max_files_changed=2),
        policy=DEFAULT_POLICY,
        limits=Limits(),
    )
    assert get_tool("write_file").run({"path": "a.py", "content": "1\n"}, ctx).ok
    assert get_tool("write_file").run({"path": "b.py", "content": "1\n"}, ctx).ok

    third = get_tool("write_file").run({"path": "c.py", "content": "1\n"}, ctx)

    assert not third.ok
    assert "TooManyFilesChanged" in (third.error or "")
    assert not (root / "c.py").exists()


# -- replace_exact ----------------------------------------------------------


def test_replace_exact_applies_a_single_unique_match(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    _write(ctx, "todo.py", "def f():\n    return 1\n")

    result = get_tool("replace_exact").run(
        {"path": "todo.py", "find": "return 1", "replace": "return 2"}, ctx
    )

    assert result.ok
    assert "replaced 1 occurrence" in result.output
    assert (ctx.workspace.root / "todo.py").read_text(encoding="utf-8") == "def f():\n    return 2\n"
    assert ctx.workspace.changed_files == ["todo.py"]


def test_replace_exact_rejects_zero_matches(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    _write(ctx, "todo.py", "def f():\n    return 1\n")

    result = get_tool("replace_exact").run(
        {"path": "todo.py", "find": "return 99", "replace": "return 2"}, ctx
    )

    assert not result.ok
    assert "anchor not found" in (result.error or "")
    assert (ctx.workspace.root / "todo.py").read_text(encoding="utf-8") == "def f():\n    return 1\n"
    assert ctx.workspace.changed_files == []


def test_replace_exact_rejects_multiple_matches_and_names_the_count(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    original = "x = 1\ny = 1\nz = 1\n"
    _write(ctx, "todo.py", original)

    result = get_tool("replace_exact").run(
        {"path": "todo.py", "find": "= 1", "replace": "= 2"}, ctx
    )

    assert not result.ok
    assert "occurs 3 times" in (result.error or "")
    assert "NOT applied" in (result.error or "")
    # The decisive assertion: nothing was changed, not even the first match.
    assert (ctx.workspace.root / "todo.py").read_text(encoding="utf-8") == original
    assert ctx.workspace.changed_files == []


def test_replace_exact_refuses_an_empty_anchor(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    _write(ctx, "todo.py", "x = 1\n")

    result = get_tool("replace_exact").run({"path": "todo.py", "find": "", "replace": "y"}, ctx)

    assert not result.ok
    assert "must not be empty" in (result.error or "")


def test_replace_exact_blocks_mass_deletion(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, max_delete_bytes=20)
    body = "line\n" * 50
    _write(ctx, "todo.py", body)

    result = get_tool("replace_exact").run({"path": "todo.py", "find": body, "replace": ""}, ctx)

    assert not result.ok
    assert "max_delete_bytes" in (result.error or "")
    assert (ctx.workspace.root / "todo.py").read_text(encoding="utf-8") == body


def test_replace_exact_allows_a_small_deletion(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, max_delete_bytes=2_000)
    _write(ctx, "todo.py", "keep\nremove me\n")

    result = get_tool("replace_exact").run(
        {"path": "todo.py", "find": "remove me\n", "replace": ""}, ctx
    )

    assert result.ok
    assert (ctx.workspace.root / "todo.py").read_text(encoding="utf-8") == "keep\n"


def test_replace_exact_refuses_paths_outside_the_workspace(tmp_path: Path) -> None:
    outside = tmp_path / "outside.py"
    outside.write_text("secret\n", encoding="utf-8")
    ctx = _ctx(tmp_path)

    result = get_tool("replace_exact").run(
        {"path": "../outside.py", "find": "secret", "replace": "leaked"}, ctx
    )

    assert not result.ok
    assert outside.read_text(encoding="utf-8") == "secret\n"


# -- run_command ------------------------------------------------------------


def test_run_command_really_runs_the_process(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    result = get_tool("run_command").run({"argv": ["python", "-c", "print(41 + 1)"]}, ctx)

    assert result.ok
    assert result.exit_code == 0
    assert "42" in result.output


def test_run_command_reports_a_real_non_zero_exit(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    result = get_tool("run_command").run(
        {"argv": ["python", "-c", "raise SystemExit(3)"]}, ctx
    )

    # The tool did its job; the command failed. Those are different facts.
    assert result.ok
    assert result.exit_code == 3


def test_run_command_surfaces_stderr(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    result = get_tool("run_command").run(
        {"argv": ["python", "-c", "__import__('sys').stderr.write('boom')"]}, ctx
    )

    assert result.ok
    assert "boom" in result.output
    assert "stderr" in result.output


def test_run_command_times_out(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, command_timeout_seconds=0.5)
    result = get_tool("run_command").run(
        {"argv": ["python", "-c", "__import__('time').sleep(30)"]}, ctx
    )

    assert not result.ok
    assert "timed out after 0.5s" in (result.error or "")


def test_run_command_runs_inside_the_workspace(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    result = get_tool("run_command").run(
        {"argv": ["python", "-c", "print(__import__('os').getcwd())"]}, ctx
    )

    assert result.ok
    assert str(ctx.workspace.root) in result.output


def test_run_command_scrubs_credentials_from_the_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-should-not-leak")
    ctx = _ctx(tmp_path)

    result = get_tool("run_command").run(
        {
            "argv": [
                "python",
                "-c",
                "print(__import__('os').environ.get('ANTHROPIC_API_KEY', 'ABSENT'))",
            ]
        },
        ctx,
    )

    assert result.ok
    assert "ABSENT" in result.output
    assert "sk-ant-should-not-leak" not in result.output


def test_run_command_denies_a_shell_string_argv(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    result = get_tool("run_command").run({"argv": "python -c 'print(1)'"}, ctx)

    assert not result.ok
    assert "list of strings" in (result.error or "")


def test_run_command_denies_git_push(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    result = get_tool("run_command").run({"argv": ["git", "push"]}, ctx)

    assert not result.ok
    assert "CommandDenied" in (result.error or "")


def test_run_command_denies_reset_hard(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    result = get_tool("run_command").run({"argv": ["git", "reset", "--hard"]}, ctx)

    assert not result.ok
    assert "CommandDenied" in (result.error or "")


def test_run_command_truncates_large_output(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, max_tool_output_bytes=200)
    result = get_tool("run_command").run(
        {"argv": ["python", "-c", "print('x' * 5000)"]}, ctx
    )

    assert result.ok
    assert result.truncated
    assert "truncated" in result.output


# -- run_tests --------------------------------------------------------------


def test_run_tests_executes_the_workspace_suite(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    _write(ctx, "test_sample.py", "def test_passes():\n    assert True\n")

    result = get_tool("run_tests").run({}, ctx)

    assert result.ok
    assert result.exit_code == 0


def test_run_tests_reports_a_real_failure(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, max_tool_output_bytes=20_000)
    _write(ctx, "test_sample.py", "def test_fails():\n    assert 1 == 2\n")

    result = get_tool("run_tests").run({}, ctx)

    assert result.ok
    assert result.exit_code != 0
    assert "test_fails" in result.output


# -- git tools --------------------------------------------------------------


def _git_repo_or_skip(root: Path) -> None:
    try:
        subprocess.run(
            ["git", "init", "-q"], cwd=root, capture_output=True, timeout=30, check=True
        )
    except (OSError, subprocess.SubprocessError):
        pytest.skip("git is not available")


def test_git_status_reports_untracked_work(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    _git_repo_or_skip(ctx.workspace.root)
    _write(ctx, "todo.py", "x = 1\n")

    result = get_tool("git_status").run({}, ctx)

    assert result.ok
    assert "todo.py" in result.output


def test_git_diff_runs_and_accepts_stat(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    _git_repo_or_skip(ctx.workspace.root)

    plain = get_tool("git_diff").run({}, ctx)
    stat = get_tool("git_diff").run({"stat": True}, ctx)

    assert plain.ok
    assert stat.ok


def test_run_command_uses_the_environments_own_interpreter(tmp_path: Path) -> None:
    """'python' normalizes to sys.executable, so a PATH-shadowing 'python'
    cannot be selected by the agent."""
    ctx = _ctx(tmp_path)
    result = get_tool("run_command").run(
        {"argv": ["python", "-c", "print(__import__('sys').executable)"]}, ctx
    )

    assert result.ok
    assert sys.executable in result.output
