"""D3: the minimal fix, and the proof that it worked.

The rule this suite exists to prove: **the model's word never decides success.**
A fixing session can end with a confident "fixed"; if the frozen reproduction
still fails, or the full suite breaks, the harness reports UNPROVEN. Every
success claim in this phase is a command exit code, not a sentence.

Offline throughout: real temporary workspaces, real subprocesses for the proof
commands, scripted providers for every model turn.
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest
from codeagent_harness import MODEL, ScriptedProvider, final_turn, tool_turn

from engine.codeagent.limits import Limits
from engine.codeagent.log import SessionLog
from engine.codeagent.policy import DEFAULT_POLICY
from engine.codeagent.state import SessionStatus
from engine.codeagent.workspace import Workspace
from engine.debugagent.evidence import build_evidence
from engine.debugagent.fix import (
    DEBUG_FIX_TOOLS,
    FixOutcome,
    ProofStatus,
    run_fix_loop,
)
from engine.debugagent.limits import DEBUG_LIMITS
from engine.debugagent.repro import freeze_repro, reproduce
from engine.debugagent.rootcause import Confidence, RootCause
from engine.debugagent.tools.repro import RunReproTool
from engine.runtime.budget import BudgetController
from engine.runtime.gateway import LLMGateway

# average([]) raises ZeroDivisionError. The fix is a two-line guard.
BUGGY = "def average(values):\n    return sum(values) / len(values)\n"
FIXED = (
    "def average(values):\n"
    "    if not values:\n"
    "        return 0\n"
    "    return sum(values) / len(values)\n"
)
# A second test that a careless fix breaks -- this is what the suite gate is for.
TESTS = (
    "from calc import average\n"
    "\n"
    "\n"
    "def test_empty_returns_zero() -> None:\n"
    "    assert average([]) == 0\n"
    "\n"
    "\n"
    "def test_average_of_numbers() -> None:\n"
    "    assert average([2, 4]) == 3\n"
)

REPRO_ARGV = ["python", "-m", "pytest", "-q", "tests/test_calc.py::test_empty_returns_zero"]
SUITE_ARGV = ["python", "-m", "pytest", "-q"]


def _ws(tmp_path: Path, calc: str = BUGGY) -> Workspace:
    root = tmp_path / "ws"
    (root / "tests").mkdir(parents=True, exist_ok=True)
    (root / "calc.py").write_text(calc, encoding="utf-8")
    (root / "tests" / "test_calc.py").write_text(TESTS, encoding="utf-8")
    (root / "conftest.py").write_text(
        "import sys\nfrom pathlib import Path\n\nsys.path.insert(0, str(Path(__file__).parent))\n",
        encoding="utf-8",
    )
    return Workspace(root, max_files_changed=DEBUG_LIMITS.max_files_changed)


def _evidence(ws: Workspace):
    outcome = reproduce(
        repro=freeze_repro(REPRO_ARGV),
        workspace=ws,
        policy=DEFAULT_POLICY,
        limits=Limits(repro_timeout_seconds=60),
    )
    assert outcome.reproduced, outcome.reason
    assert outcome.evidence is not None
    return outcome.evidence


def _root_cause(**overrides: object) -> RootCause:
    fields: dict = {
        "summary": "average divides by len(values) without guarding the empty case",
        "mechanism": "an empty list makes len(values) zero, so the division raises",
        "primary_file": "calc.py",
        "primary_line": 2,
        "proposed_fix": "return 0 for an empty sequence before dividing",
        "confidence": Confidence.OBSERVED,
        "related_files": [],
        "evidence_refs": ["traceback names calc.py:2"],
        "validation_plan": [SUITE_ARGV],
    }
    fields.update(overrides)
    return RootCause(**fields)  # type: ignore[arg-type]


# The edit that actually fixes it, as an anchored replacement.
FIX_TURN = tool_turn(
    "replace_exact",
    {
        "path": "calc.py",
        "find": "def average(values):\n    return sum(values) / len(values)",
        "replace": "def average(values):\n    if not values:\n        return 0\n    return sum(values) / len(values)",
    },
)
# Fixes the targeted test, breaks the other one.
BAD_FIX_TURN = tool_turn(
    "replace_exact",
    {
        "path": "calc.py",
        "find": "def average(values):\n    return sum(values) / len(values)",
        "replace": "def average(values):\n    return 0",
    },
)
DONE = final_turn("fixed the empty-cart crash", ["calc.py"])


def _run(
    tmp_path: Path,
    turns: list[str],
    *,
    ws: Workspace | None = None,
    root_cause: RootCause | None = None,
    limits: Limits | None = None,
    log: SessionLog | None = None,
    suite_argv: list[str] | None = None,
    max_tokens: int = 1_000_000,
) -> tuple[FixOutcome, ScriptedProvider]:
    workspace = ws if ws is not None else _ws(tmp_path)
    evidence = _evidence(workspace)
    provider = ScriptedProvider(turns)
    outcome = run_fix_loop(
        task_text="average() crashes on an empty list",
        evidence=evidence,
        root_cause=root_cause if root_cause is not None else _root_cause(),
        repro=freeze_repro(REPRO_ARGV),
        suite_argv=suite_argv if suite_argv is not None else SUITE_ARGV,
        workspace=workspace,
        gateway=LLMGateway(provider),
        budget=BudgetController(max_tokens=max_tokens, planned_budget=Decimal("10.00")),
        model=MODEL,
        task_id="dbg-fix",
        limits=limits if limits is not None else DEBUG_LIMITS,
        policy=DEFAULT_POLICY,
        log=log,
    )
    return outcome, provider


# -- the happy path ---------------------------------------------------------


def test_minimal_fix_is_proven(tmp_path: Path) -> None:
    outcome, _ = _run(tmp_path, [FIX_TURN, DONE])

    assert outcome.status is ProofStatus.PROVEN
    assert outcome.proof is not None
    assert outcome.proof.repro_after is not None
    assert outcome.proof.repro_after.exit_code == 0
    assert outcome.proof.suite_after is not None
    assert outcome.proof.suite_after.exit_code == 0
    assert outcome.repairs_used == 0


def test_proven_fix_actually_changed_the_file(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    outcome, _ = _run(tmp_path, [FIX_TURN, DONE], ws=ws)

    assert outcome.files_changed == ["calc.py"]
    assert "if not values" in (ws.root / "calc.py").read_text(encoding="utf-8")


def test_files_changed_comes_from_the_ledger_not_the_model(tmp_path: Path) -> None:
    """The model claims three files; the ledger knows it touched one."""
    lying = final_turn("rewrote everything", ["calc.py", "ghost.py", "invented.py"])
    outcome, _ = _run(tmp_path, [FIX_TURN, lying])

    assert outcome.files_changed == ["calc.py"]


# -- the model's word is not proof -----------------------------------------


def test_claiming_fixed_without_editing_is_not_proven(tmp_path: Path) -> None:
    outcome, _ = _run(tmp_path, [DONE])

    assert outcome.status is ProofStatus.UNPROVEN
    assert outcome.files_changed == []


def test_claiming_fixed_while_repro_still_fails_is_not_proven(tmp_path: Path) -> None:
    """A cosmetic edit plus a confident summary must not read as success."""
    cosmetic = tool_turn(
        "replace_exact",
        {
            "path": "calc.py",
            "find": "def average(values):",
            "replace": "def average(values):  # handles empty input",
        },
    )
    outcome, _ = _run(tmp_path, [cosmetic, DONE, cosmetic, DONE, cosmetic, DONE])

    assert outcome.status is ProofStatus.UNPROVEN
    assert outcome.proof is not None
    assert outcome.proof.repro_after is not None
    assert outcome.proof.repro_after.exit_code != 0


def test_repro_passing_but_suite_failing_is_not_proven(tmp_path: Path) -> None:
    """The classic debug failure: the targeted test goes green, a neighbour breaks."""
    outcome, _ = _run(
        tmp_path, [BAD_FIX_TURN, DONE, BAD_FIX_TURN, DONE, BAD_FIX_TURN, DONE]
    )

    assert outcome.status is ProofStatus.UNPROVEN
    assert outcome.proof is not None
    assert outcome.proof.repro_after is not None
    assert outcome.proof.repro_after.exit_code == 0
    assert outcome.proof.suite_after is not None
    assert outcome.proof.suite_after.exit_code != 0


def test_suite_is_not_run_when_the_repro_still_fails(tmp_path: Path) -> None:
    """No point asking the suite: the bug it was sent to fix is still there."""
    cosmetic = tool_turn(
        "replace_exact",
        {"path": "calc.py", "find": "def average(values):", "replace": "def average(values):  # noted"},
    )
    outcome, _ = _run(tmp_path, [cosmetic, DONE, DONE, DONE])

    assert outcome.proof is not None
    assert outcome.proof.repro_after is not None
    assert outcome.proof.suite_after is None


# -- repair -----------------------------------------------------------------


def test_repair_after_a_failed_repro_can_succeed(tmp_path: Path) -> None:
    outcome, _ = _run(tmp_path, [DONE, FIX_TURN, DONE])

    assert outcome.status is ProofStatus.PROVEN
    assert outcome.repairs_used == 1


def test_repair_after_a_broken_suite_can_succeed(tmp_path: Path) -> None:
    """Round 1 fixes the repro but breaks a neighbour; round 2 repairs it."""
    undo = tool_turn(
        "replace_exact",
        {
            "path": "calc.py",
            "find": "def average(values):\n    return 0",
            "replace": "def average(values):\n    if not values:\n        return 0\n    return sum(values) / len(values)",
        },
    )
    outcome, _ = _run(tmp_path, [BAD_FIX_TURN, DONE, undo, DONE])

    assert outcome.status is ProofStatus.PROVEN
    assert outcome.repairs_used == 1


def test_repair_feedback_names_the_failing_repro(tmp_path: Path) -> None:
    _, provider = _run(tmp_path, [DONE, FIX_TURN, DONE])
    repair_prompt = provider.seen_messages[-1][0].content

    assert "NOT PROVEN" in repair_prompt
    assert "test_empty_returns_zero" in repair_prompt


def test_repair_feedback_distinguishes_a_broken_suite(tmp_path: Path) -> None:
    _, provider = _run(tmp_path, [BAD_FIX_TURN, DONE, FIX_TURN, DONE])
    repair_prompt = provider.seen_messages[-1][0].content

    assert "SUITE" in repair_prompt.upper()


def test_repairs_are_bounded_and_exhaust_explicitly(tmp_path: Path) -> None:
    outcome, _ = _run(tmp_path, [DONE] * 10)

    assert outcome.status is ProofStatus.UNPROVEN
    assert outcome.repairs_used == DEBUG_LIMITS.max_repair_rounds
    assert "repair" in outcome.reason.lower() or "unproven" in outcome.reason.lower()


def test_repair_preserves_edits_from_earlier_rounds(tmp_path: Path) -> None:
    """The workspace is never reset -- a repair continues from the diff."""
    ws = _ws(tmp_path)
    half = tool_turn(
        "replace_exact",
        {"path": "calc.py", "find": "def average(values):", "replace": "def average(values):  # step one"},
    )
    rest = tool_turn(
        "replace_exact",
        {
            "path": "calc.py",
            "find": "    return sum(values) / len(values)",
            "replace": "    if not values:\n        return 0\n    return sum(values) / len(values)",
        },
    )
    outcome, _ = _run(tmp_path, [half, DONE, rest, DONE], ws=ws)
    body = (ws.root / "calc.py").read_text(encoding="utf-8")

    assert outcome.status is ProofStatus.PROVEN
    assert "# step one" in body  # round 1's edit survived
    assert "if not values" in body


# -- the frozen commands ----------------------------------------------------


def _repro_ctx(ws: Workspace):
    from engine.codeagent.tools.base import ToolContext

    return ToolContext(workspace=ws, policy=DEFAULT_POLICY, limits=DEBUG_LIMITS)


def test_run_repro_with_no_args_executes_the_frozen_command(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    ctx = _repro_ctx(ws)
    result = RunReproTool(freeze_repro(REPRO_ARGV)).run({}, ctx)

    assert result.ok is True
    assert [record.argv for record in ctx.command_log] == [REPRO_ARGV]


def test_run_repro_rejects_a_model_supplied_argv(tmp_path: Path) -> None:
    """Refused, not silently ignored: a discarded argument is a silent failure."""
    ws = _ws(tmp_path)
    ctx = _repro_ctx(ws)
    result = RunReproTool(freeze_repro(REPRO_ARGV)).run(
        {"argv": ["python", "-c", "pass"]}, ctx
    )

    assert result.ok is False
    assert result.error is not None
    assert "argv" in result.error
    # Nothing ran at all -- not the model's command, and not the frozen one.
    assert ctx.command_log == []


@pytest.mark.parametrize(
    "args",
    [
        {"argv": ["pytest", "-k", "empty"]},
        {"pattern": "narrow"},
        {"path": "tests/test_calc.py"},
        {"argv": [], "extra": 1},
        {"": ""},
    ],
)
def test_run_repro_rejects_every_unexpected_argument(tmp_path: Path, args: dict) -> None:
    ws = _ws(tmp_path)
    ctx = _repro_ctx(ws)
    result = RunReproTool(freeze_repro(REPRO_ARGV)).run(args, ctx)

    assert result.ok is False
    assert ctx.command_log == []


def test_the_frozen_argv_is_unchanged_after_misuse(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    frozen = freeze_repro(REPRO_ARGV)
    tool = RunReproTool(frozen)

    tool.run({"argv": ["rm", "-rf", "/"]}, _repro_ctx(ws))
    tool.run({"pattern": "x"}, _repro_ctx(ws))

    assert tool.argv == REPRO_ARGV
    assert frozen.as_list() == REPRO_ARGV
    # And it still works afterwards.
    ctx = _repro_ctx(ws)
    tool.run({}, ctx)
    assert [record.argv for record in ctx.command_log] == [REPRO_ARGV]


def test_a_refusal_is_a_usable_observation(tmp_path: Path) -> None:
    """The model must be able to read the error and correct itself."""
    ws = _ws(tmp_path)
    result = RunReproTool(freeze_repro(REPRO_ARGV)).run({"argv": ["x"]}, _repro_ctx(ws))

    assert result.error is not None
    assert "no arguments" in result.error.lower()


def test_model_cannot_narrow_the_repro_through_the_tool(tmp_path: Path) -> None:
    narrowed = tool_turn("run_repro", {"argv": ["python", "-c", "pass"]})
    outcome, _ = _run(tmp_path, [FIX_TURN, narrowed, DONE])
    executed = [c["argv"] for c in outcome.commands_run]

    assert ["python", "-c", "pass"] not in executed
    assert REPRO_ARGV in executed


def test_the_fixing_model_has_no_arbitrary_command_tool(tmp_path: Path) -> None:
    """No run_command and no write_file: edits are anchored, commands are fixed."""
    assert "run_command" not in DEBUG_FIX_TOOLS
    assert "write_file" not in DEBUG_FIX_TOOLS
    assert "run_repro" in DEBUG_FIX_TOOLS
    assert "replace_exact" in DEBUG_FIX_TOOLS


def test_suite_argv_is_frozen_against_the_model(tmp_path: Path) -> None:
    """Whatever the model runs, the gate's suite command is the harness's."""
    outcome, _ = _run(tmp_path, [FIX_TURN, tool_turn("run_tests"), DONE])

    assert outcome.proof is not None
    assert outcome.proof.suite_after is not None
    assert outcome.proof.suite_after.argv == SUITE_ARGV


def test_a_disallowed_suite_command_is_refused_before_any_edit(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    outcome, provider = _run(tmp_path, [FIX_TURN, DONE], ws=ws, suite_argv=["git", "push"])

    assert outcome.status is ProofStatus.ABORTED
    assert provider.calls == 0
    assert ws.changed_files == []


def test_a_shell_string_suite_command_is_refused(tmp_path: Path) -> None:
    outcome, _ = _run(tmp_path, [FIX_TURN, DONE], suite_argv=["python -m pytest"])  # type: ignore[list-item]

    assert outcome.status is ProofStatus.ABORTED


# -- prerequisites: no edit without D1 and D2 -------------------------------


def test_unreproduced_evidence_cannot_enter_the_fixing_phase(tmp_path: Path) -> None:
    ws = _ws(tmp_path, calc=FIXED)  # already fixed, so nothing reproduces
    passing = build_evidence(
        argv=REPRO_ARGV, stdout="", stderr="", exit_code=0, timed_out=False,
        duration_ms=1, workspace=ws, limits=Limits(),
    )
    provider = ScriptedProvider([FIX_TURN, DONE])
    outcome = run_fix_loop(
        task_text="average crashes",
        evidence=passing,
        root_cause=_root_cause(),
        repro=freeze_repro(REPRO_ARGV),
        suite_argv=SUITE_ARGV,
        workspace=ws,
        gateway=LLMGateway(provider),
        budget=BudgetController(max_tokens=1_000_000, planned_budget=Decimal("10.00")),
        model=MODEL,
        task_id="dbg-fix",
        limits=DEBUG_LIMITS,
    )

    assert outcome.status is ProofStatus.ABORTED
    assert provider.calls == 0
    assert ws.changed_files == []


def test_a_root_cause_naming_a_missing_file_cannot_enter_the_fixing_phase(
    tmp_path: Path,
) -> None:
    ws = _ws(tmp_path)
    outcome, provider = _run(
        tmp_path, [FIX_TURN, DONE], ws=ws, root_cause=_root_cause(primary_file="ghost.py")
    )

    assert outcome.status is ProofStatus.ABORTED
    assert provider.calls == 0
    assert ws.changed_files == []


# -- minimal-edit constraint ------------------------------------------------


def test_the_edit_ledger_ceiling_stops_a_broad_change(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    ws2 = Workspace(ws.root, max_files_changed=1)
    edits = [
        FIX_TURN,
        tool_turn(
            "replace_exact",
            {"path": "tests/test_calc.py", "find": "from calc import average", "replace": "from calc import average  # touched"},
        ),
        DONE,
    ]
    outcome, _ = _run(tmp_path, edits * 3, ws=ws2)

    assert outcome.files_changed == ["calc.py"]
    assert "max_files_changed" in json.dumps(
        [t for t in outcome.tool_results if not t.get("ok", True)]
    )


def test_debug_limits_are_tighter_than_the_coding_agent_defaults(tmp_path: Path) -> None:
    assert DEBUG_LIMITS.max_files_changed < Limits().max_files_changed
    assert DEBUG_LIMITS.max_repair_rounds == 2


# -- state, report and usage ------------------------------------------------


def test_outcome_records_the_observable_facts(tmp_path: Path) -> None:
    outcome, _ = _run(tmp_path, [FIX_TURN, DONE])
    payload = outcome.as_dict()

    assert payload["proof_status"] == "PROVEN"
    assert payload["files_changed"] == ["calc.py"]
    assert payload["root_cause"]["primary_file"] == "calc.py"
    assert payload["repairs_used"] == 0
    assert payload["tool_calls"] >= 1
    assert any(c["argv"] == REPRO_ARGV for c in payload["commands_run"])


def test_outcome_carries_no_hidden_reasoning(tmp_path: Path) -> None:
    payload = _run(tmp_path, [FIX_TURN, DONE])[0].as_dict()
    forbidden = {"reasoning", "thinking", "chain_of_thought", "analysis"}

    assert forbidden.isdisjoint(payload)


def test_usage_accumulates_across_repair_sessions(tmp_path: Path) -> None:
    """D2 semantics carried forward: attempts counted, tokens only when returned."""
    one, _ = _run(tmp_path, [FIX_TURN, DONE])
    two, _ = _run(tmp_path, [DONE, FIX_TURN, DONE])

    assert two.repairs_used == 1
    assert two.model_calls > one.model_calls
    assert two.input_tokens > one.input_tokens
    assert two.output_tokens > one.output_tokens


def test_model_calls_counts_gateway_attempts(tmp_path: Path) -> None:
    outcome, provider = _run(tmp_path, [FIX_TURN, DONE])

    assert outcome.model_calls == provider.calls


def test_log_records_the_proof_result(tmp_path: Path) -> None:
    log = SessionLog()
    _run(tmp_path, [FIX_TURN, DONE], log=log)

    events = log.of_kind("fix_proof")
    assert events
    assert events[-1].payload["proven"] is True


def test_session_status_is_reported_alongside_proof(tmp_path: Path) -> None:
    outcome, _ = _run(tmp_path, [FIX_TURN, DONE])

    assert outcome.session_status is SessionStatus.COMPLETED_UNVERIFIED
    assert outcome.status is ProofStatus.PROVEN


# -- no provider SDK --------------------------------------------------------


def test_no_debugagent_module_imports_a_provider_sdk() -> None:
    import ast

    from engine import debugagent

    root = Path(debugagent.__file__).parent
    banned = ("engine.providers", "anthropic", "openai", "httpx")
    violations: list[str] = []
    for path in sorted(root.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            violations += [f"{path.name}: {n}" for n in names if n.startswith(banned)]

    assert violations == []


@pytest.mark.parametrize("argv", [[], "python -m pytest"])
def test_a_malformed_suite_command_is_refused(tmp_path: Path, argv: object) -> None:
    outcome, _ = _run(tmp_path, [FIX_TURN, DONE], suite_argv=argv)  # type: ignore[arg-type]

    assert outcome.status is ProofStatus.ABORTED


# -- the committed demo fixture ---------------------------------------------
#
# These run against examples/cart_bug/ itself, copied to a temp workspace. They
# exist so the fixture cannot silently rot into something that proves nothing:
# a fixture whose bug got fixed, or whose suite has only the targeted test,
# would make the D3 demo vacuous while still "passing".

FIXTURE = Path(__file__).resolve().parents[1] / "examples" / "cart_bug"


def _fixture_ws(tmp_path: Path) -> Workspace:
    import shutil

    root = tmp_path / "cart_bug"
    shutil.copytree(FIXTURE, root)
    return Workspace(root, max_files_changed=DEBUG_LIMITS.max_files_changed)


# The ordinary command a person would type. No --tb=native: the evidence layer
# parses pytest's own failure-location lines, so the normal form yields frames.
FIXTURE_REPRO = [
    "python", "-m", "pytest", "-q",
    "tests/test_cart.py::test_empty_cart_is_shipping_only",
]


def test_fixture_is_committed_broken(tmp_path: Path) -> None:
    """If this passes out of the box, the fixture demonstrates nothing."""
    ws = _fixture_ws(tmp_path)
    outcome = reproduce(
        repro=freeze_repro(FIXTURE_REPRO),
        workspace=ws,
        policy=DEFAULT_POLICY,
        limits=Limits(repro_timeout_seconds=60),
    )

    assert outcome.reproduced is True
    assert outcome.evidence is not None
    assert outcome.evidence.exception_type == "ValueError"


def test_fixture_traceback_points_into_the_real_source(tmp_path: Path) -> None:
    ws = _fixture_ws(tmp_path)
    evidence = reproduce(
        repro=freeze_repro(FIXTURE_REPRO), workspace=ws, policy=DEFAULT_POLICY,
        limits=Limits(repro_timeout_seconds=60),
    ).evidence

    assert evidence is not None
    assert evidence.suspect is not None
    assert evidence.suspect.file == "cart.py"
    # pytest's deepest location line carries the exception type, not the
    # function, so the line is what identifies it.
    assert evidence.suspect.line == 24
    assert "cart.py" in evidence.referenced_files


def test_fixture_suite_has_tests_beyond_the_targeted_one(tmp_path: Path) -> None:
    """The full-suite gate needs something to protect."""
    body = (FIXTURE / "tests" / "test_cart.py").read_text(encoding="utf-8")
    names = [line for line in body.splitlines() if line.startswith("def test_")]

    assert len(names) >= 3
    assert any("bulk_discount" in name for name in names)


def test_fixture_task_description_does_not_contain_the_patch() -> None:
    """A fixture that hands over the fix does not exercise diagnosis."""
    task = (FIXTURE / "TASK.md").read_text(encoding="utf-8")
    report = task.split("## Commands")[0]

    assert "_discount" not in report
    assert "if not items" not in report
    assert "min(" not in report


def test_fixture_reaches_proven_with_the_correct_fix(tmp_path: Path) -> None:
    """End to end over the real fixture: guard the empty case -> PROVEN."""
    ws = _fixture_ws(tmp_path)
    evidence = reproduce(
        repro=freeze_repro(FIXTURE_REPRO), workspace=ws, policy=DEFAULT_POLICY,
        limits=Limits(repro_timeout_seconds=60),
    ).evidence
    assert evidence is not None

    guard = tool_turn(
        "replace_exact",
        {
            "path": "cart.py",
            "find": "    cheapest = min(item.price for item in items)",
            "replace": "    if not items:\n        return 0.0\n    cheapest = min(item.price for item in items)",
        },
    )
    cause = _root_cause(
        primary_file="cart.py",
        primary_line=24,
        summary="the bulk discount is computed before the cart is known to be non-empty",
        proposed_fix="return no discount for an empty cart",
    )
    outcome = run_fix_loop(
        task_text="totalling an empty cart crashes instead of returning shipping",
        evidence=evidence,
        root_cause=cause,
        repro=freeze_repro(FIXTURE_REPRO),
        suite_argv=SUITE_ARGV,
        workspace=ws,
        gateway=LLMGateway(ScriptedProvider([guard, DONE])),
        budget=BudgetController(max_tokens=1_000_000, planned_budget=Decimal("10.00")),
        model=MODEL,
        task_id="dbg-fixture",
        limits=DEBUG_LIMITS,
    )

    assert outcome.status is ProofStatus.PROVEN
    assert outcome.files_changed == ["cart.py"]


def test_fixture_suite_gate_catches_a_discount_destroying_fix(tmp_path: Path) -> None:
    """Repro goes green, a neighbour breaks -- exactly what the suite is for."""
    ws = _fixture_ws(tmp_path)
    evidence = reproduce(
        repro=freeze_repro(FIXTURE_REPRO), workspace=ws, policy=DEFAULT_POLICY,
        limits=Limits(repro_timeout_seconds=60),
    ).evidence
    assert evidence is not None

    gut_it = tool_turn(
        "replace_exact",
        {
            "path": "cart.py",
            "find": "    cheapest = min(item.price for item in items)\n    if sum(item.qty for item in items) < BULK_UNITS:\n        return 0.0\n    return cheapest * BULK_RATE",
            "replace": "    return 0.0",
        },
    )
    outcome = run_fix_loop(
        task_text="totalling an empty cart crashes",
        evidence=evidence,
        root_cause=_root_cause(primary_file="cart.py", primary_line=24),
        repro=freeze_repro(FIXTURE_REPRO),
        suite_argv=SUITE_ARGV,
        workspace=ws,
        gateway=LLMGateway(ScriptedProvider([gut_it, DONE])),
        budget=BudgetController(max_tokens=1_000_000, planned_budget=Decimal("10.00")),
        model=MODEL,
        task_id="dbg-fixture-bad",
        limits=DEBUG_LIMITS,
    )

    assert outcome.status is ProofStatus.UNPROVEN
    assert outcome.proof is not None
    assert outcome.proof.stage == "SUITE"
    assert outcome.proof.repro_after is not None
    assert outcome.proof.repro_after.exit_code == 0
