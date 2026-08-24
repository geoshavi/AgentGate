import argparse
import io
import sys
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from engine.config import DEFAULT_MODELS, load_config
from engine.orchestrator.engine import run_task
from engine.reporting.report import generate_report
from engine.runtime.gateway import LLMGateway


def _debug_task_text(args: argparse.Namespace) -> str:
    """The reported bug, from exactly one of the two accepted sources.

    ``--task-file`` exists because PowerShell 5.1 mangles embedded double quotes
    on their way to a native program, which bit the Coding Agent's live demo. A
    file has no quoting rules at all, so a bug report containing a traceback or
    a quoted error message can be passed verbatim.

    Both sources given is refused rather than silently preferring one: the two
    would disagree, and picking a winner would make the run's task text depend
    on a rule nobody read.
    """
    if args.task is not None and args.task_file is not None:
        raise ValueError("give the bug report as an argument or --task-file, not both")
    if args.task_file is not None:
        path = Path(args.task_file)
        if not path.is_file():
            raise ValueError(f"--task-file does not exist: {path}")
        text = path.read_text(encoding="utf-8")
    elif args.task is not None:
        text = args.task
    else:
        raise ValueError("a bug report is required: pass it as an argument or use --task-file")
    if not text.strip():
        raise ValueError("the bug report is empty")
    return text


