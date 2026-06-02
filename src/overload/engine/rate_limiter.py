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
_EXCEED_MULTIPLIER = 2
_PHASE_DURATION = 60.0


async def _run_phase(
    client: HttpClient,
    requests: list[ParsedRequest],
    variables: VariableContext,
    sem: asyncio.Semaphore,
    count: int,
    cancel_event: asyncio.Event,
    request_idx: int,
) -> tuple[list[RequestResult], int]:
    interval = _PHASE_DURATION / count if count > 0 else _PHASE_DURATION
    tasks: list[asyncio.Task] = []
    phase_start = time.monotonic()

    for i in range(count):
        if cancel_event.is_set():
            break
        delay = phase_start + i * interval - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)
        req = _pick_request(requests, request_idx, RequestDistribution.ROUND_ROBIN)
        request_idx += 1
        tasks.append(asyncio.create_task(_fire_one(client, req, variables, sem)))

    batch = await asyncio.gather(*tasks, return_exceptions=True)
    results = [r for r in batch if isinstance(r, RequestResult)]
    return results, request_idx


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
    concurrency = config.concurrency
    sem = asyncio.Semaphore(concurrency)
    all_results: list[RequestResult] = []
    request_idx = 0
    start_time = time.monotonic()

    logger.info("Rate Limit Test: cap=%d req/min, concurrency=%d", cap_rpm, concurrency)

    # Phase 1: Steady — send cap_rpm requests over 60 seconds (at the limit)
    if on_progress:
        await on_progress(RunProgress(
            run_id=run_id, total_requests=cap_rpm,
            completed_requests=0, current_rps=0,
            phase=f"Phase 1: Steady ({cap_rpm} req/min)", elapsed_seconds=0,
        ))

    p1_results, request_idx = await _run_phase(
        client, requests, variables, sem, cap_rpm, cancel_event, request_idx,
    )
    all_results.extend(p1_results)
    p1_total, p1_ok, p1_rl, p1_pct = _phase_stats(p1_results)

    logger.info("Phase 1 (steady): total=%d, ok=%d, 429=%d", p1_total, p1_ok, p1_rl)

    if on_progress:
        elapsed = time.monotonic() - start_time
        await on_progress(RunProgress(
            run_id=run_id, total_requests=cap_rpm,
            completed_requests=len(all_results),
            current_rps=round(cap_rpm / 60, 1),
            phase="Phase 1: Complete", elapsed_seconds=round(elapsed, 1),
        ))

    # Cooldown — sleep in 1-second ticks to respect cancellation
    if not cancel_event.is_set():
        logger.info("Cooldown: %ds", _COOLDOWN_SECONDS)
        if on_progress:
            elapsed = time.monotonic() - start_time
            await on_progress(RunProgress(
                run_id=run_id, total_requests=0,
                completed_requests=len(all_results), current_rps=0,
                phase=f"Cooldown: {_COOLDOWN_SECONDS}s",
                elapsed_seconds=round(elapsed, 1),
            ))
        cooldown_end = time.monotonic() + _COOLDOWN_SECONDS
        while time.monotonic() < cooldown_end:
            if cancel_event.is_set():
                break
            await asyncio.sleep(1)

    # Phase 2: Exceed — send 2× cap_rpm requests over 60 seconds
    exceed_count = cap_rpm * _EXCEED_MULTIPLIER
    p2_results: list[RequestResult] = []
    if not cancel_event.is_set():
        if on_progress:
            elapsed = time.monotonic() - start_time
            await on_progress(RunProgress(
                run_id=run_id, total_requests=exceed_count,
                completed_requests=0, current_rps=0,
                phase=f"Phase 2: Exceed ({exceed_count} req/min)",
                elapsed_seconds=round(elapsed, 1),
            ))

        p2_results, request_idx = await _run_phase(
            client, requests, variables, sem, exceed_count, cancel_event, request_idx,
        )
        all_results.extend(p2_results)

    p2_total, p2_ok, p2_rl, p2_pct = _phase_stats(p2_results)
    logger.info("Phase 2 (exceed): total=%d, ok=%d, 429=%d", p2_total, p2_ok, p2_rl)

    # Verdict
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
            f"(2× your {cap_rpm} req/min cap) and none were throttled."
        )

    logger.info("Verdict: %s — %s", verdict, message)

    if on_progress:
        elapsed = time.monotonic() - start_time
        await on_progress(RunProgress(
            run_id=run_id, total_requests=0,
            completed_requests=len(all_results), current_rps=0,
            phase="complete", elapsed_seconds=round(elapsed, 1),
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
