"""`engine debug`: argument handling, exit codes, and JSON output.

Two properties this file exists to hold, both learned the hard way:

**Commands are argv, never shell strings.** There is no code path from a CLI
argument to a shell, so nothing a caller types can be word-split, glob-expanded
or interpreted by a shell. Each ``--repro``/``--suite`` occurrence contributes
exactly one argv token, verbatim.

**The documented invocation must survive PowerShell 5.1.** Its native-argument
handling mangles embedded double quotes, which cost the Coding Agent a live
demo. The forms tested here are the ones that survive it: ``--flag=value`` for
every command token (mandatory when the token starts with ``-``, because
argparse would otherwise read it as an option), and ``--task-file`` for a bug
report containing quotes.

Offline: the gateway is replaced, so no key and no network.
"""

import ast
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from codeagent_harness import (
    CLEAN_CRITIC,
    DebugScenarioProvider,
    critic,
    final_turn,
    rootcause_block,
    tool_turn,
)

from engine import cli
from engine.debugagent.app import (
    DEFAULT_SUITE_ARGV,
    EXIT_ERROR,
    EXIT_UNVERIFIED,
    EXIT_VERIFIED,
)
from engine.runtime.gateway import LLMGateway
from engine.verification.judge import LENSES

FIXTURES = Path(__file__).resolve().parent.parent / "examples"
LENS_PROMPTS = tuple(LENSES.values())

BUG = "Asking for the total of an empty cart crashes instead of returning shipping."
# One token per flag, in the =value form -- the spelling the docs use, and the
# only one that works for tokens beginning with '-'.
REPRO_FLAGS = [
    "--repro=python",
    "--repro=-m",
    "--repro=pytest",
    "--repro=-q",
    "--repro=tests/test_cart.py::test_empty_cart_is_shipping_only",
]
REPRO_ARGV = ["python", "-m", "pytest", "-q", "tests/test_cart.py::test_empty_cart_is_shipping_only"]

DIAGNOSIS = rootcause_block(
    summary="the bulk discount computes the cheapest price before checking the cart has contents",
    mechanism="min() runs over an empty generator because the BULK_UNITS check comes after it",
    primary_file="cart.py",
    primary_line=24,
    proposed_fix="take the BULK_UNITS check first",
)
GOOD_FIX = tool_turn(
    "replace_exact",
    {
        "path": "cart.py",
        "find": (
            "    cheapest = min(item.price for item in items)\n"
            "    if sum(item.qty for item in items) < BULK_UNITS:\n"
            "        return 0.0\n"
        ),
        "replace": (
            "    if sum(item.qty for item in items) < BULK_UNITS:\n"
            "        return 0.0\n"
            "    cheapest = min(item.price for item in items)\n"
        ),
    },
)
SOLVE_TURNS = [GOOD_FIX, final_turn("moved the guard ahead of min()", ["cart.py"])]


def fixture_copy(tmp_path: Path) -> Path:
    workspace = tmp_path / "ws"
    shutil.copytree(
        FIXTURES / "cart_bug", workspace, ignore=shutil.ignore_patterns("__pycache__")
    )
    return workspace


def provider(
    *, judge_rounds: list[str] | None = None, fix_turns: list[str] | None = None
) -> DebugScenarioProvider:
    return DebugScenarioProvider(
        diagnosis_turns=[DIAGNOSIS],
        fix_turns=fix_turns or SOLVE_TURNS,
        judge_rounds=judge_rounds or [CLEAN_CRITIC],
        lens_prompts=LENS_PROMPTS,
    )


class _GatewayFactory:
    """Stands in for LLMGateway in cli.py so no API key is needed."""

    def __init__(self, fake: DebugScenarioProvider) -> None:
        self._fake = fake

    def from_config(self, provider_name: str, config: object) -> LLMGateway:
        return LLMGateway(self._fake)


def invoke_cli(
    monkeypatch, argv: list[str], fake: DebugScenarioProvider, tmp_path: Path
) -> int:
    monkeypatch.setenv("ENGINE_DB_PATH", str(tmp_path / "state.db"))
    monkeypatch.setattr(cli, "LLMGateway", _GatewayFactory(fake))
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as exc:
        cli.main()
    return int(exc.value.code or 0)


def base_argv(workspace: Path, *extra: str) -> list[str]:
    return [
        "engine", "debug", BUG,
        "--workspace", str(workspace),
        *REPRO_FLAGS,
        *extra,
    ]


