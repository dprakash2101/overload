from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Callable, Coroutine
from typing import Any, Protocol

from overload.collection.models import ParsedRequest
from overload.collection.variables import VariableContext
from overload.engine.http_client import HttpClient
from overload.engine.models import (
    PatternConfig,
    RequestDistribution,
    RequestResult,
    RunProgress,
    Stats,
)

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[RunProgress], Coroutine[Any, Any, None]]


class LoadPattern(Protocol):
    async def execute(
        self,
        client: HttpClient,
        requests: list[ParsedRequest],
        variables: VariableContext,
        config: PatternConfig,
        run_id: str,
        cancel_event: asyncio.Event,
        on_progress: ProgressCallback | None = None,
    ) -> list[RequestResult]: ...


def _pick_request(
    requests: list[ParsedRequest],
    index: int,
    distribution: RequestDistribution,
) -> ParsedRequest:
    if distribution == RequestDistribution.RANDOM:
        return random.choice(requests)
    return requests[index % len(requests)]


async def _fire_one(
    client: HttpClient,
    request: ParsedRequest,
    variables: VariableContext,
    semaphore: asyncio.Semaphore,
) -> RequestResult:
    async with semaphore:
        return await client.execute(request, variables)


_last_emit_state: dict[str, tuple[int, float]] = {}


async def _emit_progress(
    callback: ProgressCallback | None,
    run_id: str,
    results: list[RequestResult],
    total: int,
    phase: str,
    start_time: float,
) -> None:
    if callback is None:
        return

    elapsed = time.monotonic() - start_time
    completed = len(results)

    prev_count, prev_time = _last_emit_state.get(run_id, (0, start_time))
    dt = time.monotonic() - prev_time
    dr = completed - prev_count
    instant_rps = round(dr / max(dt, 0.1), 1) if dt > 0.05 else 0.0
    _last_emit_state[run_id] = (completed, time.monotonic())

    status_codes: dict[int, int] = {}
    total_latency = 0.0
    error_count = 0
    for r in results:
        status_codes[r.status_code] = status_codes.get(r.status_code, 0) + 1
        total_latency += r.latency_ms
        if r.status_code < 200 or r.status_code >= 400:
            error_count += 1

    recent_slice = results[-20:] if results else []
    base_idx = max(0, completed - len(recent_slice))
    recent = [
        {
            "idx": base_idx + i,
            "name": r.request_name,
            "method": r.method,
            "status": r.status_code,
            "latency": round(r.latency_ms, 1),
            "url": r.url[:100],
            "error": r.error,
        }
        for i, r in enumerate(recent_slice)
    ]

    try:
        await callback(RunProgress(
            run_id=run_id,
            total_requests=total,
            completed_requests=completed,
            current_rps=instant_rps,
            phase=phase,
            elapsed_seconds=round(elapsed, 1),
            error_count=error_count,
            status_codes=status_codes,
            avg_latency_ms=round(total_latency / max(completed, 1), 1),
            recent_results=recent,
        ))
    except Exception:
        logger.exception("Error in progress callback")


async def _cancel_tasks(tasks: list[asyncio.Task]) -> None:
    for t in tasks:
        if not t.done():
            t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


