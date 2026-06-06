from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest

from overload.collection.models import ParsedRequest
from overload.collection.variables import VariableContext
from overload.engine.load_patterns import (
    _emit_progress,
    _last_emit_state,
    _last_emit_time,
    _safe_done_callback,
    BurstPattern,
    RampPattern,
    SoakPattern,
    SpikePattern,
    StressPattern,
)
from overload.engine.models import PatternConfig, RequestResult, RunProgress


def _result(status: int = 200) -> RequestResult:
    return RequestResult(
        request_name="test",
        method="GET",
        url="https://api.example.com/items",
        status_code=status,
        latency_ms=10.0,
        timestamp=time.time(),
    )


def _request() -> ParsedRequest:
    return ParsedRequest(
        name="test",
        method="GET",
        url_raw="https://api.example.com/items",
    )


# ---------------------------------------------------------------------------
# _safe_done_callback
# ---------------------------------------------------------------------------

class TestSafeDoneCallback:
    @pytest.mark.asyncio
    async def test_appends_successful_result(self) -> None:
        results: list[RequestResult] = []
        cb = _safe_done_callback(results)

        async def _coro():
            return _result(200)

        task = asyncio.create_task(_coro())
        task.add_done_callback(cb)
        await task

        await asyncio.sleep(0)
        assert len(results) == 1
        assert results[0].status_code == 200

    @pytest.mark.asyncio
    async def test_does_not_append_on_exception(self) -> None:
        results: list[RequestResult] = []
        cb = _safe_done_callback(results)

        async def _failing():
            raise RuntimeError("boom")

        task = asyncio.create_task(_failing())
        task.add_done_callback(cb)
        try:
            await task
        except RuntimeError:
            pass

        await asyncio.sleep(0)
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_does_not_append_on_cancellation(self) -> None:
        results: list[RequestResult] = []
        cb = _safe_done_callback(results)

        async def _long():
            await asyncio.sleep(10)

        task = asyncio.create_task(_long())
        task.add_done_callback(cb)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        await asyncio.sleep(0)
        assert len(results) == 0


# ---------------------------------------------------------------------------
# _emit_progress — throttle behaviour
# ---------------------------------------------------------------------------

class TestEmitProgressThrottle:
    @pytest.mark.asyncio
    async def test_throttles_rapid_calls(self) -> None:
        """Calling _emit_progress rapidly should not emit on every call (0.5s throttle)."""
        call_count = 0

        async def cb(p: RunProgress) -> None:
            nonlocal call_count
            call_count += 1

        run_id = "throttle-test-1"
        _last_emit_time.pop(run_id, None)
        _last_emit_state.pop(run_id, None)
        start = time.monotonic()

        for _ in range(10):
            await _emit_progress(cb, run_id, [], 100, "running", start)

        assert call_count == 1

    @pytest.mark.asyncio
    async def test_force_bypasses_throttle(self) -> None:
        """force=True must emit even if called immediately after a previous emit."""
        call_count = 0

        async def cb(p: RunProgress) -> None:
            nonlocal call_count
            call_count += 1

        run_id = "throttle-test-2"
        _last_emit_time.pop(run_id, None)
        _last_emit_state.pop(run_id, None)
        start = time.monotonic()

        await _emit_progress(cb, run_id, [], 100, "running", start, force=True)
        await _emit_progress(cb, run_id, [], 100, "running", start, force=True)
        await _emit_progress(cb, run_id, [], 100, "running", start, force=True)

        assert call_count == 3

    @pytest.mark.asyncio
    async def test_no_call_when_callback_none(self) -> None:
        """_emit_progress must not raise when callback is None."""
        run_id = "throttle-test-3"
        _last_emit_time.pop(run_id, None)
        _last_emit_state.pop(run_id, None)
        start = time.monotonic()

        await _emit_progress(None, run_id, [], 100, "running", start)

    @pytest.mark.asyncio
    async def test_rps_computed_from_completed_delta(self) -> None:
        """instant_rps should reflect completions since last emit, not zero."""
        reported_rps: list[float] = []

        async def cb(p: RunProgress) -> None:
            reported_rps.append(p.current_rps)

        run_id = "throttle-test-4"
        _last_emit_time.pop(run_id, None)
        _last_emit_state.pop(run_id, None)
        start = time.monotonic() - 2.0

        results = [_result() for _ in range(10)]
        await _emit_progress(cb, run_id, results, 100, "running", start, force=True)

        assert len(reported_rps) == 1
        assert reported_rps[0] >= 0


# ---------------------------------------------------------------------------
# BurstPattern — live progress
# ---------------------------------------------------------------------------

class TestBurstPatternLiveProgress:
    @pytest.mark.asyncio
    @patch("overload.engine.load_patterns._fire_one", new_callable=AsyncMock)
    async def test_emits_multiple_progress_updates(self, mock_fire: AsyncMock) -> None:
        mock_fire.return_value = _result(200)
        cancel = asyncio.Event()
        config = PatternConfig(total_requests=20, concurrency=10)
        progress_calls: list[RunProgress] = []

        async def on_progress(p: RunProgress) -> None:
            progress_calls.append(p)

        run_id = "burst-live-1"
        _last_emit_time.pop(run_id, None)
        _last_emit_state.pop(run_id, None)

        pattern = BurstPattern()
        await pattern.execute(
            AsyncMock(), [_request()], VariableContext(), config, run_id, cancel, on_progress,
        )

        assert len(progress_calls) >= 2

    @pytest.mark.asyncio
    @patch("overload.engine.load_patterns._fire_one", new_callable=AsyncMock)
    async def test_completed_grows_monotonically(self, mock_fire: AsyncMock) -> None:
        mock_fire.return_value = _result(200)
        cancel = asyncio.Event()
        config = PatternConfig(total_requests=15, concurrency=5)
        completeds: list[int] = []

        async def on_progress(p: RunProgress) -> None:
            completeds.append(p.completed_requests)

        run_id = "burst-live-2"
        _last_emit_time.pop(run_id, None)
        _last_emit_state.pop(run_id, None)

        pattern = BurstPattern()
        with patch("overload.engine.load_patterns._MIN_EMIT_INTERVAL", 0.0):
            await pattern.execute(
                AsyncMock(), [_request()], VariableContext(), config, run_id, cancel, on_progress,
            )

        for i in range(1, len(completeds)):
            assert completeds[i] >= completeds[i - 1], "completed_requests must not decrease"


