from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import webbrowser

from overload import __version__

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="overload",
        description="Overload — Free load testing tool for Postman collections",
    )
    parser.add_argument("--version", action="version", version=f"overload {__version__}")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    subparsers = parser.add_subparsers(dest="command")

    # UI command (also the default)
    ui_parser = subparsers.add_parser("ui", help="Start the browser UI")
    ui_parser.add_argument("--port", type=int, default=3000, help="Port number (default: 3000)")
    ui_parser.add_argument("--no-browser", action="store_true", help="Don't open browser automatically")
    ui_parser.add_argument("--host", default="127.0.0.1", help="Host to bind to (default: 127.0.0.1)")

    # Run command
    run_parser = subparsers.add_parser("run", help="Run a load test from CLI")
    run_parser.add_argument("--collection", required=True, help="Path to Postman collection JSON")
    run_parser.add_argument("--environment", help="Path to Postman environment JSON")
    run_parser.add_argument(
        "--pattern",
        choices=["load", "stress", "spike", "soak", "ramp", "burst", "breakpoint", "custom", "ratelimit"],
        default="burst",
        help="Test pattern (default: burst)",
    )
    run_parser.add_argument("--requests", type=int, default=200, help="Total requests for burst (default: 200)")
    run_parser.add_argument("--concurrency", type=int, default=20, help="Max concurrent requests (default: 20)")
    run_parser.add_argument("--rps", type=int, default=50, help="Target requests per second")
    run_parser.add_argument("--duration", type=int, default=300, help="Test duration in seconds")
    run_parser.add_argument("--data", metavar="PATH", help="CSV file for data-driven testing (column names fill {{placeholders}})")
    run_parser.add_argument("--var", action="append", dest="vars", metavar="KEY=VALUE", help="Variable override")
    run_parser.add_argument("--save-responses", action="store_true", help="Save response bodies")
    run_parser.add_argument("--output", default="reports", help="Output directory for reports (default: reports/)")
    run_parser.add_argument("--format", choices=["html", "json", "csv"], default="html", help="Report format")
    run_parser.add_argument("--stages", help="Custom stages JSON: '[{\"duration\":60,\"rps\":100}]'")
    run_parser.add_argument("--timeout", type=float, default=30.0, help="Request timeout in seconds")
    run_parser.add_argument("--no-verify-ssl", action="store_true", help="Disable SSL verification")
    run_parser.add_argument(
        "--assert", action="append", dest="assertions", metavar="EXPR",
        help="Assertion threshold, e.g. 'p95_latency_ms<500' (repeatable)",
    )
    run_parser.add_argument("--junit", metavar="PATH", help="Write JUnit XML report to PATH")
    run_parser.add_argument("--open-report", action="store_true", help="Open HTML report in browser after run")
    run_parser.add_argument("--config", metavar="PATH", help="Path to overload.config.yaml")

    # Sequential command
    seq_parser = subparsers.add_parser("sequential", help="Run collection requests sequentially")
    seq_parser.add_argument("--collection", required=True, help="Path to Postman collection JSON")
    seq_parser.add_argument("--environment", help="Path to Postman environment JSON")
    seq_parser.add_argument("--iterations", type=int, default=1, help="Number of iterations (default: 1)")
    seq_parser.add_argument("--delay", type=int, default=0, help="Delay between requests in ms (default: 0)")
    seq_parser.add_argument("--data", metavar="PATH", help="CSV file for data-driven testing")
    seq_parser.add_argument("--var", action="append", dest="vars", metavar="KEY=VALUE", help="Variable override")
    seq_parser.add_argument("--output", default=".", help="Output directory")
    seq_parser.add_argument("--timeout", type=float, default=30.0, help="Request timeout in seconds")

    # MCP command
    subparsers.add_parser(
        "mcp",
        help="Start the MCP server (stdio) for Claude Code, Codex, and GitHub Copilot",
    )

    args = parser.parse_args()

    _setup_logging(args.debug if hasattr(args, "debug") else False)

    if args.command == "run":
        asyncio.run(_run_test(args))
    elif args.command == "sequential":
        asyncio.run(_run_sequential(args))
    elif args.command == "mcp":
        _start_mcp()
    else:
        _start_ui(args)


def _start_mcp() -> None:
    from overload.mcp_server import main as mcp_main
    mcp_main()


def _setup_logging(debug: bool) -> None:
    level = logging.DEBUG if debug else logging.WARNING
    if os.environ.get("OVERLOAD_DEBUG"):
        level = logging.DEBUG
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _parse_vars(var_list: list[str] | None) -> dict[str, str]:
    if not var_list:
        return {}
    result = {}
    for v in var_list:
        if "=" in v:
            key, value = v.split("=", 1)
            result[key.strip()] = value.strip()
    return result