def main() -> None:
    # Windows consoles default to cp1252 and agent-generated content routinely
    # contains characters it cannot encode (U+2264, U+2265, ...). Reconfigure
    # before any output so terminal rendering can never fail a completed run.
    # Guarded: under pytest capture stdout is not a TextIOWrapper and has no
    # reconfigure(), and there is nothing to fix in that case anyway.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(prog="engine")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run a coding task through the engine")
    run_parser.add_argument("task", help="Natural-language description of the task")
    run_parser.add_argument(
        "--workspace", default=None, help="Directory to write generated code into"
    )
    run_parser.add_argument("--provider", default="anthropic", help="Provider to use")

    code_parser = subparsers.add_parser(
        "code",
        help="Run a coding task inside a workspace, verified by AgentGate",
        description=(
            "Plans, edits files with real tools, runs tests, then puts the result "
            "through AgentGate verification. The workspace is edited IN PLACE. Exit "
            "code 0 means AgentGate verified the work, 1 means it was reviewed and "
            "blocked, 2 means the agent or runtime failed."
        ),
    )
    code_parser.add_argument("task", help="Natural-language description of the task")
    code_parser.add_argument(
        "--workspace", required=True, help="Directory the agent may read and edit (in place)"
    )
    code_parser.add_argument("--provider", default="anthropic", help="Provider to use")
    code_parser.add_argument(
        "--model", default=None, help="Model for the agent (default: this provider's coding model)"
    )
    code_parser.add_argument(
        "--judge-model", default=None, help="Model for the judge lenses (default: the judge model)"
    )
    code_parser.add_argument(
        "--budget", default=None, metavar="USD", help="Max spend for the whole run, e.g. 0.25"
    )
    code_parser.add_argument("--max-tokens", type=int, default=None, help="Token ceiling")
    code_parser.add_argument(
        "--timeout", type=float, default=None, metavar="SECONDS", help="Wall-clock deadline"
    )
    code_parser.add_argument("--max-turns", type=int, default=None, help="Model turns allowed")
    code_parser.add_argument(
        "--max-repairs", type=int, default=None, help="Verification-driven repair rounds"
    )
    code_parser.add_argument(
        "--json", dest="json_path", default=None, metavar="PATH", help="Also write the report JSON here"
    )

    debug_parser = subparsers.add_parser(
        "debug",
        help="Debug a reported failure: reproduce, diagnose, fix, prove, verify",
        description=(
            "Reproduces a reported failure, diagnoses it, applies the smallest fix, "
            "and proves the fix by re-running the frozen reproduction and the full "
            "regression suite before AgentGate verifies the change. The workspace is "
            "edited IN PLACE. Exit 0 means proven AND verified, 1 means reviewed and "
            "blocked or not proven, 2 means the run never reached a verdict."
        ),
        epilog=(
            "Commands are argv, never shell strings: pass one token per --repro/--suite "
            "flag, using the --flag=value form (required whenever a token starts with '-'). "
            "Example: --repro=python --repro=-m --repro=pytest --repro=-q "
            "--repro=tests/test_cart.py::test_empty_cart"
        ),
    )
    debug_parser.add_argument(
        "task",
        nargs="?",
        default=None,
        help="The reported bug, as a user would describe it (or use --task-file)",
    )
    debug_parser.add_argument(
        "--task-file",
        default=None,
        metavar="PATH",
        help=(
            "Read the reported bug from this file instead of the argument. Use this "
            "when the text contains quotes: PowerShell 5.1 mangles embedded double "
            "quotes on their way to a native program."
        ),
    )
    debug_parser.add_argument(
        "--workspace", required=True, help="Directory the agent may read and edit (in place)"
    )
    debug_parser.add_argument(
        "--repro",
        action="append",
        default=None,
        metavar="TOKEN",
        required=True,
        help="One argv token of the reproduction command. Repeat, once per token.",
    )
    debug_parser.add_argument(
        "--suite",
        action="append",
        default=None,
        metavar="TOKEN",
        # The default is stated literally rather than read from
        # debugagent.app.DEFAULT_SUITE_ARGV: building this parser happens for
        # every subcommand, so importing the Debug Agent to render a help
        # string would put it on `engine bench`'s import path. The value is
        # applied from that constant in the dispatch branch below, and
        # test_debugagent_cli.py asserts the two agree.
        help=(
            "One argv token of the regression suite command. Repeat, once per token. "
            "Default: python -m pytest -q"
        ),
    )
    debug_parser.add_argument("--provider", default="anthropic", help="Provider to use")
    debug_parser.add_argument(
        "--model", default=None, help="Model for the agent (default: this provider's coding model)"
    )
    debug_parser.add_argument(
        "--judge-model", default=None, help="Model for the judge lenses (default: the judge model)"
    )
    debug_parser.add_argument(
        "--budget", default=None, metavar="USD", help="Max spend for the whole run, e.g. 0.25"
    )
    debug_parser.add_argument("--max-tokens", type=int, default=None, help="Token ceiling")
    debug_parser.add_argument(
        "--timeout", type=float, default=None, metavar="SECONDS", help="Wall-clock deadline"
    )
    debug_parser.add_argument(
        "--repro-timeout",
        type=float,
        default=None,
        metavar="SECONDS",
        help="Deadline for one run of the reproduction or suite command",
    )
    debug_parser.add_argument("--max-turns", type=int, default=None, help="Model turns allowed")
    debug_parser.add_argument(
        "--max-repairs", type=int, default=None, help="Proof-driven repair rounds"
    )
    debug_parser.add_argument(
        "--max-files", type=int, default=None, help="Distinct files the fix may change"
    )
    debug_parser.add_argument(
        "--json",
        dest="json_path",
        default=None,
        metavar="PATH",
        help="Also write the report JSON here",
    )

    serve_parser = subparsers.add_parser(
        "serve", help="Run the code-review HTTP API (for n8n or other automation)"
    )
    serve_parser.add_argument("--port", type=int, default=8000)
    serve_parser.add_argument("--provider", default="anthropic", help="Provider to use")

    bench_parser = subparsers.add_parser(
        "bench", help="Run the evaluation benchmark against the review flow"
    )
    bench_parser.add_argument(
        "--category",
        default=None,
        choices=["security", "correctness", "quality", "edge_case"],
        help="Run only this category instead of the full 40-case benchmark",
    )
    bench_parser.add_argument(
        "--compare",
        type=int,
        default=None,
        metavar="EVAL_RUN_ID",
        help="After running, compare results against a previous eval_run_id",
    )
    bench_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate the dataset and budget, print the plan, make zero LLM calls",
    )
    bench_parser.add_argument("--provider", default="anthropic", help="Provider to use")

    args = parser.parse_args()

    if args.command == "run":
        config = load_config()
        gateway = LLMGateway.from_config(args.provider, config)
        workspace = Path(args.workspace) if args.workspace else Path(".engine/workspace")

        result = run_task(args.task, workspace, gateway, config, provider_name=args.provider)

        # Persist before displaying: the report is the durable artifact, so a
        # terminal that cannot render it must not cost us the file.
        report = generate_report(result)
        report_path = workspace.parent / "report.md"
        report_path.write_text(report, encoding="utf-8")
        print(report)

        sys.exit(0 if result.passed else 1)
    elif args.command == "code":
        from engine.codeagent.app import EXIT_ERROR, WorkspaceRejected, run_coding_task
        from engine.codeagent.limits import DEFAULT_LIMITS
        from engine.codeagent.report import render_report

        config = load_config()
        models = DEFAULT_MODELS[args.provider]
        overrides = {
            "session_timeout_seconds": args.timeout,
            "max_turns": args.max_turns,
            "max_repair_rounds": args.max_repairs,
        }
        limits = replace(
            DEFAULT_LIMITS, **{k: v for k, v in overrides.items() if v is not None}
        )

        try:
            gateway = LLMGateway.from_config(args.provider, config)
            code_result = run_coding_task(
                task_text=args.task,
                workspace_path=Path(args.workspace),
                gateway=gateway,
                model=args.model or models["coding"],
                judge_model=args.judge_model or models["judge"],
                provider_name=args.provider,
                limits=limits,
                # str -> Decimal, never float: see runtime/budget.py.
                planned_budget=Decimal(args.budget) if args.budget else config.planned_budget,
                max_tokens=args.max_tokens or config.max_tokens,
                artifacts_root=config.db_path.parent / "codeagent",
                db_path=config.db_path,
            )
        except WorkspaceRejected as exc:
            print(f"ERROR: {exc}")
            sys.exit(EXIT_ERROR)
        except Exception as exc:  # noqa: BLE001 - a CLI reports failures, it does not traceback
            print(f"ERROR: {type(exc).__name__}: {exc}")
            sys.exit(EXIT_ERROR)

        print(render_report(code_result.report))
        if code_result.report_path is not None:
            print(f"report    {code_result.report_path}")
        if code_result.log_path is not None:
            print(f"log       {code_result.log_path}")
        if args.json_path:
            Path(args.json_path).write_text(code_result.report.to_json(), encoding="utf-8")
            print(f"json      {args.json_path}")

        sys.exit(code_result.exit_code)
    elif args.command == "debug":
        from engine.debugagent.app import (
            DEFAULT_SUITE_ARGV,
            EXIT_ERROR,
            WorkspaceRejected,
            run_debug_task,
        )
        from engine.debugagent.limits import DEBUG_LIMITS
        from engine.debugagent.report import render_debug_report

        config = load_config()
        models = DEFAULT_MODELS[args.provider]

        try:
            task_text = _debug_task_text(args)
        except ValueError as exc:
            debug_parser.error(str(exc))

        overrides = {
            "session_timeout_seconds": args.timeout,
            "repro_timeout_seconds": args.repro_timeout,
            "max_turns": args.max_turns,
            "max_repair_rounds": args.max_repairs,
            "max_files_changed": args.max_files,
        }
        limits = replace(DEBUG_LIMITS, **{k: v for k, v in overrides.items() if v is not None})

        try:
            gateway = LLMGateway.from_config(args.provider, config)
            debug_result = run_debug_task(
                task_text=task_text,
                workspace_path=Path(args.workspace),
                repro_argv=list(args.repro),
                suite_argv=list(args.suite) if args.suite else list(DEFAULT_SUITE_ARGV),
                gateway=gateway,
                model=args.model or models["coding"],
                judge_model=args.judge_model or models["judge"],
                provider_name=args.provider,
                limits=limits,
                # str -> Decimal, never float: see runtime/budget.py.
                planned_budget=Decimal(args.budget) if args.budget else config.planned_budget,
                max_tokens=args.max_tokens or config.max_tokens,
                artifacts_root=config.db_path.parent / "debugagent",
                db_path=config.db_path,
            )
        except WorkspaceRejected as exc:
            print(f"ERROR: {exc}")
            sys.exit(EXIT_ERROR)
        except (TypeError, ValueError) as exc:
            # A malformed or policy-refused command. Nothing ran and nothing
            # was edited, so this is a usage error, not a run outcome.
            print(f"ERROR: {exc}")
            sys.exit(EXIT_ERROR)
        except Exception as exc:  # noqa: BLE001 - a CLI reports failures, it does not traceback
            print(f"ERROR: {type(exc).__name__}: {exc}")
            sys.exit(EXIT_ERROR)

        print(render_debug_report(debug_result.report))
        if debug_result.report_path is not None:
            print(f"report    {debug_result.report_path}")
        if debug_result.log_path is not None:
            print(f"log       {debug_result.log_path}")
        if args.json_path:
            Path(args.json_path).write_text(debug_result.report.to_json(), encoding="utf-8")
            print(f"json      {args.json_path}")

        sys.exit(debug_result.exit_code)
    elif args.command == "serve":
        from engine.api import serve

        serve(port=args.port, provider_name=args.provider)
    elif args.command == "bench":
        from engine.eval.report import (
            format_benchmark_report,
            format_comparison,
            format_dry_run_plan,
        )
        from engine.eval.runner import run_benchmark, select_cases
        from engine.state import db

        config = load_config()
        judge_model = DEFAULT_MODELS[args.provider]["judge"]
        cases = select_cases(args.category)

        if args.dry_run:
            if args.compare is not None:
                print(
                    f"WARNING: --compare {args.compare} is ignored with --dry-run -- "
                    "dry-run makes zero LLM calls, so there are no new results to compare. "
                    "Run without --dry-run to actually compare against a previous eval run.\n"
                )
            plan_text, errors = format_dry_run_plan(cases, judge_model)
            print(plan_text)
            sys.exit(1 if errors else 0)

        eval_run, results = run_benchmark(
            config=config, provider_name=args.provider, judge_model=judge_model, category=args.category
        )
        print(format_benchmark_report(eval_run, results))

        if args.compare is not None:
            with db.connect(config.db_path) as conn:
                previous = db.get_eval_run(conn, args.compare)
                if previous is None:
                    print(f"\nERROR: no eval run #{args.compare} found -- cannot compare.")
                    sys.exit(1)
                previous_results = db.get_eval_case_results(conn, args.compare)
            print()
            print(format_comparison(eval_run, results, previous, previous_results))

        # false_pass (the judge wrongly approving bad code) is the failure
        # mode this benchmark exists to catch -- treat it as a CI-style gate.
        sys.exit(0 if eval_run.false_pass == 0 else 1)


if __name__ == "__main__":
    main()
