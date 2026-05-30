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


async def run_rate_limit_test(
    client: HttpClient,
    requests: list[ParsedRequest],
    variables: VariableContext,
    config: PatternConfig,
    run_id: str,
    cancel_event: asyncio.Event,
    on_progress: ProgressCallback | None = None,
) -> tuple[list[RequestResult], list[dict]]:
    cap = config.rate_limit_cap
    total_requests = config.rate_limit_requests
    concurrency = config.concurrency
    sem = asyncio.Semaphore(concurrency)
    all_results: list[RequestResult] = []
    ramp_rows: list[dict] = []
    start_time = time.monotonic()
    request_idx = 0

    logger.info("Rate Limit Test: cap=%d, requests=%d, concurrency=%d", cap, total_requests, concurrency)

    # Phase 1: Burst test
    if on_progress:
        await on_progress(RunProgress(
            run_id=run_id, total_requests=total_requests,
            completed_requests=0, current_rps=0,
            phase=f"Burst: {total_requests} requests", elapsed_seconds=0,
        ))

    burst_tasks = [
        asyncio.create_task(
            _fire_one(
                client,
                _pick_request(requests, i, RequestDistribution.ROUND_ROBIN),
                variables, sem,
            )
        )
        for i in range(total_requests)
    ]

    for coro in asyncio.as_completed(burst_tasks):
        if cancel_event.is_set():
            for t in burst_tasks:
                t.cancel()
            break
        result = await coro
        all_results.append(result)
        request_idx += 1

    # Phase 2: Ramp to find threshold
    if not cancel_event.is_set():
        logger.info("Rate limit ramp: 10 -> %d req/s", cap * 2)

        for rps in range(10, cap * 2 + 1, 10):
            if cancel_event.is_set():
                break

            interval = 1.0 / rps
            batch_tasks = []
            batch_start = time.monotonic()

            for i in range(rps):
                if cancel_event.is_set():
                    break
                delay = batch_start + i * interval - time.monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)
                req = _pick_request(requests, request_idx, RequestDistribution.ROUND_ROBIN)
                request_idx += 1
                batch_tasks.append(
                    asyncio.create_task(_fire_one(client, req, variables, sem))
                )

            batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)
            valid = [r for r in batch_results if isinstance(r, RequestResult)]
            all_results.extend(valid)

            total = len(valid)
            rl = sum(1 for r in valid if r.status_code == 429)
            ok = sum(1 for r in valid if 200 <= r.status_code < 400)
            pct = rl * 100 // total if total else 0

            ramp_rows.append({"rps": rps, "ok": ok, "rate_limited": rl, "pct": pct})

            logger.info("%d/s: ok=%d, 429=%d (%d%%)", rps, ok, rl, pct)

            if on_progress:
                elapsed = time.monotonic() - start_time
                await on_progress(RunProgress(
                    run_id=run_id, total_requests=0,
                    completed_requests=len(all_results),
                    current_rps=rps,
                    phase=f"Ramp: {rps} req/s ({pct}% throttled)",
                    elapsed_seconds=round(elapsed, 1),
                ))

            if pct >= 50:
                logger.info("Rate limiting confirmed at %d req/s", rps)
                break

    return all_results, ramp_rows