def _start_ui(args: argparse.Namespace) -> None:
    import uvicorn

    from overload.web.app import create_app

    port = getattr(args, "port", 3000)
    host = getattr(args, "host", "127.0.0.1")
    no_browser = getattr(args, "no_browser", False)

    app = create_app(working_dir=os.getcwd())

    print(f"\n  OVERLOAD — Load Testing Tool v{__version__}")
    print(f"  Starting on http://{host}:{port}")
    print("  Open the in-app 'Docs' tab for help, or visit https://dprakash2101.github.io/overload/")
    print("  Press Ctrl+C to stop\n")

    if not no_browser:
        import threading
        threading.Timer(1.0, lambda: webbrowser.open(f"http://{host}:{port}")).start()

    uvicorn.run(app, host=host, port=port, log_level="warning")


async def _run_test(args: argparse.Namespace) -> None:
    from overload.collection.environment import parse_environment
    from overload.collection.parser import parse_collection
    from overload.collection.variables import VariableContext
    from overload.engine.http_client import HttpClient
    from overload.engine.load_patterns import get_pattern
    from overload.engine.models import PatternConfig, Stats, Threshold
    from overload.engine.rate_limiter import run_rate_limit_test
    from overload.report.exporters import export_csv, export_json
    from overload.report.generator import generate_report
    from overload.utils.naming import generate_run_id

    file_config: dict = {}
    file_thresholds: list[Threshold] = []
    if args.config:
        from overload.config_file import extract_config, extract_test_type, extract_thresholds, load_config
        raw = load_config(args.config)
        file_config = extract_config(raw)
        file_thresholds = extract_thresholds(raw)
        file_test_type = extract_test_type(raw)
        if file_test_type and args.pattern == "burst":
            args.pattern = file_test_type

    print(f"\n  OVERLOAD — {args.pattern.upper()} TEST")
    print(f"  Collection: {args.collection}")
    if args.config:
        print(f"  Config: {args.config}")

    collection = parse_collection(args.collection)
    print(f"  Requests: {len(collection.requests)}")

    env_vars = {}
    if args.environment:
        env_vars = parse_environment(args.environment)

    runtime_vars = _parse_vars(args.vars)
    variables = VariableContext(
        collection_vars=collection.variables,
        environment_vars=env_vars,
        runtime_vars=runtime_vars,
    )

    data_source = None
    if getattr(args, "data", None):
        from overload.collection.data_source import DataSource
        data_source = DataSource.from_csv(args.data)
        print(f"  Data: {args.data} ({len(data_source.rows)} rows, columns: {', '.join(data_source.columns)})")

    run_id = generate_run_id()
    cancel_event = asyncio.Event()
    print(f"  Run ID: {run_id}\n")

    def _cfg(cli_val, key, default, cast=None):
        if cli_val != default:
            return cli_val
        file_val = file_config.get(key)
        if file_val is not None:
            return cast(file_val) if cast else file_val
        return cli_val

    concurrency = _cfg(args.concurrency, "concurrency", 20, int)
    timeout = _cfg(args.timeout, "timeout_seconds", 30.0, float)
    rps = _cfg(args.rps, "target_rps", 50, int)
    duration = _cfg(args.duration, "hold_duration_seconds", 300, int)
    requests = _cfg(args.requests, "total_requests", 200, int)

    config = PatternConfig(
        concurrency=concurrency,
        timeout_seconds=timeout,
        verify_ssl=not args.no_verify_ssl,
        total_requests=requests,
        target_rps=rps,
        hold_duration_seconds=duration,
        soak_rps=rps,
        soak_duration_seconds=duration,
        ramp_end_rps=rps,
        start_rps=10,
        spike_rps=rps,
        rate_limit_cap=rps,
    )

    if args.stages:
        try:
            config.stages = json.loads(args.stages)
        except json.JSONDecodeError:
            print("  Error: Invalid stages JSON")
            sys.exit(1)
    elif file_config.get("stages"):
        config.stages = file_config["stages"]

    stats = Stats()
    ramp_rows: list[dict] = []
    completed = 0

    async def on_progress(progress):
        nonlocal completed
        if progress.completed_requests > completed:
            completed = progress.completed_requests
            pct = min(100, completed * 100 // max(progress.total_requests, completed, 1))
            bar = "#" * (pct // 5) + "-" * (20 - pct // 5)
            print(f"\r  [{bar}] {pct}% ({completed} requests) — {progress.phase}", end="", flush=True)
            if progress.phase == "complete":
                print()

    async with HttpClient(
        timeout=config.timeout_seconds,
        verify_ssl=config.verify_ssl,
        max_connections=config.concurrency * 2,
        data_source=data_source,
    ) as client:
        await client.prepare_collection_auth(collection.auth, variables)
        if args.pattern == "ratelimit":
            results, ramp_rows = await run_rate_limit_test(
                client, collection.requests, variables, config,
                run_id, cancel_event, on_progress,
            )
            stats.add_all(results)
        else:
            pattern = get_pattern(args.pattern)
            results = await pattern.execute(
                client, collection.requests, variables, config,
                run_id, cancel_event, on_progress,
            )
            stats.add_all(results)

    computed = stats.compute()
    if computed:
        print(f"\n  Results:")
        print(f"    Total: {computed['total']}  OK: {computed['ok']}  Errors: {computed['errors']}")
        lat = computed["latency"]
        print(f"    Latency — min: {lat['min']}ms  p95: {lat['p95']}ms  max: {lat['max']}ms")
        print(f"    Duration: {computed['duration_seconds']}s  Avg RPS: {computed['avg_rps']}")

    thresholds: list[Threshold] = []
    if args.assertions:
        from overload.engine.assertions import parse_threshold
        for expr in args.assertions:
            try:
                thresholds.append(parse_threshold(expr))
            except ValueError as e:
                print(f"\n  Error: {e}")
                sys.exit(2)
    elif file_thresholds:
        thresholds = file_thresholds

    verdict_failed = False
    verdict_data = None
    if thresholds and computed:
        from overload.engine.assertions import evaluate, print_verdict, write_junit_xml

        verdict = evaluate(computed, thresholds)
        print_verdict(verdict)
        verdict_data = {
            "passed": verdict.passed,
            "results": [
                {
                    "metric": r.metric,
                    "operator": r.operator,
                    "expected": r.expected,
                    "actual": round(r.actual, 2),
                    "passed": r.passed,
                }
                for r in verdict.results
            ],
        }

        if args.junit:
            write_junit_xml(verdict, args.junit, test_name=f"overload-{args.pattern}")
            print(f"  JUnit XML: {os.path.abspath(args.junit)}")

        verdict_failed = not verdict.passed

    report_config_dict = {"pattern": args.pattern, "concurrency": concurrency}
    report_path = ""
    if args.format in ("html", "json"):
        report_path = generate_report(
            stats, args.pattern, report_config_dict,
            run_id=run_id, ramp_rows=ramp_rows, output_dir=args.output,
            verdict=verdict_data,
        )
        if report_path:
            print(f"\n  Report: {os.path.abspath(report_path)}")

    if args.format == "json":
        json_path = export_json(stats, args.pattern, run_id, args.output, ramp_rows)
        if json_path:
            print(f"  JSON: {os.path.abspath(json_path)}")

    if args.format == "csv":
        csv_path = export_csv(stats, run_id, args.output)
        if csv_path:
            print(f"  CSV: {os.path.abspath(csv_path)}")

    if getattr(args, "open_report", False) and report_path:
        webbrowser.open(f"file://{os.path.abspath(report_path)}")

    print()

    if verdict_failed:
        sys.exit(1)


async def _run_sequential(args: argparse.Namespace) -> None:
    from overload.collection.environment import parse_environment
    from overload.collection.parser import parse_collection
    from overload.collection.variables import VariableContext
    from overload.engine.http_client import HttpClient
    from overload.engine.models import PatternConfig, Stats
    from overload.engine.runner import run_sequential
    from overload.report.generator import generate_report
    from overload.utils.naming import generate_run_id

    print(f"\n  OVERLOAD — SEQUENTIAL RUN")
    print(f"  Collection: {args.collection}")

    collection = parse_collection(args.collection)
    print(f"  Requests: {len(collection.requests)}")
    print(f"  Iterations: {args.iterations}  Delay: {args.delay}ms")

    env_vars = {}
    if args.environment:
        env_vars = parse_environment(args.environment)

    runtime_vars = _parse_vars(args.vars)
    variables = VariableContext(
        collection_vars=collection.variables,
        environment_vars=env_vars,
        runtime_vars=runtime_vars,
    )

    data_source = None
    if getattr(args, "data", None):
        from overload.collection.data_source import DataSource
        data_source = DataSource.from_csv(args.data)
        print(f"  Data: {args.data} ({len(data_source.rows)} rows)")

    run_id = generate_run_id()
    cancel_event = asyncio.Event()
    print(f"  Run ID: {run_id}\n")

    config = PatternConfig(
        iterations=args.iterations,
        delay_ms=args.delay,
        timeout_seconds=args.timeout,
    )

    async def on_progress(progress):
        print(f"\r  {progress.phase} — {progress.completed_requests}/{progress.total_requests}", end="", flush=True)
        if progress.phase == "complete":
            print()

    async with HttpClient(timeout=config.timeout_seconds, data_source=data_source) as client:
        results = await run_sequential(
            client, collection.requests, variables, config,
            run_id, cancel_event, on_progress,
        )

    stats = Stats()
    stats.add_all(results)
    computed = stats.compute()

    if computed:
        print(f"\n  Results:")
        print(f"    Total: {computed['total']}  OK: {computed['ok']}  Errors: {computed['errors']}")
        lat = computed["latency"]
        print(f"    Latency — min: {lat['min']}ms  p95: {lat['p95']}ms  max: {lat['max']}ms")

    report_config = {"iterations": args.iterations, "delay_ms": args.delay}
    report_path = generate_report(
        stats, "sequential", report_config,
        run_id=run_id, output_dir=args.output,
    )
    if report_path:
        print(f"\n  Report: {os.path.abspath(report_path)}")
    print()


if __name__ == "__main__":
    main()
