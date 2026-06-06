"""
MCP server for Overload — exposes load testing as MCP tools.

Supported clients (all speak the same MCP stdio protocol):
  Claude Code:     claude mcp add overload -- overload mcp
  Codex CLI:       codex mcp add overload -- overload mcp
  GitHub Copilot:  add to VS Code settings.json (see overload mcp --help)
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_MAX_CONCURRENCY = 200
_MAX_TOTAL_REQUESTS = 10_000

_PATTERN_DESCRIPTIONS: dict[str, str] = {
    "burst": "Fire a fixed number of concurrent requests as fast as possible. Best for quick smoke checks.",
    "load": "Sustained traffic at a target RPS with ramp-up and hold phases. Best for baseline measurement.",
    "stress": "Incrementally raise RPS until errors exceed a threshold. Finds the server's breaking point.",
    "spike": "Alternate between low baseline and high spike RPS. Tests recovery from sudden traffic surges.",
    "soak": "Sustain a constant load for a long duration. Detects memory leaks and degradation over time.",
    "ramp": "Linearly increase RPS from a start value to an end value. Shows how performance scales with load.",
    "breakpoint": "Binary-search for the exact RPS where latency or error rate crosses a threshold.",
    "custom": "Stage-based test — define arbitrary (duration, rps) steps for maximum flexibility.",
    "ratelimit": (
        "Two-phase validation: send at the stated rate-limit cap for 60 s, then 2× the cap for 60 s. "
        "Reports a verdict: 'working', 'not_working', or 'too_strict'."
    ),
    "sequential": "Run each request in the collection once, in order. Best for functional flow testing.",
}


# ---------------------------------------------------------------------------
# Tool functions — defined at module level so tests can call them directly.
# All are registered with FastMCP in main().
# ---------------------------------------------------------------------------

def list_patterns() -> list[dict[str, str]]:
    """List all available load test patterns with one-line descriptions."""
    return [
        {"name": name, "description": desc}
        for name, desc in _PATTERN_DESCRIPTIONS.items()
    ]


def describe_collection(path: str) -> dict[str, Any]:
    """
    Parse a Postman collection file and return its structure.

    Returns request names, methods, URLs, and all {{placeholder}} variables
    found across the collection — useful for planning CSV data files.
    """
    import re

    from overload.collection.parser import parse_collection
    from overload.collection.variables import VARIABLE_PATTERN

    if not os.path.isfile(path):
        return {"error": f"File not found: {path}"}
    try:
        collection = parse_collection(path)
    except Exception as exc:
        return {"error": str(exc)}

    all_text = " ".join(
        r.url_raw
        + " "
        + " ".join(r.headers.values())
        + " "
        + str(r.body.content or "")
        for r in collection.requests
    )
    placeholders = sorted(set(VARIABLE_PATTERN.findall(all_text)))

    return {
        "name": collection.name,
        "request_count": len(collection.requests),
        "requests": [
            {"name": r.name, "method": r.method, "url": r.url_raw}
            for r in collection.requests
        ],
        "placeholders": placeholders,
    }


async def run_load_test(
    collection_path: str,
    pattern: str = "burst",
    concurrency: int = 20,
    total_requests: int = 200,
    target_rps: int = 50,
    duration_seconds: int = 60,
    environment_path: str | None = None,
    data_csv: str | None = None,
    selected_requests: list[int] | None = None,
    output_dir: str = "reports",
    assertions: list[str] | None = None,
) -> dict[str, Any]:
    """
    Start a load test and return a run_id immediately (non-blocking).

    Poll get_run_status(run_id) until status is 'complete' or 'stopped',
    then call get_run_results(run_id) for the full summary and verdict.

    Args:
        collection_path: Absolute or relative path to a Postman collection JSON.
        pattern: One of burst|load|stress|spike|soak|ramp|breakpoint|custom|ratelimit|sequential.
        concurrency: Max concurrent requests (capped at 200).
        total_requests: Total requests for burst pattern (capped at 10 000).
        target_rps: Target requests per second (load, ramp, spike, soak, ratelimit).
        duration_seconds: Hold/soak/ramp duration in seconds.
        environment_path: Optional Postman environment JSON for variable values.
        data_csv: Optional CSV file — column names fill {{placeholders}} round-robin.
        selected_requests: Optional list of 0-based request indices to run (omit = run all).
        output_dir: Directory to write the HTML report (default: reports/).
        assertions: Optional threshold expressions, e.g. ["p95_latency_ms<500", "error_rate_pct<5"].

    Guardrails: concurrency is capped at 200, total_requests at 10 000.
    """
    from overload.collection.data_source import DataSource
    from overload.collection.environment import parse_environment
    from overload.collection.parser import parse_collection
    from overload.collection.variables import VariableContext
    from overload.engine import service as _svc
    from overload.engine.assertions import parse_threshold
    from overload.engine.models import PatternConfig, Threshold

    if not os.path.isfile(collection_path):
        return {"error": f"Collection not found: {collection_path}"}

    concurrency = min(concurrency, _MAX_CONCURRENCY)
    total_requests = min(total_requests, _MAX_TOTAL_REQUESTS)

    try:
        collection = parse_collection(collection_path)
    except Exception as exc:
        return {"error": f"Failed to parse collection: {exc}"}

    env_vars: dict[str, str] = {}
    if environment_path:
        if not os.path.isfile(environment_path):
            return {"error": f"Environment file not found: {environment_path}"}
        try:
            env_vars = parse_environment(environment_path)
        except Exception as exc:
            return {"error": f"Failed to parse environment: {exc}"}

    variables = VariableContext(
        collection_vars=collection.variables,
        environment_vars=env_vars,
    )

    ds = None
    if data_csv:
        if not os.path.isfile(data_csv):
            return {"error": f"CSV file not found: {data_csv}"}
        try:
            ds = DataSource.from_csv(data_csv)
        except Exception as exc:
            return {"error": f"Failed to load CSV: {exc}"}

    requests = None
    if selected_requests is not None:
        if len(selected_requests) == 0:
            return {"error": "selected_requests must not be empty"}
        requests = [
            collection.requests[i]
            for i in selected_requests
            if i < len(collection.requests)
        ]

    thresholds: list[Threshold] = []
    if assertions:
        for expr in assertions:
            try:
                thresholds.append(parse_threshold(expr))
            except ValueError as exc:
                return {"error": f"Invalid assertion '{expr}': {exc}"}

    config = PatternConfig(
        concurrency=concurrency,
        total_requests=total_requests,
        target_rps=target_rps,
        hold_duration_seconds=duration_seconds,
        soak_rps=target_rps,
        soak_duration_seconds=duration_seconds,
        ramp_end_rps=target_rps,
        spike_rps=target_rps,
        rate_limit_cap=target_rps,
    )

    run_id = await _svc.start_run(
        collection, pattern, config,
        variables=variables,
        requests=requests,
        thresholds=thresholds,
        data_source=ds,
        output_dir=output_dir,
    )

    return {
        "run_id": run_id,
        "message": "Test started. Poll get_run_status(run_id) until complete, then call get_run_results(run_id).",
        "collection": collection.name,
        "pattern": pattern,
        "request_count": len(requests) if requests is not None else len(collection.requests),
        "guardrails_applied": {
            "concurrency": concurrency,
            "total_requests": total_requests,
        },
    }


def get_run_status(run_id: str) -> dict[str, Any]:
    """
    Poll the status of a running or completed load test.

    Status values:
      'running'  — test is in progress; check phase and completed_requests for progress.
      'complete' — test finished normally.
      'stopped'  — test was stopped early; a partial report was generated.
      'error'    — test failed with an unexpected error.
    """
    from overload.engine import service as _svc

    run = _svc.get_run(run_id)
    if run is None:
        return {"error": f"Run not found: {run_id}"}

    status = run.get("status", "unknown")
    result: dict[str, Any] = {"run_id": run_id, "status": status}

    progress = _svc.get_latest_progress(run_id)
    if progress:
        result["phase"] = progress.phase
        result["completed_requests"] = progress.completed_requests
        result["total_requests"] = progress.total_requests
        result["elapsed_seconds"] = progress.elapsed_seconds
        result["current_rps"] = progress.current_rps
    elif status == "running":
        result["phase"] = "starting"

    return result


def get_run_results(run_id: str) -> dict[str, Any]:
    """
    Fetch the final results of a completed load test.

    Returns a performance summary (latency percentiles, RPS, error rate),
    verdict (if assertions were configured), and the path to the HTML report.
    Call this only after get_run_status returns status 'complete' or 'stopped'.
    """
    from overload.engine import service as _svc

    run = _svc.get_run(run_id)
    if run is None:
        return {"error": f"Run not found: {run_id}"}

    status = run.get("status", "unknown")
    if status == "running":
        return {"error": "Test is still running. Poll get_run_status(run_id) first."}

    result: dict[str, Any] = {
        "run_id": run_id,
        "test_type": run.get("test_type"),
        "status": status,
    }

    stats = run.get("stats")
    if stats:
        lat = stats["latency"]
        total = stats["total"]
        ok = stats["ok"]
        errors = stats["errors"]
        result["summary"] = {
            "total_requests": total,
            "successful": ok,
            "errors": errors,
            "success_rate_pct": round(ok / max(total, 1) * 100, 2),
            "error_rate_pct": round(errors / max(total, 1) * 100, 2),
            "avg_rps": stats["avg_rps"],
            "duration_seconds": stats["duration_seconds"],
            "latency_p50_ms": lat["median"],
            "latency_p95_ms": lat["p95"],
            "latency_p99_ms": lat["p99"],
            "latency_max_ms": lat["max"],
        }

    verdict = run.get("verdict")
    if verdict is not None:
        result["verdict"] = {
            "passed": verdict["passed"],
            "assertions": verdict["results"],
        }

    if run.get("report_path"):
        result["report_path"] = run["report_path"]

    return result


async def stop_run(run_id: str) -> dict[str, str]:
    """
    Gracefully stop a running load test.

    The test stops cooperatively (cancel event + 10-second grace window),
    then generates a partial report from whatever data was collected.
    Returns immediately; the actual stop completes asynchronously.
    """
    from overload.engine import service as _svc

    run = _svc.get_run(run_id)
    if run is None:
        return {"error": f"Run not found: {run_id}"}

    sent = await _svc.stop_run(run_id)
    if sent:
        return {
            "status": "ok",
            "message": "Stop signal sent. A partial report will be generated. Poll get_run_status for completion.",
        }
    return {"status": "ok", "message": "Run has already completed."}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _registration_instructions() -> str:
    return (
        "\n  MCP client registration:\n"
        "    Claude Code:     claude mcp add overload -- overload mcp\n"
        "    Codex CLI:       codex mcp add overload -- overload mcp\n"
        "    GitHub Copilot:  add to VS Code settings.json:\n"
        '      "mcpServers": {"overload": {"command": "overload", "args": ["mcp"]}}\n'
    )


def main() -> None:
    """Start the Overload MCP server (stdio transport)."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise ImportError(
            "The 'mcp' package is required. Install with: pip install 'overload-cli[mcp]'"
        ) from exc

    mcp = FastMCP(
        "overload",
        instructions=(
            "Overload is a load testing tool for Postman collections. "
            "Workflow: (1) describe_collection to inspect the file, "
            "(2) run_load_test to start a test (returns run_id immediately), "
            "(3) get_run_status to poll until complete/stopped, "
            "(4) get_run_results for the final summary and verdict. "
            "Use list_patterns for available test types. "
            "Use stop_run to cancel an active test and get a partial report."
        ),
    )

    for fn in (
        list_patterns,
        describe_collection,
        run_load_test,
        get_run_status,
        get_run_results,
        stop_run,
    ):
        mcp.tool()(fn)

    print(_registration_instructions())
    mcp.run()