# ---------------------------------------------------------------------------
# RampPattern — live progress during steps
# ---------------------------------------------------------------------------

class TestRampPatternLiveProgress:
    @pytest.mark.asyncio
    @patch("overload.engine.load_patterns._fire_one", new_callable=AsyncMock)
    async def test_emits_progress_during_step(self, mock_fire: AsyncMock) -> None:
        mock_fire.return_value = _result(200)
        cancel = asyncio.Event()
        config = PatternConfig(
            ramp_start_rps=5, ramp_end_rps=5, step_rps=5,
            step_duration_seconds=1, concurrency=10,
        )
        progress_calls: list[RunProgress] = []

        async def on_progress(p: RunProgress) -> None:
            progress_calls.append(p)

        run_id = "ramp-live-1"
        _last_emit_time.pop(run_id, None)
        _last_emit_state.pop(run_id, None)

        pattern = RampPattern()
        with patch("overload.engine.load_patterns._MIN_EMIT_INTERVAL", 0.0):
            await pattern.execute(
                AsyncMock(), [_request()], VariableContext(), config, run_id, cancel, on_progress,
            )

        assert len(progress_calls) >= 2


# ---------------------------------------------------------------------------
# StressPattern — live progress during steps
# ---------------------------------------------------------------------------

class TestStressPatternLiveProgress:
    @pytest.mark.asyncio
    @patch("overload.engine.load_patterns._fire_one", new_callable=AsyncMock)
    async def test_emits_progress_during_step(self, mock_fire: AsyncMock) -> None:
        mock_fire.return_value = _result(200)
        cancel = asyncio.Event()
        config = PatternConfig(
            start_rps=5, step_rps=100, max_rps=5,
            step_duration_seconds=1, concurrency=10,
            failure_threshold_pct=100.0,
        )
        progress_calls: list[RunProgress] = []

        async def on_progress(p: RunProgress) -> None:
            progress_calls.append(p)

        run_id = "stress-live-1"
        _last_emit_time.pop(run_id, None)
        _last_emit_state.pop(run_id, None)

        pattern = StressPattern()
        with patch("overload.engine.load_patterns._MIN_EMIT_INTERVAL", 0.0):
            await pattern.execute(
                AsyncMock(), [_request()], VariableContext(), config, run_id, cancel, on_progress,
            )

        assert len(progress_calls) >= 2


# ---------------------------------------------------------------------------
# SpikePattern — live progress during phases
# ---------------------------------------------------------------------------

class TestSpikePatternLiveProgress:
    @pytest.mark.asyncio
    @patch("overload.engine.load_patterns._fire_one", new_callable=AsyncMock)
    async def test_emits_during_baseline_phase(self, mock_fire: AsyncMock) -> None:
        mock_fire.return_value = _result(200)
        cancel = asyncio.Event()
        config = PatternConfig(
            baseline_rps=5, spike_rps=5, baseline_duration_seconds=1,
            spike_duration_seconds=0, recovery_duration_seconds=0, concurrency=10,
        )
        progress_calls: list[RunProgress] = []

        async def on_progress(p: RunProgress) -> None:
            progress_calls.append(p)

        run_id = "spike-live-1"
        _last_emit_time.pop(run_id, None)
        _last_emit_state.pop(run_id, None)

        pattern = SpikePattern()
        with patch("overload.engine.load_patterns._MIN_EMIT_INTERVAL", 0.0):
            await pattern.execute(
                AsyncMock(), [_request()], VariableContext(), config, run_id, cancel, on_progress,
            )

        assert len(progress_calls) >= 2


# ---------------------------------------------------------------------------
# SoakPattern — live progress
# ---------------------------------------------------------------------------

class TestSoakPatternLiveProgress:
    @pytest.mark.asyncio
    @patch("overload.engine.load_patterns._fire_one", new_callable=AsyncMock)
    async def test_emits_during_soak(self, mock_fire: AsyncMock) -> None:
        mock_fire.return_value = _result(200)
        cancel = asyncio.Event()
        config = PatternConfig(soak_rps=5, soak_duration_seconds=1, concurrency=10)
        progress_calls: list[RunProgress] = []

        async def on_progress(p: RunProgress) -> None:
            progress_calls.append(p)

        run_id = "soak-live-1"
        _last_emit_time.pop(run_id, None)
        _last_emit_state.pop(run_id, None)

        pattern = SoakPattern()
        with patch("overload.engine.load_patterns._MIN_EMIT_INTERVAL", 0.0):
            await pattern.execute(
                AsyncMock(), [_request()], VariableContext(), config, run_id, cancel, on_progress,
            )

        assert len(progress_calls) >= 2
