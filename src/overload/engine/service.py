from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from overload.collection.data_source import DataSource
from overload.collection.models import ParsedCollection, ParsedRequest
from overload.collection.variables import VariableContext
from overload.engine.assertions import evaluate
from overload.engine.http_client import HttpClient
from overload.engine.load_patterns import get_pattern
from overload.engine.models import (
    PatternConfig,
    RequestResult,
    RunProgress,
    Stats,
    TestType,
    Threshold,
)
from overload.engine.rate_limiter import run_rate_limit_test
from overload.engine.runner import run_sequential
from overload.report.generator import generate_report
from overload.report.responses import RESPONSES_FILENAME
from overload.utils.naming import generate_run_id, run_dir_name

logger = logging.getLogger(__name__)

_runs: dict[str, dict[str, Any]] = {}
_tasks: dict[str, asyncio.Task] = {}  # type: ignore[type-arg]
_cancel_events: dict[str, asyncio.Event] = {}
_progress: dict[str, RunProgress] = {}

ProgressCallback = Callable[[RunProgress], Awaitable[None]]


@dataclass
class RunResult:
    run_id: str
    test_type: str
    status: str
    stats: dict[str, Any] | None
    report_path: str | None
    verdict: dict[str, Any] | None
    ramp_rows: list[dict[str, Any]] = field(default_factory=list)


async def run_test(
    collection: ParsedCollection,
    test_type: str,
    config: PatternConfig,
    *,
    variables: VariableContext,
    requests: list[ParsedRequest] | None = None,
    thresholds: list[Threshold] | None = None,
    data_source: DataSource | None = None,
    output_dir: str = "reports",
    run_id: str | None = None,
    on_progress: ProgressCallback | None = None,
    cancel_event: asyncio.Event | None = None,
) -> RunResult:
    """Run a load test, store the result in _runs, and return a RunResult."""
    if run_id is None:
        run_id = generate_run_id()
    if cancel_event is None:
        cancel_event = asyncio.Event()

    effective_requests = requests if requests is not None else collection.requests
    stats = Stats()
    ramp_rows: list[dict[str, Any]] = []
    result: RunResult

    # Every result flows through this sink as it completes, so partial results
    # survive even a hard (asyncio-level) cancellation of the run task.
    collected: list[RequestResult] = []

    async def _tracked_progress(p: RunProgress) -> None:
        _progress[run_id] = p
        if on_progress:
            await on_progress(p)

    try:
        async with HttpClient(
            timeout=config.timeout_seconds,
            verify_ssl=config.verify_ssl,
            follow_redirects=config.follow_redirects,
            max_connections=config.concurrency * 2,
            save_responses=config.save_responses,
            data_source=data_source,
            result_sink=collected,
        ) as client:
            await client.prepare_collection_auth(collection.auth, variables)
            if test_type in (TestType.SEQUENTIAL, "sequential"):
                results = await run_sequential(
                    client, effective_requests, variables, config,
                    run_id, cancel_event, _tracked_progress,
                )
                stats.add_all(results)
            elif test_type in (TestType.RATE_LIMIT, "ratelimit"):
                results, ramp_rows = await run_rate_limit_test(
                    client, effective_requests, variables, config,
                    run_id, cancel_event, _tracked_progress,
                )
                stats.add_all(results)
            else:
                pattern = get_pattern(test_type)
                results = await pattern.execute(
                    client, effective_requests, variables, config,
                    run_id, cancel_event, _tracked_progress,
                )
                stats.add_all(results)

        stopped = cancel_event.is_set()
        computed = stats.compute()

        verdict_data = None
        if thresholds and computed and not stopped:
            verdict = evaluate(computed, thresholds)
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

        report_path = None
        if computed:
            report_path = generate_report(
                stats, test_type,
                {"test_type": test_type, "concurrency": config.concurrency,
                 "total_requests_configured": config.total_requests},
                run_id=run_id, ramp_rows=ramp_rows,
                output_dir=output_dir,
                verdict=verdict_data,
            )

        run_status = "stopped" if stopped else "complete"
        result = RunResult(
            run_id=run_id,
            test_type=test_type,
            status=run_status,
            stats=computed,
            report_path=report_path,
            verdict=verdict_data,
            ramp_rows=ramp_rows,
        )

    except asyncio.CancelledError:
        logger.info("Test hard-cancelled: %s", run_id)
        if stats.total == 0:
            stats.add_all(collected)
        computed = stats.compute() if stats.total > 0 else None
        report_path = None
        if computed:
            try:
                report_path = generate_report(
                    stats, test_type,
                    {"test_type": test_type, "concurrency": config.concurrency,
                     "total_requests_configured": config.total_requests},
                    run_id=run_id, ramp_rows=ramp_rows, output_dir=output_dir,
                )
            except Exception:
                logger.exception("Report generation failed after hard cancel: %s", run_id)
        result = RunResult(
            run_id=run_id,
            test_type=test_type,
            status="stopped",
            stats=computed,
            report_path=report_path,
            verdict=None,
            ramp_rows=ramp_rows,
        )

    except Exception:
        logger.exception("Test failed: %s", run_id)
        result = RunResult(
            run_id=run_id,
            test_type=test_type,
            status="error",
            stats=None,
            report_path=None,
            verdict=None,
        )

    responses_path = None
    if result.report_path:
        candidate = os.path.join(os.path.dirname(result.report_path), RESPONSES_FILENAME)
        if os.path.isfile(candidate):
            responses_path = candidate

    run_record = {
        "run_id": result.run_id,
        "test_type": result.test_type,
        "stats": result.stats,
        "ramp_rows": result.ramp_rows,
        "report_path": result.report_path,
        "responses_path": responses_path,
        "status": result.status,
        "verdict": result.verdict,
    }
    _runs[run_id] = run_record
    _tasks.pop(run_id, None)
    logger.info("Test %s: %s (%d requests)", result.status, run_id, stats.total)

    # Persist metadata sidecar so the run survives across restarts.
    if result.report_path:
        _write_run_sidecar(output_dir, run_record)

    # Emit final progress so callers (WebSocket, MCP) know the run is done.
    computed_final = result.stats
    if result.status == "stopped":
        final_phase = "complete (stopped)"
    elif result.status == "error":
        final_phase = "error"
    else:
        final_phase = "complete"
    await _tracked_progress(RunProgress(
        run_id=run_id,
        total_requests=computed_final["total"] if computed_final else stats.total,
        completed_requests=computed_final["total"] if computed_final else stats.total,
        current_rps=0,
        phase=final_phase,
        elapsed_seconds=computed_final["duration_seconds"] if computed_final else 0,
    ))

    return result