class BurstPattern:
    async def execute(
        self,
        client: HttpClient,
        requests: list[ParsedRequest],
        variables: VariableContext,
        config: PatternConfig,
        run_id: str,
        cancel_event: asyncio.Event,
        on_progress: ProgressCallback | None = None,
    ) -> list[RequestResult]:
        n = config.total_requests
        sem = asyncio.Semaphore(config.concurrency)
        results: list[RequestResult] = []
        start_time = time.monotonic()

        logger.info("Burst: %d requests, concurrency=%d", n, config.concurrency)

        await _emit_progress(on_progress, run_id, results, n, "Preparing burst...", start_time)

        tasks = [
            asyncio.create_task(
                _fire_one(
                    client,
                    _pick_request(requests, i, config.distribution),
                    variables,
                    sem,
                )
            )
            for i in range(n)
        ]

        await _emit_progress(on_progress, run_id, results, n, f"Firing {n} requests...", start_time)

        progress_interval = max(n // 20, 1)
        for i, coro in enumerate(asyncio.as_completed(tasks)):
            if cancel_event.is_set():
                await _cancel_tasks(tasks)
                break
            result = await coro
            results.append(result)
            if (i + 1) % progress_interval == 0 or i == n - 1:
                await _emit_progress(on_progress, run_id, results, n, "running", start_time)

        return results


class RampPattern:
    async def execute(
        self,
        client: HttpClient,
        requests: list[ParsedRequest],
        variables: VariableContext,
        config: PatternConfig,
        run_id: str,
        cancel_event: asyncio.Event,
        on_progress: ProgressCallback | None = None,
    ) -> list[RequestResult]:
        start_rps = config.ramp_start_rps
        end_rps = config.ramp_end_rps
        step = config.step_rps
        step_dur = config.step_duration_seconds
        sem = asyncio.Semaphore(config.concurrency)
        all_results: list[RequestResult] = []
        start_time = time.monotonic()
        request_idx = 0

        total_estimate = sum(
            rps * step_dur
            for rps in range(start_rps, end_rps + 1, step)
        )

        logger.info("Ramp: %d -> %d req/s, step=%d, step_duration=%ds", start_rps, end_rps, step, step_dur)

        await _emit_progress(on_progress, run_id, all_results, total_estimate, "Preparing ramp test...", start_time)

        for rps in range(start_rps, end_rps + 1, step):
            if cancel_event.is_set():
                break

            phase = f"Ramping: {rps} req/s"
            interval = 1.0 / rps
            batch_tasks: list[asyncio.Task] = []
            batch_start = time.monotonic()

            for i in range(rps * step_dur):
                if cancel_event.is_set():
                    break
                delay = batch_start + i * interval - time.monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)
                req = _pick_request(requests, request_idx, config.distribution)
                request_idx += 1
                batch_tasks.append(
                    asyncio.create_task(_fire_one(client, req, variables, sem))
                )

            if cancel_event.is_set():
                await _cancel_tasks(batch_tasks)
                break

            batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)
            for r in batch_results:
                if isinstance(r, RequestResult):
                    all_results.append(r)

            await _emit_progress(on_progress, run_id, all_results, total_estimate, phase, start_time)

        return all_results


