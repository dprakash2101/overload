from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Coroutine
from typing import Any

from overload.collection.models import ParsedRequest
from overload.collection.variables import VariableContext
from overload.engine.http_client import HttpClient
from overload.engine.models import PatternConfig, RequestResult, RunProgress

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[RunProgress], Coroutine[Any, Any, None]]


async def run_sequential(
    client: HttpClient,
    requests: list[ParsedRequest],
    variables: VariableContext,
    config: PatternConfig,
    run_id: str,
    cancel_event: asyncio.Event,
    on_progress: ProgressCallback | None = None,
) -> list[RequestResult]:
    iterations = config.iterations
    delay_ms = config.delay_ms
    total = len(requests) * iterations
    all_results: list[RequestResult] = []
    start_time = time.monotonic()

    logger.info(
        "Sequential: %d requests x %d iterations, delay=%dms",
        len(requests), iterations, delay_ms,
    )

    if on_progress:
        try:
            await on_progress(RunProgress(
                run_id=run_id,
                total_requests=total,
                completed_requests=0,
                current_rps=0,
                phase="Preparing sequential run...",
                elapsed_seconds=0,
            ))
        except Exception:
            logger.exception("Error in progress callback")

    for iteration in range(1, iterations + 1):
        if cancel_event.is_set():
            break

        for idx, request in enumerate(requests):
            if cancel_event.is_set():
                break

            result = await client.execute(request, variables)
            all_results.append(result)

            logger.debug(
                "Iter %d/%d, Req %d/%d: %s %s -> %d (%.1fms)",
                iteration, iterations, idx + 1, len(requests),
                result.method, result.url, result.status_code, result.latency_ms,
            )

            if on_progress:
                elapsed = time.monotonic() - start_time
                try:
                    await on_progress(RunProgress(
                        run_id=run_id,
                        total_requests=total,
                        completed_requests=len(all_results),
                        current_rps=len(all_results) / max(elapsed, 0.001),
                        phase=f"Iteration {iteration}/{iterations}: {request.name}",
                        elapsed_seconds=round(elapsed, 1),
                    ))
                except Exception:
                    logger.exception("Error in progress callback")

            if delay_ms > 0 and not (iteration == iterations and idx == len(requests) - 1):
                await asyncio.sleep(delay_ms / 1000.0)

    return all_results
