"""C10: bounded repository graph -- the scan, the queries, the tool, the seam.

Four layers, each proving something the one below it cannot:

    scan    a deterministic AST/import walk indexes symbols and module edges,
            bounded and screened the same way capabilities/testenv is
    query   find_references does its own bounded, early-stopping scan
    tool    what a model may ask, what is recorded, and that a path still goes
            through Workspace.resolve like every other path-taking tool
    stack   a coding session and a Debug fix session gaining the tool while
            diagnosis, the frozen commands and the proof gate are untouched

**Offline throughout.** Every test reads only files this suite writes under
``tmp_path``. No subprocess, no network, no import of scanned code.
"""

import ast
from decimal import Decimal
from pathlib import Path

from codeagent_harness import CLEAN_CRITIC, MODEL, DebugScenarioProvider, final_turn, tool_turn
from test_codeagent_capabilities import ctx_for, run_session
from test_debugagent_app import (
    BUG,
    DIAGNOSIS,
    LENS_PROMPTS,
    REPRO,
    SOLVE_TURNS,
    SUITE,
    fixture_copy,
)

from engine.capabilities.graph import build_graph, find_references
from engine.codeagent.capabilities import build_capabilities, context_sources_from
from engine.codeagent.limits import Limits
from engine.codeagent.state import SessionStatus
from engine.codeagent.tools.base import ToolContext
from engine.codeagent.tools.graph import ALLOWED_ARGS, OPS, RepoGraphTool
from engine.debugagent.app import run_debug_task
from engine.debugagent.fix import ProofStatus
from engine.debugagent.limits import DEBUG_LIMITS
from engine.runtime.gateway import LLMGateway


def seed(root: Path, relative: str, content: str = "") -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def run_query(tmp_path: Path, **args: object):  # type: ignore[no-untyped-def]
    ctx = ctx_for(tmp_path)
    return RepoGraphTool().run(args, ctx), ctx


# -- the scan -------------------------------------------------------------------


def test_module_level_and_class_level_symbols_are_indexed(tmp_path: Path) -> None:
    seed(
        tmp_path,
        "pkg/mod_a.py",
        "def foo():\n    pass\n\n\nclass Bar:\n    def method_a(self):\n        pass\n",
    )
    graph = build_graph(tmp_path)

    assert [d.as_dict() for d in graph.symbols["foo"]] == [
        {"name": "foo", "kind": "function", "qualname": "foo", "path": "pkg/mod_a.py", "line": 1}
    ]
    assert [d.as_dict() for d in graph.symbols["Bar"]] == [
        {"name": "Bar", "kind": "class", "qualname": "Bar", "path": "pkg/mod_a.py", "line": 5}
    ]
    assert [d.as_dict() for d in graph.symbols["method_a"]] == [
        {
            "name": "method_a",
            "kind": "method",
            "qualname": "Bar.method_a",
            "path": "pkg/mod_a.py",
            "line": 6,
        }
    ]


def test_nested_function_is_not_indexed(tmp_path: Path) -> None:
    """Shallow by design: a function inside a function is out of scope."""
    seed(tmp_path, "mod.py", "def outer():\n    def inner():\n        pass\n    return inner\n")
    graph = build_graph(tmp_path)
    assert "inner" not in graph.symbols
    assert "outer" in graph.symbols


def test_an_absolute_import_resolves_against_a_scanned_module(tmp_path: Path) -> None:
    seed(tmp_path, "pkg/__init__.py", "")
    seed(tmp_path, "pkg/mod_a.py", "def foo():\n    pass\n")
    seed(tmp_path, "pkg/mod_b.py", "from pkg.mod_a import foo\n\nfoo()\n")

    graph = build_graph(tmp_path)

    assert graph.imports["pkg/mod_b.py"].resolved == ("pkg/mod_a.py",)
    assert graph.imports["pkg/mod_b.py"].external == ()
    assert graph.dependents["pkg/mod_a.py"] == ("pkg/mod_b.py",)


def test_a_src_layout_import_resolves_using_the_stripped_dotted_name(tmp_path: Path) -> None:
    seed(tmp_path, "src/engine/foo.py", "def helper():\n    pass\n")
    seed(tmp_path, "src/engine/bar.py", "from engine.foo import helper\n")

    graph = build_graph(tmp_path)

    assert graph.imports["src/engine/bar.py"].resolved == ("src/engine/foo.py",)