class LoadTestPattern:
    async def execute(
        self,
        client: HttpClient,
        requests: list[ParsedRequest],
        variables: VariableContext,
        config: PatternConfig,
        run_id: str,
        cancel_event: asyncio.Event,
        on_progress: ProgressCallback | None = None,
    ) -> list[RequestResult]:
        target_rps = config.target_rps
        ramp_up = config.ramp_up_seconds
        hold = config.hold_duration_seconds
        ramp_down = config.ramp_down_seconds
        sem = asyncio.Semaphore(config.concurrency)
        all_results: list[RequestResult] = []
        in_flight: list[asyncio.Task] = []
        start_time = time.monotonic()
        request_idx = 0

        total_duration = ramp_up + hold + ramp_down
        total_estimate = int(target_rps * (ramp_up / 2 + hold + ramp_down / 2))

        logger.info(
            "Load: target=%d req/s, ramp_up=%ds, hold=%ds, ramp_down=%ds",
            target_rps, ramp_up, hold, ramp_down,
        )

        await _emit_progress(on_progress, run_id, all_results, total_estimate, "Preparing load test...", start_time)

        async def _run_at_rps(rps: int, duration: float, phase: str) -> None:
            nonlocal request_idx
            if rps <= 0 or duration <= 0:
                return
            interval = 1.0 / rps
            phase_start = time.monotonic()
            i = 0
            while time.monotonic() - phase_start < duration:
                if cancel_event.is_set():
                    return
                delay = phase_start + i * interval - time.monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)
                req = _pick_request(requests, request_idx, config.distribution)
                request_idx += 1
                task = asyncio.create_task(_fire_one(client, req, variables, sem))
                task.add_done_callback(lambda t: all_results.append(t.result()) if not t.cancelled() and t.exception() is None else None)
                in_flight.append(task)
                i += 1
                if i % max(rps // 2, 1) == 0:
                    await _emit_progress(on_progress, run_id, all_results, total_estimate, phase, start_time)

        # Ramp up
        if ramp_up > 0:
            steps = max(ramp_up, 1)
            for s in range(steps):
                if cancel_event.is_set():
                    break
                current_rps = max(1, int(target_rps * (s + 1) / steps))
                await _run_at_rps(current_rps, 1.0, f"Ramping up: {current_rps} req/s")

        # Hold
        if not cancel_event.is_set():
            await _run_at_rps(target_rps, hold, f"Holding at {target_rps} req/s")

        # Ramp down
        if ramp_down > 0 and not cancel_event.is_set():
            steps = max(ramp_down, 1)
            for s in range(steps):
                if cancel_event.is_set():
                    break
                current_rps = max(1, int(target_rps * (steps - s) / steps))
                await _run_at_rps(current_rps, 1.0, f"Ramping down: {current_rps} req/s")

        if cancel_event.is_set():
            await _cancel_tasks(in_flight)
        else:
            pending = [t for t in in_flight if not t.done()]
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

        await _emit_progress(on_progress, run_id, all_results, total_estimate, "complete", start_time)
        return all_results


class StressPattern:
    async def execute(
        self,
        client: HttpClient,
        requests: list[ParsedRequest],
        variables: VariableContext,
        config: PatternConfig,
        run_id: str,
        cancel_event: asyncio.Event,
        on_progress: ProgressCallback | None = None,
    ) -> list[RequestResult]:
        start_rps = config.start_rps
        step = config.step_rps
        step_dur = config.step_duration_seconds
        max_rps = config.max_rps
        failure_threshold = config.failure_threshold_pct / 100.0
        sem = asyncio.Semaphore(config.concurrency)
        all_results: list[RequestResult] = []
        start_time = time.monotonic()
        request_idx = 0

        logger.info(
            "Stress: start=%d, step=%d, max=%d, failure_threshold=%.0f%%",
            start_rps, step, max_rps, config.failure_threshold_pct,
        )

        await _emit_progress(on_progress, run_id, all_results, 0, "Preparing stress test...", start_time)

        rps = start_rps
        breaking_point = 0

        while rps <= max_rps:
            if cancel_event.is_set():
                break

            phase = f"Stress: {rps} req/s"
            interval = 1.0 / rps
            batch_tasks: list[asyncio.Task] = []
            batch_start = time.monotonic()

            for i in range(rps * step_dur):
                if cancel_event.is_set():
                    break
                delay = batch_start + i * interval - time.monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)
                req = _pick_request(requests, request_idx, config.distribution)
                request_idx += 1
                batch_tasks.append(
                    asyncio.create_task(_fire_one(client, req, variables, sem))
                )

            if cancel_event.is_set():
                await _cancel_tasks(batch_tasks)
                break

            batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)
            step_results = [r for r in batch_results if isinstance(r, RequestResult)]
            all_results.extend(step_results)

            if step_results:
                errors = sum(1 for r in step_results if r.status_code < 200 or r.status_code >= 400)
                error_rate = errors / len(step_results)
                logger.info("Stress step %d req/s: error_rate=%.1f%%", rps, error_rate * 100)

                if error_rate >= failure_threshold:
                    breaking_point = rps
                    logger.info("Breaking point found at %d req/s (%.1f%% errors)", rps, error_rate * 100)
                    break

            await _emit_progress(on_progress, run_id, all_results, 0, phase, start_time)
            rps += step

        if breaking_point == 0 and not cancel_event.is_set():
            breaking_point = rps - step

        await _emit_progress(
            on_progress, run_id, all_results, 0,
            f"complete (breaking point: {breaking_point} req/s)", start_time,
        )
        return all_results


class SpikePattern:
    async def execute(
        self,
        client: HttpClient,
        requests: list[ParsedRequest],
        variables: VariableContext,
        config: PatternConfig,
        run_id: str,
        cancel_event: asyncio.Event,
        on_progress: ProgressCallback | None = None,
    ) -> list[RequestResult]:
        baseline_rps = config.baseline_rps
        spike_rps = config.spike_rps
        baseline_dur = config.baseline_duration_seconds
        spike_dur = config.spike_duration_seconds
        recovery_dur = config.recovery_duration_seconds
        sem = asyncio.Semaphore(config.concurrency)
        all_results: list[RequestResult] = []
        start_time = time.monotonic()
        request_idx = 0

        total_estimate = baseline_rps * baseline_dur + spike_rps * spike_dur + baseline_rps * recovery_dur

        logger.info(
            "Spike: baseline=%d, spike=%d, baseline_dur=%ds, spike_dur=%ds, recovery=%ds",
            baseline_rps, spike_rps, baseline_dur, spike_dur, recovery_dur,
        )

        await _emit_progress(on_progress, run_id, all_results, total_estimate, "Preparing spike test...", start_time)

        async def _run_phase(rps: int, duration: float, phase: str) -> None:
            nonlocal request_idx
            if rps <= 0 or duration <= 0:
                return
            interval = 1.0 / rps
            phase_start = time.monotonic()
            tasks: list[asyncio.Task] = []
            i = 0
            while time.monotonic() - phase_start < duration:
                if cancel_event.is_set():
                    await _cancel_tasks(tasks)
                    return
                delay = phase_start + i * interval - time.monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)
                req = _pick_request(requests, request_idx, config.distribution)
                request_idx += 1
                tasks.append(asyncio.create_task(_fire_one(client, req, variables, sem)))
                i += 1
                if i % max(rps, 1) == 0:
                    await _emit_progress(on_progress, run_id, all_results, total_estimate, phase, start_time)

            if cancel_event.is_set():
                await _cancel_tasks(tasks)
                return

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, RequestResult):
                    all_results.append(r)
            await _emit_progress(on_progress, run_id, all_results, total_estimate, phase, start_time)

        await _run_phase(baseline_rps, baseline_dur, f"Baseline: {baseline_rps} req/s")
        if not cancel_event.is_set():
            await _run_phase(spike_rps, spike_dur, f"SPIKE: {spike_rps} req/s")
        if not cancel_event.is_set():
            await _run_phase(baseline_rps, recovery_dur, f"Recovery: {baseline_rps} req/s")

        return all_results