async def start_run(
    collection: ParsedCollection,
    test_type: str,
    config: PatternConfig,
    *,
    variables: VariableContext,
    requests: list[ParsedRequest] | None = None,
    thresholds: list[Threshold] | None = None,
    data_source: DataSource | None = None,
    output_dir: str = "reports",
    run_id: str | None = None,
    on_progress: ProgressCallback | None = None,
) -> str:
    """Start a run in the background and return the run_id immediately."""
    if run_id is None:
        run_id = generate_run_id()
    cancel_event = asyncio.Event()
    _cancel_events[run_id] = cancel_event
    _runs[run_id] = {"run_id": run_id, "test_type": test_type, "status": "running"}

    task = asyncio.create_task(
        run_test(
            collection, test_type, config,
            variables=variables,
            requests=requests,
            thresholds=thresholds,
            data_source=data_source,
            output_dir=output_dir,
            run_id=run_id,
            on_progress=on_progress,
            cancel_event=cancel_event,
        )
    )
    _tasks[run_id] = task
    return run_id


def get_run(run_id: str) -> dict[str, Any] | None:
    return _runs.get(run_id)


def get_latest_progress(run_id: str) -> RunProgress | None:
    return _progress.get(run_id)


async def stop_run(run_id: str) -> bool:
    """Gracefully stop a run. Returns True if a stop signal was sent."""
    cancel_event = _cancel_events.get(run_id)
    if cancel_event:
        cancel_event.set()
    task = _tasks.get(run_id)
    if task and not task.done():
        async def _watchdog(t: asyncio.Task) -> None:  # type: ignore[type-arg]
            await asyncio.sleep(10)
            if not t.done():
                t.cancel()
                logger.info("Watchdog: hard-cancelled after grace window: %s", run_id)
        asyncio.create_task(_watchdog(task))
        return True
    return cancel_event is not None


def is_running(run_id: str) -> bool:
    task = _tasks.get(run_id)
    return task is not None and not task.done()


def _write_run_sidecar(output_dir: str, run_record: dict[str, Any]) -> None:
    """Write meta.json inside the run folder for history persistence across restarts."""
    try:
        run_id = run_record["run_id"]
        run_dir = os.path.join(output_dir, run_dir_name(run_id))
        os.makedirs(run_dir, exist_ok=True)
        sidecar_path = os.path.join(run_dir, "meta.json")
        with open(sidecar_path, "w", encoding="utf-8") as fh:
            json.dump(run_record, fh, separators=(",", ":"))
    except OSError:
        logger.exception("Failed to write run sidecar: %s", run_record.get("run_id"))


def load_run_history(reports_dir: str) -> None:
    """Scan reports_dir for run folders (run_*/meta.json) and legacy *_meta.json
    sidecars, populating _runs with historical entries."""
    p = Path(reports_dir)
    if not p.is_dir():
        return
    meta_files = sorted(p.glob("run_*/meta.json")) + sorted(p.glob("*_meta.json"))
    for meta_file in meta_files:
        try:
            with open(meta_file, encoding="utf-8") as fh:
                data = json.load(fh)
            run_id = data.get("run_id")
            if run_id and run_id not in _runs:
                _runs[run_id] = data
                logger.debug("Loaded historical run: %s", run_id)
        except (json.JSONDecodeError, OSError, KeyError):
            logger.debug("Skipped unreadable sidecar: %s", meta_file)