def test_an_import_of_a_plain_import_statement_also_resolves(tmp_path: Path) -> None:
    seed(tmp_path, "pkg/__init__.py", "")
    seed(tmp_path, "pkg/mod_a.py", "")
    seed(tmp_path, "pkg/mod_b.py", "import pkg.mod_a\n")

    graph = build_graph(tmp_path)
    assert graph.imports["pkg/mod_b.py"].resolved == ("pkg/mod_a.py",)


def test_an_unresolvable_import_is_recorded_as_external(tmp_path: Path) -> None:
    seed(tmp_path, "mod.py", "import numpy\nfrom os import path\n")
    graph = build_graph(tmp_path)
    edge = graph.imports["mod.py"]
    assert edge.resolved == ()
    assert edge.external == ("numpy", "os")


def test_a_relative_import_is_recorded_as_external_not_resolved(tmp_path: Path) -> None:
    """No relative import appears in this codebase; getting resolution wrong
    would be a worse answer than an honestly unresolved one, so it is not
    attempted."""
    seed(tmp_path, "pkg/__init__.py", "")
    seed(tmp_path, "pkg/mod_a.py", "")
    seed(tmp_path, "pkg/mod_b.py", "from .mod_a import helper\n")

    graph = build_graph(tmp_path)
    edge = graph.imports["pkg/mod_b.py"]
    assert edge.resolved == ()
    assert edge.external == (".mod_a",)


def test_a_syntax_error_is_recorded_as_evidence_not_a_crash(tmp_path: Path) -> None:
    seed(tmp_path, "broken.py", "def broken(:\n")
    seed(tmp_path, "fine.py", "def ok():\n    pass\n")

    graph = build_graph(tmp_path)

    assert "fine.py" in graph.modules
    assert "broken.py" not in graph.modules
    assert any("broken.py" in e for e in graph.errors)


def test_a_missing_root_yields_an_empty_graph_with_an_error(tmp_path: Path) -> None:
    graph = build_graph(tmp_path / "does-not-exist")
    assert graph.modules == ()
    assert graph.errors == ("root: not an existing directory",)


def test_noise_and_denied_directories_are_never_descended_into(tmp_path: Path) -> None:
    seed(tmp_path, "real.py", "def visible():\n    pass\n")
    seed(tmp_path, "node_modules/pkg.py", "def hidden():\n    pass\n")
    seed(tmp_path, ".git/hooks.py", "def also_hidden():\n    pass\n")
    seed(tmp_path, "__pycache__/cache.py", "def cached():\n    pass\n")

    graph = build_graph(tmp_path)

    assert graph.modules == ("real.py",)
    assert "hidden" not in graph.symbols
    assert "also_hidden" not in graph.symbols
    assert "cached" not in graph.symbols


def test_the_file_scan_is_bounded(tmp_path: Path) -> None:
    for i in range(5):
        seed(tmp_path, f"mod_{i}.py", "")
    graph = build_graph(tmp_path, max_files=3)
    assert len(graph.modules) == 3
    assert graph.files_skipped_bound is True


def test_the_scan_is_deterministic(tmp_path: Path) -> None:
    seed(tmp_path, "pkg/__init__.py", "")
    seed(tmp_path, "pkg/mod_a.py", "def foo():\n    pass\n")
    seed(tmp_path, "pkg/mod_b.py", "from pkg.mod_a import foo\n")

    first = build_graph(tmp_path)
    second = build_graph(tmp_path)

    assert first.modules == second.modules
    assert {k: [d.as_dict() for d in v] for k, v in first.symbols.items()} == {
        k: [d.as_dict() for d in v] for k, v in second.symbols.items()
    }
    assert {k: v.as_dict() for k, v in first.imports.items()} == {
        k: v.as_dict() for k, v in second.imports.items()
    }


# -- find_references --------------------------------------------------------


def test_find_references_matches_a_bare_identifier(tmp_path: Path) -> None:
    seed(tmp_path, "mod_a.py", "def foo():\n    pass\n")
    seed(tmp_path, "mod_b.py", "from mod_a import foo\n\nfoo()\n")

    hits = find_references(tmp_path, "foo")
    assert ("mod_b.py", 3) in hits


def test_find_references_is_bounded(tmp_path: Path) -> None:
    seed(tmp_path, "mod.py", "\n".join("target()" for _ in range(10)))
    hits = find_references(tmp_path, "target", max_results=4)
    assert len(hits) == 4


# -- the tool -----------------------------------------------------------------