# -- argv construction -------------------------------------------------------


def test_repeated_flags_become_one_argv_list_verbatim(monkeypatch, tmp_path: Path) -> None:
    workspace = fixture_copy(tmp_path)
    json_path = tmp_path / "report.json"

    code = invoke_cli(
        monkeypatch,
        base_argv(workspace, "--json", str(json_path)),
        provider(),
        tmp_path,
    )

    assert code == EXIT_VERIFIED
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["repro_command"] == REPRO_ARGV
    # No --suite given, so the documented default is applied and is visible.
    assert payload["suite_command"] == ["python", "-m", "pytest", "-q"]
    assert payload["suite_command"] == list(DEFAULT_SUITE_ARGV)


def test_a_custom_suite_is_taken_token_by_token(monkeypatch, tmp_path: Path) -> None:
    workspace = fixture_copy(tmp_path)
    json_path = tmp_path / "report.json"

    invoke_cli(
        monkeypatch,
        base_argv(
            workspace,
            "--suite=python", "--suite=-m", "--suite=pytest", "--suite=-q", "--suite=tests",
            "--json", str(json_path),
        ),
        provider(),
        tmp_path,
    )

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["suite_command"] == ["python", "-m", "pytest", "-q", "tests"]


def test_a_shell_metacharacter_in_a_token_is_refused_not_interpreted(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    """The token reaches the policy as one string; nothing splits it on ';'."""
    workspace = fixture_copy(tmp_path)

    code = invoke_cli(
        monkeypatch,
        [
            "engine", "debug", BUG,
            "--workspace", str(workspace),
            "--repro=python", "--repro=-m", "--repro=pytest; rm -rf /",
        ],
        provider(),
        tmp_path,
    )

    out = capsys.readouterr().out
    assert code == EXIT_ERROR
    # Refused by the command policy as a single argv token, not split on ';'.
    assert "DENIED" in out
    assert "ABORTED_NO_REPRO" in out


def test_repro_is_required(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        sys, "argv", ["engine", "debug", BUG, "--workspace", str(fixture_copy(tmp_path))]
    )
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2  # argparse usage error


def test_workspace_is_required(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "argv", ["engine", "debug", BUG, *REPRO_FLAGS])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2


# -- the bug report ----------------------------------------------------------


def test_the_bug_report_can_come_from_a_file(monkeypatch, tmp_path: Path) -> None:
    """The PowerShell escape hatch: a file has no quoting rules at all."""
    workspace = fixture_copy(tmp_path)
    task_file = tmp_path / "bug.txt"
    task_file.write_text(
        'cart_total([]) raises ValueError: min() arg is an empty sequence -- '
        'the "empty basket" page 500s.\n',
        encoding="utf-8",
    )
    json_path = tmp_path / "report.json"

    code = invoke_cli(
        monkeypatch,
        [
            "engine", "debug",
            "--workspace", str(workspace),
            "--task-file", str(task_file),
            *REPRO_FLAGS,
            "--json", str(json_path),
        ],
        provider(),
        tmp_path,
    )

    assert code == EXIT_VERIFIED
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    # Embedded double quotes survive verbatim -- the thing PowerShell mangles.
    assert '"empty basket"' in payload["reported_bug"]


def test_both_bug_report_sources_is_a_usage_error(monkeypatch, tmp_path: Path) -> None:
    task_file = tmp_path / "bug.txt"
    task_file.write_text("something", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "engine", "debug", BUG,
            "--workspace", str(fixture_copy(tmp_path)),
            "--task-file", str(task_file),
            *REPRO_FLAGS,
        ],
    )
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2


def test_no_bug_report_at_all_is_a_usage_error(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["engine", "debug", "--workspace", str(fixture_copy(tmp_path)), *REPRO_FLAGS],
    )
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2


def test_a_missing_task_file_is_a_usage_error(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "engine", "debug",
            "--workspace", str(fixture_copy(tmp_path)),
            "--task-file", str(tmp_path / "nope.txt"),
            *REPRO_FLAGS,
        ],
    )
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2


# -- exit codes --------------------------------------------------------------