class SoakPattern:
    async def execute(
        self,
        client: HttpClient,
        requests: list[ParsedRequest],
        variables: VariableContext,
        config: PatternConfig,
        run_id: str,
        cancel_event: asyncio.Event,
        on_progress: ProgressCallback | None = None,
    ) -> list[RequestResult]:
        rps = config.soak_rps
        duration = config.soak_duration_seconds
        sem = asyncio.Semaphore(config.concurrency)
        all_results: list[RequestResult] = []
        start_time = time.monotonic()
        request_idx = 0
        total_estimate = rps * duration

        logger.info("Soak: %d req/s for %ds", rps, duration)

        await _emit_progress(on_progress, run_id, all_results, total_estimate, "Preparing soak test...", start_time)

        interval = 1.0 / rps
        phase_start = time.monotonic()
        tasks: list[asyncio.Task] = []
        i = 0

        while time.monotonic() - phase_start < duration:
            if cancel_event.is_set():
                break
            delay = phase_start + i * interval - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            req = _pick_request(requests, request_idx, config.distribution)
            request_idx += 1
            task = asyncio.create_task(_fire_one(client, req, variables, sem))
            task.add_done_callback(
                lambda t: all_results.append(t.result()) if not t.cancelled() and t.exception() is None else None
            )
            tasks.append(task)
            i += 1

            if i % (rps * 5) == 0:
                elapsed_min = (time.monotonic() - phase_start) / 60
                phase = f"Soaking: {rps} req/s ({elapsed_min:.1f}m elapsed)"
                await _emit_progress(on_progress, run_id, all_results, total_estimate, phase, start_time)

        if cancel_event.is_set():
            await _cancel_tasks(tasks)
        else:
            pending = [t for t in tasks if not t.done()]
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

        await _emit_progress(on_progress, run_id, all_results, total_estimate, "complete", start_time)
        return all_results


