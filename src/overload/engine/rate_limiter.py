from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Coroutine
from typing import Any

from overload.collection.models import ParsedRequest
from overload.collection.variables import VariableContext
from overload.engine.http_client import HttpClient
from overload.engine.load_patterns import _fire_one, _pick_request
from overload.engine.models import (
    PatternConfig,
    RequestDistribution,
    RequestResult,
    RunProgress,
)

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[RunProgress], Coroutine[Any, Any, None]]


_COOLDOWN_SECONDS = 15
_PHASE_DURATION = 60.0


def _safe_done_callback(results: list[RequestResult]):
    def _cb(t: asyncio.Task) -> None:
        if not t.cancelled() and t.exception() is None:
            results.append(t.result())
    return _cb


async def _run_phase(
    client: HttpClient,
    requests: list[ParsedRequest],
    variables: VariableContext,
    sem: asyncio.Semaphore,
    count: int,
    cancel_event: asyncio.Event,
    request_idx: int,
    on_progress: ProgressCallback | None,
    run_id: str,
    phase: str,
    prior_results: list[RequestResult],
    total_requests: int,
    start_time: float,
) -> tuple[list[RequestResult], int]:
    interval = _PHASE_DURATION / count if count > 0 else _PHASE_DURATION
    tasks: list[asyncio.Task] = []
    phase_results: list[RequestResult] = []
    phase_start = time.monotonic()

    for i in range(count):
        if cancel_event.is_set():
            break
        delay = phase_start + i * interval - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)
        req = _pick_request(requests, request_idx, RequestDistribution.ROUND_ROBIN)
        request_idx += 1
        task = asyncio.create_task(_fire_one(client, req, variables, sem))
        task.add_done_callback(_safe_done_callback(phase_results))
        tasks.append(task)

        if on_progress:
            all_so_far = prior_results + phase_results
            elapsed = time.monotonic() - start_time
            completed = len(all_so_far)
            error_count = sum(1 for r in all_so_far if r.status_code < 200 or r.status_code >= 400)
            status_codes: dict[int, int] = {}
            for r in all_so_far:
                status_codes[r.status_code] = status_codes.get(r.status_code, 0) + 1
            avg_lat = sum(r.latency_ms for r in all_so_far) / max(completed, 1)

            recent_slice = all_so_far[-20:]
            base_idx = max(0, completed - len(recent_slice))
            recent = [
                {
                    "idx": base_idx + j,
                    "name": r.request_name,
                    "method": r.method,
                    "status": r.status_code,
                    "latency": round(r.latency_ms, 1),
                    "url": r.url[:100],
                    "error": r.error,
                }
                for j, r in enumerate(recent_slice)
            ]

            tasks_sent = i + 1
            phase_rps = round(tasks_sent / max(time.monotonic() - phase_start, 0.1), 1)
            try:
                await on_progress(RunProgress(
                    run_id=run_id,
                    total_requests=total_requests,
                    completed_requests=completed,
                    current_rps=phase_rps,
                    phase=f"{phase} ({tasks_sent}/{count} sent)",
                    elapsed_seconds=round(elapsed, 1),
                    error_count=error_count,
                    status_codes=status_codes,
                    avg_latency_ms=round(avg_lat, 1),
                    recent_results=recent,
                ))
            except Exception:
                logger.exception("Error in rate limit progress callback")

    pending = [t for t in tasks if not t.done()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    return phase_results, request_idx


def _phase_stats(results: list[RequestResult]) -> tuple[int, int, int, int]:
    total = len(results)
    rl = sum(1 for r in results if r.status_code == 429)
    ok = sum(1 for r in results if 200 <= r.status_code < 400)
    pct = rl * 100 // total if total else 0
    return total, ok, rl, pct


async def run_rate_limit_test(
    client: HttpClient,
    requests: list[ParsedRequest],
    variables: VariableContext,
    config: PatternConfig,
    run_id: str,
    cancel_event: asyncio.Event,
    on_progress: ProgressCallback | None = None,
) -> tuple[list[RequestResult], list[dict]]:
    cap_rpm = config.rate_limit_cap
    exceed_multiplier = config.rate_limit_exceed_multiplier
    concurrency = config.concurrency
    sem = asyncio.Semaphore(concurrency)
    all_results: list[RequestResult] = []
    request_idx = 0
    start_time = time.monotonic()
    exceed_count = cap_rpm * exceed_multiplier
    total_requests = cap_rpm + exceed_count

    logger.info("Rate Limit Test: cap=%d req/min, concurrency=%d", cap_rpm, concurrency)

    if on_progress:
        await on_progress(RunProgress(
            run_id=run_id,
            total_requests=total_requests,
            completed_requests=0,
            current_rps=0,
            phase=f"Phase 1: Steady ({cap_rpm} req/min)",
            elapsed_seconds=0,
        ))

    p1_results, request_idx = await _run_phase(
        client, requests, variables, sem, cap_rpm, cancel_event, request_idx,
        on_progress, run_id, f"Phase 1: Steady ({cap_rpm} req/min)",
        [], total_requests, start_time,
    )
    all_results.extend(p1_results)
    p1_total, p1_ok, p1_rl, p1_pct = _phase_stats(p1_results)

    logger.info("Phase 1 (steady): total=%d, ok=%d, 429=%d", p1_total, p1_ok, p1_rl)

    if on_progress:
        elapsed = time.monotonic() - start_time
        status_codes: dict[int, int] = {}
        for r in all_results:
            status_codes[r.status_code] = status_codes.get(r.status_code, 0) + 1
        await on_progress(RunProgress(
            run_id=run_id,
            total_requests=total_requests,
            completed_requests=len(all_results),
            current_rps=round(cap_rpm / 60, 1),
            phase="Phase 1: Complete",
            elapsed_seconds=round(elapsed, 1),
            error_count=sum(1 for r in all_results if r.status_code < 200 or r.status_code >= 400),
            status_codes=status_codes,
        ))

    if not cancel_event.is_set():
        logger.info("Cooldown: %ds", _COOLDOWN_SECONDS)
        for remaining in range(_COOLDOWN_SECONDS, 0, -1):
            if cancel_event.is_set():
                break
            if on_progress:
                elapsed = time.monotonic() - start_time
                status_codes = {}
                for r in all_results:
                    status_codes[r.status_code] = status_codes.get(r.status_code, 0) + 1
                await on_progress(RunProgress(
                    run_id=run_id,
                    total_requests=total_requests,
                    completed_requests=len(all_results),
                    current_rps=0,
                    phase=f"Cooldown: {remaining}s remaining",
                    elapsed_seconds=round(elapsed, 1),
                    error_count=sum(1 for r in all_results if r.status_code < 200 or r.status_code >= 400),
                    status_codes=status_codes,
                ))
            await asyncio.sleep(1)

    p2_results: list[RequestResult] = []
    if not cancel_event.is_set():
        if on_progress:
            elapsed = time.monotonic() - start_time
            status_codes = {}
            for r in all_results:
                status_codes[r.status_code] = status_codes.get(r.status_code, 0) + 1
            await on_progress(RunProgress(
                run_id=run_id,
                total_requests=total_requests,
                completed_requests=len(all_results),
                current_rps=0,
                phase=f"Phase 2: Exceed ({exceed_count} req/min)",
                elapsed_seconds=round(elapsed, 1),
                error_count=sum(1 for r in all_results if r.status_code < 200 or r.status_code >= 400),
                status_codes=status_codes,
            ))

        p2_results, request_idx = await _run_phase(
            client, requests, variables, sem, exceed_count, cancel_event, request_idx,
            on_progress, run_id, f"Phase 2: Exceed ({exceed_count} req/min)",
            list(all_results), total_requests, start_time,
        )
        all_results.extend(p2_results)

    p2_total, p2_ok, p2_rl, p2_pct = _phase_stats(p2_results)
    logger.info("Phase 2 (exceed): total=%d, ok=%d, 429=%d", p2_total, p2_ok, p2_rl)

    if p1_rl > 0:
        verdict = "too_strict"
        message = (
            f"Rate limiting triggered too early. "
            f"Sent {p1_total} requests at {cap_rpm} req/min "
            f"(within your stated cap) but {p1_rl} were throttled."
        )
    elif p2_rl > 0:
        verdict = "working"
        message = (
            f"Rate limiting is working. "
            f"{p2_rl} of {p2_total} requests were throttled "
            f"after exceeding the {cap_rpm} req/min cap."
        )
    else:
        verdict = "not_working"
        message = (
            f"Rate limiting is NOT working. "
            f"Sent {p2_total} requests at {exceed_count} req/min "
            f"({exceed_multiplier}× your {cap_rpm} req/min cap) and none were throttled."
        )

    logger.info("Verdict: %s — %s", verdict, message)

    if on_progress:
        elapsed = time.monotonic() - start_time
        final_status_codes: dict[int, int] = {}
        for r in all_results:
            final_status_codes[r.status_code] = final_status_codes.get(r.status_code, 0) + 1
        await on_progress(RunProgress(
            run_id=run_id,
            total_requests=total_requests,
            completed_requests=len(all_results),
            current_rps=0,
            phase="complete",
            elapsed_seconds=round(elapsed, 1),
            error_count=sum(1 for r in all_results if r.status_code < 200 or r.status_code >= 400),
            status_codes=final_status_codes,
        ))

    phase_data: list[dict] = [
        {
            "phase": "steady",
            "label": f"Steady ({cap_rpm} req/min)",
            "rpm": cap_rpm,
            "total": p1_total,
            "ok": p1_ok,
            "rate_limited": p1_rl,
            "pct": p1_pct,
        },
        {
            "phase": "exceed",
            "label": f"Exceed ({exceed_count} req/min)",
            "rpm": exceed_count,
            "total": p2_total,
            "ok": p2_ok,
            "rate_limited": p2_rl,
            "pct": p2_pct,
        },
        {
            "phase": "verdict",
            "verdict": verdict,
            "message": message,
            "cap_rpm": cap_rpm,
        },
    ]

    return all_results, phase_data