def test_exit_zero_when_proven_and_verified(monkeypatch, capsys, tmp_path: Path) -> None:
    workspace = fixture_copy(tmp_path)

    code = invoke_cli(monkeypatch, base_argv(workspace), provider(), tmp_path)

    out = capsys.readouterr().out
    assert code == EXIT_VERIFIED
    assert "PASSED" in out
    assert "-- observed" in out and "-- claimed by the model" in out
    source = (workspace / "cart.py").read_text(encoding="utf-8")
    assert source.index("< BULK_UNITS") < source.index("cheapest = min(")


def test_exit_one_when_agentgate_blocks(monkeypatch, capsys, tmp_path: Path) -> None:
    blocked = critic(
        [
            {
                "id": "C1",
                "category": "SECURITY",
                "severity": "CRITICAL",
                "location": "cart.py:24",
                "fix": "do not do that",
            }
        ]
    )

    code = invoke_cli(
        monkeypatch,
        base_argv(fixture_copy(tmp_path), "--max-repairs", "0"),
        provider(judge_rounds=[blocked]),
        tmp_path,
    )

    assert code == EXIT_UNVERIFIED
    assert "UNVERIFIED" in capsys.readouterr().out


def test_exit_one_when_the_fix_is_not_proven(monkeypatch, capsys, tmp_path: Path) -> None:
    code = invoke_cli(
        monkeypatch,
        base_argv(fixture_copy(tmp_path), "--max-repairs", "0"),
        provider(fix_turns=[final_turn("fixed it", ["cart.py"])]),
        tmp_path,
    )

    assert code == EXIT_UNVERIFIED
    assert "UNPROVEN" in capsys.readouterr().out