def test_an_unexpected_argument_is_refused_rather_than_ignored(tmp_path: Path) -> None:
    outcome, ctx = run_query(tmp_path, op="find_symbol", name="foo", rules="p/default")
    assert "rules" in outcome.output
    assert ctx.graph_log[0].error is not None


def test_an_unknown_op_is_refused(tmp_path: Path) -> None:
    outcome, ctx = run_query(tmp_path, op="delete_everything")
    assert "op must be one of" in outcome.output
    assert ctx.graph_log[0].error is not None


def test_a_missing_required_argument_fails(tmp_path: Path) -> None:
    outcome, _ = run_query(tmp_path, op="find_symbol")
    assert outcome.ok is False


def test_find_symbol_reports_a_match(tmp_path: Path) -> None:
    seed(tmp_path / "ws", "mod.py", "def target():\n    pass\n")
    outcome, ctx = run_query(tmp_path, op="find_symbol", name="target")
    assert "function target mod.py:1" in outcome.output
    assert ctx.graph_log[0].op == "find_symbol"
    assert ctx.graph_log[0].result_count == 1


def test_find_symbol_with_no_match_says_none(tmp_path: Path) -> None:
    outcome, _ = run_query(tmp_path, op="find_symbol", name="nope")
    assert "(none)" in outcome.output


def test_find_references_reports_a_hit(tmp_path: Path) -> None:
    seed(tmp_path / "ws", "mod_a.py", "def foo():\n    pass\n")
    seed(tmp_path / "ws", "mod_b.py", "from mod_a import foo\n\nfoo()\n")
    outcome, ctx = run_query(tmp_path, op="find_references", name="foo")
    assert "mod_b.py:3" in outcome.output
    assert "not type-resolved" in outcome.output
    assert ctx.graph_log[0].op == "find_references"


def test_find_dependents_lists_importing_modules(tmp_path: Path) -> None:
    seed(tmp_path / "ws", "pkg/__init__.py", "")
    seed(tmp_path / "ws", "pkg/mod_a.py", "")
    seed(tmp_path / "ws", "pkg/mod_b.py", "import pkg.mod_a\n")
    outcome, _ = run_query(tmp_path, op="find_dependents", path="pkg/mod_a.py")
    assert "pkg/mod_b.py" in outcome.output


def test_related_files_is_the_union_of_imports_and_dependents(tmp_path: Path) -> None:
    seed(tmp_path / "ws", "pkg/__init__.py", "")
    seed(tmp_path / "ws", "pkg/a.py", "import pkg.b\n")
    seed(tmp_path / "ws", "pkg/b.py", "")
    seed(tmp_path / "ws", "pkg/c.py", "import pkg.a\n")
    outcome, _ = run_query(tmp_path, op="related_files", path="pkg/a.py")
    assert "pkg/b.py" in outcome.output  # a imports b
    assert "pkg/c.py" in outcome.output  # c imports a


def test_show_module_graph_with_no_path_summarises_the_scan(tmp_path: Path) -> None:
    seed(tmp_path / "ws", "mod.py", "def foo():\n    pass\n")
    outcome, _ = run_query(tmp_path, op="show_module_graph")
    assert "modules_scanned: 1" in outcome.output


def test_show_module_graph_with_a_path_shows_direct_edges(tmp_path: Path) -> None:
    seed(tmp_path / "ws", "pkg/__init__.py", "")
    seed(tmp_path / "ws", "pkg/a.py", "import pkg.b\n")
    seed(tmp_path / "ws", "pkg/b.py", "")
    outcome, _ = run_query(tmp_path, op="show_module_graph", path="pkg/a.py")
    assert "pkg/b.py" in outcome.output


def test_a_path_that_escapes_the_workspace_is_refused(tmp_path: Path) -> None:
    outcome, _ = run_query(tmp_path, op="find_dependents", path="../outside.py")
    assert outcome.ok is False


def test_results_are_bounded_by_max_graph_results(tmp_path: Path) -> None:
    for i in range(5):
        seed(tmp_path / "ws", f"mod_{i}.py", "def target():\n    pass\n")
    ctx = ctx_for(tmp_path)
    small = ToolContext(
        workspace=ctx.workspace, policy=ctx.policy, limits=Limits(max_graph_results=2)
    )
    outcome = RepoGraphTool().run({"op": "find_symbol", "name": "target"}, small)
    assert "showing: 2 of 5" in outcome.output
    assert small.graph_log[0].truncated is True


