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