def test_exit_two_when_the_failure_does_not_reproduce(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    fake = provider()

    code = invoke_cli(
        monkeypatch,
        [
            "engine", "debug", BUG,
            "--workspace", str(fixture_copy(tmp_path)),
            "--repro=python", "--repro=-m", "--repro=pytest", "--repro=-q",
            "--repro=tests/test_cart.py::test_shipping_is_always_added",
        ],
        fake,
        tmp_path,
    )

    assert code == EXIT_ERROR
    assert "ABORTED_NO_REPRO" in capsys.readouterr().out
    assert fake.model_calls == 0


def test_exit_two_on_a_bad_workspace(monkeypatch, capsys, tmp_path: Path) -> None:
    code = invoke_cli(
        monkeypatch,
        [
            "engine", "debug", BUG,
            "--workspace", str(tmp_path / "nope"),
            *REPRO_FLAGS,
        ],
        provider(),
        tmp_path,
    )

    assert code == EXIT_ERROR
    assert "ERROR" in capsys.readouterr().out


# -- output ------------------------------------------------------------------


def test_json_is_written_and_machine_readable(monkeypatch, tmp_path: Path) -> None:
    json_path = tmp_path / "report.json"

    invoke_cli(
        monkeypatch,
        base_argv(fixture_copy(tmp_path), "--json", str(json_path)),
        provider(),
        tmp_path,
    )

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["status"] == "PASSED"
    assert payload["observed"]["files_changed"] == ["cart.py"]
    assert payload["observed"]["proof_status"] == "PROVEN"
    assert payload["agentgate"]["status"] == "OK"
    assert payload["claimed"]["root_cause"]["primary_file"] == "cart.py"
    # No prompts, no reasoning text, no raw model output.
    raw = json_path.read_text(encoding="utf-8")
    assert "```" not in raw
    assert "You are a debugging agent" not in raw


def test_limit_flags_reach_the_session(monkeypatch, tmp_path: Path) -> None:
    """--max-turns 1 stops the session after one turn -- and the gate still runs.

    A session that hit its ceiling can still have fixed the bug, so the proof
    commands are run either way and decide on their own. This is the two-status
    separation from the other direction: ABORTED_TURNS is how the loop ended,
    PROVEN is what the commands found.
    """
    json_path = tmp_path / "report.json"
    fake = provider()

    code = invoke_cli(
        monkeypatch,
        base_argv(fixture_copy(tmp_path), "--max-turns", "1", "--json", str(json_path)),
        fake,
        tmp_path,
    )

    assert fake.fix_calls == 1
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["observed"]["fix_session_status"] == "ABORTED_TURNS"
    assert payload["observed"]["proof_status"] == "PROVEN"
    assert code == EXIT_VERIFIED


# -- agent / benchmark isolation ---------------------------------------------
#
# `engine bench` is the measured path. Nothing on it may reach an agent package,
# and "reach" includes an import performed while the argument parser is built --
# which happens for every subcommand, before the chosen one is known.
#
# These tests are structural and out-of-process rather than sys.modules
# assertions made here, because this file has already imported
# engine.debugagent at the top and so has every other D4 suite. A test that
# checked sys.modules in-process would pass or fail on collection order.

CLI_SOURCE = Path(cli.__file__)
REPO_ROOT = CLI_SOURCE.resolve().parent.parent.parent

_PROBE = """
import sys
sys.argv = {argv!r}
import engine.cli
try:
    engine.cli.main()
except SystemExit:
    pass
except BaseException as exc:
    print("PROBE_ERROR=" + type(exc).__name__ + ": " + str(exc))
leaked = sorted(
    name for name in sys.modules
    if name == "engine.debugagent" or name.startswith("engine.debugagent.")
)
print("DEBUGAGENT_MODULES=" + ",".join(leaked))
"""


def _probe(argv: list[str], tmp_path: Path) -> str:
    """Run one CLI invocation in a fresh interpreter and report what it imported."""
    env = dict(os.environ)
    env["ENGINE_DB_PATH"] = str(tmp_path / "state.db")
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    result = subprocess.run(
        [sys.executable, "-c", _PROBE.format(argv=argv)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        check=False,
    )
    assert "PROBE_ERROR" not in result.stdout, result.stdout + result.stderr
    for line in result.stdout.splitlines():
        if line.startswith("DEBUGAGENT_MODULES="):
            return line.partition("=")[2]
    raise AssertionError(f"probe produced no verdict:\n{result.stdout}\n{result.stderr}")


def test_parser_construction_alone_does_not_import_debugagent(tmp_path: Path) -> None:
    """No subcommand chosen: every parser is fully built, then argparse rejects."""
    assert _probe(["engine"], tmp_path) == ""


def test_bench_dry_run_does_not_import_debugagent(tmp_path: Path) -> None:
    """The measured path, exercised for real -- dataset validation, zero LLM calls."""
    assert _probe(["engine", "bench", "--dry-run"], tmp_path) == ""


def _selects_debug(test: ast.expr) -> bool:
    return (
        isinstance(test, ast.Compare)
        and isinstance(test.left, ast.Attribute)
        and test.left.attr == "command"
        and isinstance(test.left.value, ast.Name)
        and test.left.value.id == "args"
        and len(test.comparators) == 1
        and isinstance(test.comparators[0], ast.Constant)
        and test.comparators[0].value == "debug"
    )


def test_every_debugagent_import_sits_inside_the_debug_branch() -> None:
    """Structural guard: no debugagent import can run before `debug` is chosen.

    Asserted over the AST rather than by line numbers, so moving the branch or
    reformatting cannot silently weaken it.
    """
    tree = ast.parse(CLI_SOURCE.read_text(encoding="utf-8"), filename=str(CLI_SOURCE))

    branch = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.If) and _selects_debug(node.test)
        ),
        None,
    )
    assert branch is not None, "no `args.command == debug` branch found in cli.py"
    inside = {id(node) for node in ast.walk(branch)}

    outside = [
        f"line {node.lineno}: imports {node.module!r}"
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module is not None
        and (node.module == "engine.debugagent" or node.module.startswith("engine.debugagent."))
        and id(node) not in inside
    ]
    outside += [
        f"line {node.lineno}: imports {alias.name!r}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
        if (alias.name == "engine.debugagent" or alias.name.startswith("engine.debugagent."))
        and id(node) not in inside
    ]

    assert not outside, (
        "every engine.debugagent import in cli.py must sit inside the debug branch -- "
        "an import outside it runs while the parser is built, which puts the Debug "
        "Agent on `engine bench`'s import path:\n" + "\n".join(outside)
    )


def test_the_documented_suite_default_matches_the_constant(
    monkeypatch, capsys
) -> None:
    """The --suite help literal and the real default are two copies, on purpose.

    The help string is rendered while the parser is built, and reading the
    constant there would import the Debug Agent for every subcommand. This test
    is what keeps the copies honest. The *applied* value is asserted separately,
    by test_repeated_flags_become_one_argv_list_verbatim running a real command.
    """
    assert list(DEFAULT_SUITE_ARGV) == ["python", "-m", "pytest", "-q"]

    monkeypatch.setattr(sys, "argv", ["engine", "debug", "--help"])
    with pytest.raises(SystemExit):
        cli.main()

    assert "Default: " + " ".join(DEFAULT_SUITE_ARGV) in capsys.readouterr().out