def test_every_op_is_reachable_and_documented() -> None:
    description = RepoGraphTool().description
    for op in OPS:
        assert op in description
    assert ALLOWED_ARGS == {"op", "name", "path", "depth"}


# -- advisory only, and stays a leaf -------------------------------------------


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_the_graph_layer_never_reaches_verification_or_eval() -> None:
    roots = [
        Path("src/engine/capabilities/graph"),
        Path("src/engine/codeagent/tools/graph.py"),
    ]
    modules = [
        path
        for root in roots
        for path in ([root] if root.is_file() else sorted(root.glob("*.py")))
    ]
    assert modules

    forbidden = ("engine.verification", "engine.eval", "engine.debugagent")
    for path in modules:
        offending = {name for name in _imports(path) if name.startswith(forbidden)}
        assert not offending, f"{path}: imports {sorted(offending)}"


def test_the_capability_layer_stays_a_leaf() -> None:
    for path in sorted(Path("src/engine/capabilities/graph").glob("*.py")):
        agent_imports = {
            name
            for name in _imports(path)
            if name.startswith(("engine.codeagent", "engine.debugagent"))
        }
        assert not agent_imports, f"{path}: imports {sorted(agent_imports)}"


# -- the bundle and the report ------------------------------------------------


def test_the_tool_is_absent_unless_requested() -> None:
    assert "repo_graph" not in build_capabilities().tools


def test_requesting_the_graph_registers_exactly_one_tool() -> None:
    bundle = build_capabilities(graph=True)
    assert set(bundle.tools) == {"repo_graph"}


def test_context_sources_is_none_when_nothing_was_queried(tmp_path: Path) -> None:
    state, _ = run_session(tmp_path, [final_turn("done")], bundle=build_capabilities())
    assert context_sources_from([state])["graph_queries"] is None


def test_a_session_records_its_queries_in_context_sources(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir(parents=True, exist_ok=True)
    seed(workspace, "mod.py", "def target():\n    pass\n")

    state, _ = run_session(
        tmp_path,
        [tool_turn("repo_graph", {"op": "find_symbol", "name": "target"}), final_turn("done")],
        bundle=build_capabilities(graph=True),
    )

    recorded = context_sources_from([state])["graph_queries"]
    assert isinstance(recorded, list) and len(recorded) == 1
    assert recorded[0]["op"] == "find_symbol"
    assert recorded[0]["result_count"] == 1
    assert state.status is SessionStatus.COMPLETED_UNVERIFIED


# -- the Debug Agent keeps every guarantee it had ------------------------------


def run_debug(tmp_path: Path, fix_turns, **kwargs):  # type: ignore[no-untyped-def]
    fake = DebugScenarioProvider(
        diagnosis_turns=[DIAGNOSIS],
        fix_turns=fix_turns,
        judge_rounds=[CLEAN_CRITIC],
        lens_prompts=LENS_PROMPTS,
    )
    result_ = run_debug_task(
        task_text=BUG,
        workspace_path=fixture_copy(tmp_path),
        repro_argv=REPRO,
        suite_argv=SUITE,
        gateway=LLMGateway(fake),
        model=MODEL,
        judge_model=MODEL,
        limits=DEBUG_LIMITS,
        planned_budget=Decimal("10.00"),
        task_id="dbg-c10",
        **kwargs,
    )
    return result_, fake


def test_a_debug_fix_session_can_query_the_graph_and_diagnosis_cannot(tmp_path: Path) -> None:
    outcome, fake = run_debug(
        tmp_path,
        [tool_turn("repo_graph", {"op": "show_module_graph"}), *SOLVE_TURNS],
        graph=True,
    )

    fix_system = next(
        s for s in fake.seen_systems if s and s.startswith("You are a debugging agent")
    )
    assert "repo_graph" in fix_system

    diagnosis_system = next(
        s for s in fake.seen_systems if s and s.startswith("You are diagnosing a reproduced")
    )
    assert "repo_graph" not in diagnosis_system

    report = outcome.report
    assert list(report.repro_command) == REPRO
    assert list(report.suite_command) == SUITE
    assert report.observed.proof_status == ProofStatus.PROVEN.value
    assert report.status == SessionStatus.PASSED.value


def test_a_debug_run_without_the_graph_never_learns_the_tool_existed(tmp_path: Path) -> None:
    _, fake = run_debug(tmp_path, SOLVE_TURNS)
    for system in fake.seen_systems:
        if system:
            assert "repo_graph" not in system
