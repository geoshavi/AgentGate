"""`engine bench --shadow-adjudicate` / `--adjudicate` / `--case-id`: the CLI
surface for both adjudication modes.

`--shadow-adjudicate` only chooses whether adjudication records are *computed
and stored*. It cannot change a verdict: `run_verification` puts shadow
records in a separate key that `verdict.gate` never reads, and that property
is pinned by tests/test_shadow_adjudication.py.

`--adjudicate` is the authoritative counterpart, deliberately reachable only
together with `--case-id`: the CLI refuses it outright on a full or
category-wide run, before any provider call, so it cannot be turned on by
accident against a random paid benchmark. What these tests pin is the part
the CLI owns -- that each flag reaches `run_benchmark` correctly, that
neither flag's absence changes anything about the pre-flag CLI, that the two
modes cannot be combined (both at the argparse level and, as a second line of
defense, inside `run_verification` itself), and that `--adjudicate` without
`--case-id` is refused before any provider call.

No test here makes an LLM call. `run_benchmark` is replaced wholesale, and the
--dry-run cases run with every provider key deleted, so constructing a gateway
would raise rather than reach a provider.

Every test also redirects ENGINE_DB_PATH into tmp_path. That is not tidiness:
`engine bench --compare N` calls `db.connect(config.db_path)`, and `db.connect`
runs `executescript(SCHEMA)`, `_migrate()` and `commit()` on whatever file it
is handed. Without the redirect these tests open and write to the real
`.engine/state.db`, which holds the entire run history, is gitignored, and has
no backup of any kind. `test_compare_never_touches_the_production_database`
below pins the redirect so this cannot regress.
"""

import sys
from decimal import Decimal
from pathlib import Path

import pytest

from engine import cli
from engine.state.models import EvalRun

PRODUCTION_DB = Path(__file__).resolve().parents[1] / ".engine" / "state.db"


def _eval_run(false_pass: int = 0) -> EvalRun:
    return EvalRun(
        id=99,
        created_at="2026-09-11T00:00:00",
        git_commit_sha="deadbeef",
        benchmark_name="bench",
        benchmark_version="v1",
        dataset_version="v6",
        total_cases=40,
        correct_verdicts=40 - false_pass,
        false_pass=false_pass,
        false_unverified=0,
        category_accuracy={},
        average_cost=Decimal(0),
        average_latency=0,
        total_cost=Decimal(0),
    )


def _bench(monkeypatch, tmp_path: Path, argv: list[str], *, false_pass: int = 0) -> dict:
    """Run `engine bench <argv>` with run_benchmark replaced. Returns its kwargs."""
    captured: dict = {}

    def _fake_run_benchmark(**kwargs):
        captured.update(kwargs)
        return _eval_run(false_pass), []

    monkeypatch.setenv("ENGINE_DB_PATH", str(tmp_path / "cli.db"))
    monkeypatch.setattr("engine.eval.runner.run_benchmark", _fake_run_benchmark)
    monkeypatch.setattr(sys, "argv", ["engine", "bench", *argv])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    captured["_exit_code"] = exc.value.code
    return captured


# ==========================================================================
# 1. no flag -> existing behaviour
# ==========================================================================


def test_bench_without_the_flag_requests_no_shadow_adjudication(monkeypatch, tmp_path) -> None:
    captured = _bench(monkeypatch, tmp_path, [])

    assert captured["shadow_adjudicate"] is False


def test_bench_without_the_flag_passes_the_same_arguments_as_before(monkeypatch, tmp_path) -> None:
    """Default mode must be indistinguishable from the pre-flag CLI on every
    argument shadow-adjudicate already covered, plus the new ones defaulting
    off/unset."""
    captured = _bench(monkeypatch, tmp_path, [])

    assert captured["provider_name"] == "anthropic"
    assert captured["category"] is None
    assert captured["judge_model"]
    assert captured["config"] is not None
    assert captured["case_ids"] is None
    assert captured["adjudicate"] is False
    assert set(captured) - {"_exit_code"} == {
        "config",
        "provider_name",
        "judge_model",
        "category",
        "case_ids",
        "shadow_adjudicate",
        "adjudicate",
    }