class BreakpointPattern:
    async def execute(
        self,
        client: HttpClient,
        requests: list[ParsedRequest],
        variables: VariableContext,
        config: PatternConfig,
        run_id: str,
        cancel_event: asyncio.Event,
        on_progress: ProgressCallback | None = None,
    ) -> list[RequestResult]:
        start_rps = config.start_rps
        precision = config.precision_rps
        latency_threshold = config.latency_threshold_ms
        error_threshold = config.error_threshold_pct / 100.0
        max_rps = config.max_rps
        sem = asyncio.Semaphore(config.concurrency)
        all_results: list[RequestResult] = []
        start_time = time.monotonic()
        request_idx = 0

        logger.info(
            "Breakpoint: start=%d, precision=%d, latency_threshold=%.0fms, error_threshold=%.0f%%",
            start_rps, precision, latency_threshold, config.error_threshold_pct,
        )

        await _emit_progress(on_progress, run_id, all_results, 0, "Preparing breakpoint test...", start_time)

        low = start_rps
        high = max_rps
        last_good = start_rps
        breakpoint_rps = 0

        async def _probe(rps: int) -> tuple[float, float]:
            nonlocal request_idx
            interval = 1.0 / rps
            probe_tasks = []
            probe_start = time.monotonic()
            probe_count = rps * 5

            for idx in range(probe_count):
                if cancel_event.is_set():
                    break
                delay = probe_start + idx * interval - time.monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)
                req = _pick_request(requests, request_idx, config.distribution)
                request_idx += 1
                probe_tasks.append(asyncio.create_task(_fire_one(client, req, variables, sem)))

            probe_results = await asyncio.gather(*probe_tasks, return_exceptions=True)
            valid = [r for r in probe_results if isinstance(r, RequestResult)]
            all_results.extend(valid)

            if not valid:
                return 0.0, 1.0

            latencies = sorted(r.latency_ms for r in valid)
            p95_idx = int(len(latencies) * 0.95)
            p95 = latencies[min(p95_idx, len(latencies) - 1)]

            errors = sum(1 for r in valid if r.status_code < 200 or r.status_code >= 400)
            error_rate = errors / len(valid)

            return p95, error_rate

        # Binary search for breakpoint
        while high - low > precision:
            if cancel_event.is_set():
                break

            mid = (low + high) // 2
            phase = f"Probing: {mid} req/s"
            await _emit_progress(on_progress, run_id, all_results, 0, phase, start_time)

            p95, error_rate = await _probe(mid)
            logger.info("Probe %d req/s: p95=%.1fms, error_rate=%.1f%%", mid, p95, error_rate * 100)

            if p95 > latency_threshold or error_rate > error_threshold:
                high = mid
                breakpoint_rps = mid
            else:
                low = mid
                last_good = mid

        if breakpoint_rps == 0:
            breakpoint_rps = high

        await _emit_progress(
            on_progress, run_id, all_results, 0,
            f"complete (breakpoint: {breakpoint_rps} req/s, last good: {last_good} req/s)",
            start_time,
        )
        return all_results


class CustomPattern:
    async def execute(
        self,
        client: HttpClient,
        requests: list[ParsedRequest],
        variables: VariableContext,
        config: PatternConfig,
        run_id: str,
        cancel_event: asyncio.Event,
        on_progress: ProgressCallback | None = None,
    ) -> list[RequestResult]:
        stages = config.stages
        if not stages:
            logger.warning("Custom pattern: no stages defined")
            return []

        sem = asyncio.Semaphore(config.concurrency)
        all_results: list[RequestResult] = []
        start_time = time.monotonic()
        request_idx = 0

        total_estimate = sum(
            s.get("rps", 0) * s.get("duration", 0) for s in stages
        )

        logger.info("Custom: %d stages, estimated %d requests", len(stages), total_estimate)

        await _emit_progress(on_progress, run_id, all_results, total_estimate, "Preparing custom test...", start_time)

        for stage_num, stage in enumerate(stages, 1):
            if cancel_event.is_set():
                break

            rps = stage.get("rps", 10)
            duration = stage.get("duration", 30)
            phase = f"Stage {stage_num}/{len(stages)}: {rps} req/s for {duration}s"

            if rps <= 0 or duration <= 0:
                continue

            interval = 1.0 / rps
            stage_start = time.monotonic()
            tasks: list[asyncio.Task] = []
            i = 0

            while time.monotonic() - stage_start < duration:
                if cancel_event.is_set():
                    break
                delay = stage_start + i * interval - time.monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)
                req = _pick_request(requests, request_idx, config.distribution)
                request_idx += 1
                task = asyncio.create_task(_fire_one(client, req, variables, sem))
                task.add_done_callback(
                    lambda t: all_results.append(t.result()) if not t.cancelled() and t.exception() is None else None
                )
                tasks.append(task)
                i += 1

                if i % max(rps, 1) == 0:
                    await _emit_progress(on_progress, run_id, all_results, total_estimate, phase, start_time)

            if cancel_event.is_set():
                await _cancel_tasks(tasks)
                break

            pending = [t for t in tasks if not t.done()]
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

            await _emit_progress(on_progress, run_id, all_results, total_estimate, phase, start_time)

        await _emit_progress(on_progress, run_id, all_results, total_estimate, "complete", start_time)
        return all_results


PATTERNS: dict[str, LoadPattern] = {
    "burst": BurstPattern(),
    "ramp": RampPattern(),
    "load": LoadTestPattern(),
    "stress": StressPattern(),
    "spike": SpikePattern(),
    "soak": SoakPattern(),
    "breakpoint": BreakpointPattern(),
    "custom": CustomPattern(),
}


def get_pattern(name: str) -> LoadPattern:
    pattern = PATTERNS.get(name.lower())
    if pattern is None:
        available = ", ".join(PATTERNS.keys())
        raise ValueError(f"Unknown pattern: {name}. Available: {available}")
    return pattern