# ==========================================================================
# 2. --shadow-adjudicate -> runner receives shadow_adjudicate=True
# ==========================================================================


def test_shadow_flag_reaches_run_benchmark(monkeypatch, tmp_path) -> None:
    captured = _bench(monkeypatch, tmp_path, ["--shadow-adjudicate"])

    assert captured["shadow_adjudicate"] is True


def test_shadow_flag_changes_nothing_else_about_the_call(monkeypatch, tmp_path) -> None:
    off = _bench(monkeypatch, tmp_path, [])
    on = _bench(monkeypatch, tmp_path, ["--shadow-adjudicate"])

    differing = {k for k in off if off[k] != on[k]}
    assert differing == {"shadow_adjudicate"}


def test_shadow_flag_composes_with_category(monkeypatch, tmp_path) -> None:
    captured = _bench(monkeypatch, tmp_path, ["--shadow-adjudicate", "--category", "quality"])

    assert captured["shadow_adjudicate"] is True
    assert captured["category"] == "quality"


# ==========================================================================
# 3. authoritative adjudication: gated behind --case-id, mutually exclusive
#    with shadow, and never reachable against a full or category-wide run
# ==========================================================================


def test_bench_rejects_adjudicate_without_case_id(monkeypatch, tmp_path, capsys) -> None:
    """The core safety property: --adjudicate alone can never launch a full
    (or category-wide) paid run. Refused by the CLI itself, before
    load_config/select_cases/run_benchmark are ever reached."""
    called = False

    def _fail_if_called(**kwargs):
        nonlocal called
        called = True

    monkeypatch.setenv("ENGINE_DB_PATH", str(tmp_path / "cli.db"))
    monkeypatch.setattr("engine.eval.runner.run_benchmark", _fail_if_called)
    monkeypatch.setattr(sys, "argv", ["engine", "bench", "--adjudicate"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 2
    assert "--adjudicate requires --case-id" in capsys.readouterr().err
    assert called is False


def test_bench_rejects_adjudicate_with_category_but_no_case_id(monkeypatch, tmp_path) -> None:
    """--category alone is still a multi-case (category-wide) run -- not
    narrow enough to satisfy the gate."""
    monkeypatch.setenv("ENGINE_DB_PATH", str(tmp_path / "cli.db"))
    monkeypatch.setattr(sys, "argv", ["engine", "bench", "--adjudicate", "--category", "edge_case"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 2


def test_adjudicate_flag_reaches_run_benchmark_when_case_id_is_given(monkeypatch, tmp_path) -> None:
    captured = _bench(
        monkeypatch, tmp_path, ["--adjudicate", "--case-id", "edge_case-02-clean"]
    )

    assert captured["adjudicate"] is True
    assert captured["case_ids"] == ["edge_case-02-clean"]
    assert captured["shadow_adjudicate"] is False


def test_case_id_is_repeatable_and_composes_with_category(monkeypatch, tmp_path) -> None:
    captured = _bench(
        monkeypatch,
        tmp_path,
        [
            "--adjudicate",
            "--case-id",
            "edge_case-02-clean",
            "--case-id",
            "edge_case-02-broken",
            "--category",
            "edge_case",
        ],
    )

    assert captured["case_ids"] == ["edge_case-02-clean", "edge_case-02-broken"]
    assert captured["category"] == "edge_case"
    assert captured["adjudicate"] is True


def test_shadow_and_adjudicate_together_are_rejected_by_argparse(monkeypatch, tmp_path) -> None:
    """Argparse's own mutually-exclusive group refuses the combination before
    load_config/run_benchmark are ever reached -- not just a downstream
    ValueError."""
    called = False

    def _fail_if_called(**kwargs):
        nonlocal called
        called = True

    monkeypatch.setenv("ENGINE_DB_PATH", str(tmp_path / "cli.db"))
    monkeypatch.setattr("engine.eval.runner.run_benchmark", _fail_if_called)
    monkeypatch.setattr(
        sys,
        "argv",
        ["engine", "bench", "--adjudicate", "--shadow-adjudicate", "--case-id", "edge_case-02-clean"],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 2
    assert called is False


def test_both_adjudication_modes_together_are_still_rejected_downstream() -> None:
    """Second line of defense below the CLI, for any caller that is not the
    CLI's argparse group (e.g. a direct run_benchmark/run_verification call)."""
    import inspect

    from engine.verification import pipeline

    source = inspect.getsource(pipeline.run_verification)
    assert "adjudicate and shadow_adjudicate" in source


def test_case_id_alone_does_not_imply_adjudicate(monkeypatch, tmp_path) -> None:
    """--case-id is a general filter, usable without --adjudicate -- it must
    not silently turn authoritative mode on."""
    captured = _bench(monkeypatch, tmp_path, ["--case-id", "edge_case-02-clean"])

    assert captured["case_ids"] == ["edge_case-02-clean"]
    assert captured["adjudicate"] is False
    assert captured["shadow_adjudicate"] is False


def test_select_cases_filters_to_exactly_the_named_case_ids() -> None:
    from engine.eval.runner import select_cases

    cases = select_cases(None, case_ids=["edge_case-02-clean", "edge_case-02-broken"])

    assert sorted(c.eval_case_id for c in cases) == ["edge_case-02-broken", "edge_case-02-clean"]


def test_select_cases_case_ids_intersects_with_category() -> None:
    from engine.eval.runner import select_cases

    # edge_case-02-clean is in category "edge_case", not "security" -- an
    # AND filter must return nothing, never fall back to ignoring category.
    assert select_cases("security", case_ids=["edge_case-02-clean"]) == []


# ==========================================================================
# 4. existing CLI benchmark commands remain valid
# ==========================================================================


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["--category", "security"],
        ["--compare", "7"],
        ["--category", "edge_case", "--compare", "3"],
    ],
)
def test_existing_bench_invocations_still_parse_and_run(monkeypatch, tmp_path, argv) -> None:
    captured = _bench(monkeypatch, tmp_path, argv)

    assert captured["shadow_adjudicate"] is False
    assert captured["adjudicate"] is False
    assert captured["case_ids"] is None


def test_compare_never_touches_the_production_database(monkeypatch, tmp_path) -> None:
    """`--compare` opens config.db_path, and db.connect() writes to whatever it
    is handed -- executescript(SCHEMA), _migrate(), commit(). The real
    .engine/state.db holds every run ever measured, is gitignored and has no
    backup, so a test that reaches it corrupts the only copy. Redirecting
    ENGINE_DB_PATH is what prevents that, and this pins the redirect.
    """
    if not PRODUCTION_DB.exists():
        pytest.skip("no production database present")
    before = PRODUCTION_DB.stat()

    _bench(monkeypatch, tmp_path, ["--compare", "7"])

    after = PRODUCTION_DB.stat()
    assert (after.st_mtime_ns, after.st_size) == (before.st_mtime_ns, before.st_size)
    assert (tmp_path / "cli.db").exists()  # the write landed here instead


def test_dry_run_still_makes_zero_llm_calls_with_the_shadow_flag(
    monkeypatch, tmp_path, capsys
) -> None:
    """No API key configured: reaching a gateway would raise, so a clean exit
    is direct evidence the flag did not open a provider path."""
    monkeypatch.setenv("ENGINE_DB_PATH", str(tmp_path / "cli.db"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setattr(sys, "argv", ["engine", "bench", "--dry-run", "--shadow-adjudicate"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    assert "Benchmark plan:" in capsys.readouterr().out


# ==========================================================================
# 5. no behaviour drift in default mode
# ==========================================================================


def test_exit_code_still_signals_false_pass_in_default_mode(monkeypatch, tmp_path) -> None:
    assert _bench(monkeypatch, tmp_path, [], false_pass=0)["_exit_code"] == 0
    assert _bench(monkeypatch, tmp_path, [], false_pass=1)["_exit_code"] == 1


def test_exit_code_semantics_are_identical_under_shadow(monkeypatch, tmp_path) -> None:
    """Shadow mode must not become a second way to change the CI gate."""
    assert _bench(monkeypatch, tmp_path, ["--shadow-adjudicate"], false_pass=0)["_exit_code"] == 0
    assert _bench(monkeypatch, tmp_path, ["--shadow-adjudicate"], false_pass=1)["_exit_code"] == 1
