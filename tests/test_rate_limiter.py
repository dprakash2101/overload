from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest

from overload.collection.models import ParsedRequest
from overload.collection.variables import VariableContext
from overload.engine.models import PatternConfig, RequestResult, RunProgress
from overload.engine.rate_limiter import (
    _phase_stats,
    _run_phase,
    run_rate_limit_test,
)


def _result(status: int = 200) -> RequestResult:
    return RequestResult(
        request_name="test",
        method="GET",
        url="https://api.example.com/items",
        status_code=status,
        latency_ms=50.0,
        timestamp=time.time(),
    )


def _request() -> ParsedRequest:
    return ParsedRequest(
        name="get-items",
        method="GET",
        url_raw="https://api.example.com/items",
    )


# ---------------------------------------------------------------------------
# _phase_stats
# ---------------------------------------------------------------------------

class TestPhaseStats:
    def test_all_ok(self) -> None:
        total, ok, rl, pct = _phase_stats([_result(200) for _ in range(10)])
        assert total == 10
        assert ok == 10
        assert rl == 0
        assert pct == 0

    def test_all_rate_limited(self) -> None:
        total, ok, rl, pct = _phase_stats([_result(429) for _ in range(5)])
        assert total == 5
        assert ok == 0
        assert rl == 5
        assert pct == 100

    def test_mixed_responses(self) -> None:
        results = [_result(200)] * 7 + [_result(429)] * 3
        total, ok, rl, pct = _phase_stats(results)
        assert total == 10
        assert ok == 7
        assert rl == 3
        assert pct == 30

    def test_empty_list(self) -> None:
        total, ok, rl, pct = _phase_stats([])
        assert (total, ok, rl, pct) == (0, 0, 0, 0)

    def test_3xx_counted_as_ok(self) -> None:
        results = [_result(301), _result(200), _result(429)]
        _, ok, rl, _ = _phase_stats(results)
        assert ok == 2
        assert rl == 1

    def test_5xx_not_counted_as_ok_or_rl(self) -> None:
        results = [_result(500), _result(200)]
        total, ok, rl, _ = _phase_stats(results)
        assert total == 2
        assert ok == 1
        assert rl == 0

    def test_client_errors_not_counted_as_rl(self) -> None:
        results = [_result(400), _result(403), _result(429)]
        _, ok, rl, _ = _phase_stats(results)
        assert ok == 0
        assert rl == 1


# ---------------------------------------------------------------------------
# _run_phase
# ---------------------------------------------------------------------------

class TestRunPhase:
    @pytest.mark.asyncio
    @patch("overload.engine.rate_limiter._PHASE_DURATION", 0.05)
    @patch("overload.engine.rate_limiter._fire_one", new_callable=AsyncMock)
    async def test_fires_correct_count(self, mock_fire: AsyncMock) -> None:
        mock_fire.return_value = _result(200)
        sem = asyncio.Semaphore(10)
        cancel = asyncio.Event()

        results, next_idx = await _run_phase(
            AsyncMock(), [_request()], VariableContext(), sem, 5, cancel, 0,
            None, "run-1", "Phase 1", [], 5, time.monotonic(),
        )
        assert len(results) == 5
        assert next_idx == 5
        assert mock_fire.call_count == 5

    @pytest.mark.asyncio
    @patch("overload.engine.rate_limiter._PHASE_DURATION", 0.05)
    @patch("overload.engine.rate_limiter._fire_one", new_callable=AsyncMock)
    async def test_returns_updated_index(self, mock_fire: AsyncMock) -> None:
        mock_fire.return_value = _result(200)
        sem = asyncio.Semaphore(10)
        cancel = asyncio.Event()

        _, next_idx = await _run_phase(
            AsyncMock(), [_request()], VariableContext(), sem, 3, cancel, 10,
            None, "run-1", "Phase 1", [], 3, time.monotonic(),
        )
        assert next_idx == 13

    @pytest.mark.asyncio
    @patch("overload.engine.rate_limiter._PHASE_DURATION", 0.05)
    @patch("overload.engine.rate_limiter._fire_one", new_callable=AsyncMock)
    async def test_zero_count(self, mock_fire: AsyncMock) -> None:
        sem = asyncio.Semaphore(10)
        cancel = asyncio.Event()

        results, next_idx = await _run_phase(
            AsyncMock(), [_request()], VariableContext(), sem, 0, cancel, 0,
            None, "run-1", "Phase 1", [], 0, time.monotonic(),
        )
        assert len(results) == 0
        assert next_idx == 0
        mock_fire.assert_not_called()

    @pytest.mark.asyncio
    @patch("overload.engine.rate_limiter._PHASE_DURATION", 0.5)
    @patch("overload.engine.rate_limiter._fire_one", new_callable=AsyncMock)
    async def test_respects_cancellation(self, mock_fire: AsyncMock) -> None:
        cancel = asyncio.Event()
        call_count = 0

        async def fire_then_cancel(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count >= 3:
                cancel.set()
            return _result(200)

        mock_fire.side_effect = fire_then_cancel
        sem = asyncio.Semaphore(10)

        results, _ = await _run_phase(
            AsyncMock(), [_request()], VariableContext(), sem, 20, cancel, 0,
            None, "run-1", "Phase 1", [], 20, time.monotonic(),
        )
        assert len(results) < 20

    @pytest.mark.asyncio
    @patch("overload.engine.rate_limiter._PHASE_DURATION", 0.05)
    @patch("overload.engine.rate_limiter._fire_one", new_callable=AsyncMock)
    async def test_filters_out_exceptions(self, mock_fire: AsyncMock) -> None:
        call_count = 0

        async def sometimes_fail(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 3:
                raise RuntimeError("network error")
            return _result(200)

        mock_fire.side_effect = sometimes_fail
        sem = asyncio.Semaphore(10)
        cancel = asyncio.Event()

        results, _ = await _run_phase(
            AsyncMock(), [_request()], VariableContext(), sem, 5, cancel, 0,
            None, "run-1", "Phase 1", [], 5, time.monotonic(),
        )
        assert len(results) == 4


# ---------------------------------------------------------------------------
# run_rate_limit_test — verdict logic
# ---------------------------------------------------------------------------

class TestRateLimitVerdictWorking:
    @pytest.mark.asyncio
    @patch("overload.engine.rate_limiter._PHASE_DURATION", 0.05)
    @patch("overload.engine.rate_limiter._COOLDOWN_SECONDS", 0)
    @patch("overload.engine.rate_limiter._fire_one", new_callable=AsyncMock)
    async def test_working_verdict(self, mock_fire: AsyncMock) -> None:
        cap = 5
        call_count = 0

        async def simulate_rate_limit(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return _result(200 if call_count <= cap else 429)

        mock_fire.side_effect = simulate_rate_limit
        cancel = asyncio.Event()
        config = PatternConfig(rate_limit_cap=cap, concurrency=10)

        results, phase_data = await run_rate_limit_test(
            AsyncMock(), [_request()], VariableContext(), config,
            "run-1", cancel,
        )

        verdict = next(r for r in phase_data if r["phase"] == "verdict")
        assert verdict["verdict"] == "working"
        assert verdict["cap_rpm"] == cap

        steady = next(r for r in phase_data if r["phase"] == "steady")
        assert steady["rate_limited"] == 0

        exceed = next(r for r in phase_data if r["phase"] == "exceed")
        assert exceed["rate_limited"] > 0


class TestRateLimitVerdictNotWorking:
    @pytest.mark.asyncio
    @patch("overload.engine.rate_limiter._PHASE_DURATION", 0.05)
    @patch("overload.engine.rate_limiter._COOLDOWN_SECONDS", 0)
    @patch("overload.engine.rate_limiter._fire_one", new_callable=AsyncMock)
    async def test_not_working_verdict(self, mock_fire: AsyncMock) -> None:
        mock_fire.return_value = _result(200)
        cancel = asyncio.Event()
        config = PatternConfig(rate_limit_cap=5, concurrency=10)

        _, phase_data = await run_rate_limit_test(
            AsyncMock(), [_request()], VariableContext(), config,
            "run-2", cancel,
        )

        verdict = next(r for r in phase_data if r["phase"] == "verdict")
        assert verdict["verdict"] == "not_working"
        assert "NOT working" in verdict["message"]


class TestRateLimitVerdictTooStrict:
    @pytest.mark.asyncio
    @patch("overload.engine.rate_limiter._PHASE_DURATION", 0.05)
    @patch("overload.engine.rate_limiter._COOLDOWN_SECONDS", 0)
    @patch("overload.engine.rate_limiter._fire_one", new_callable=AsyncMock)
    async def test_too_strict_verdict(self, mock_fire: AsyncMock) -> None:
        mock_fire.return_value = _result(429)
        cancel = asyncio.Event()
        config = PatternConfig(rate_limit_cap=5, concurrency=10)

        _, phase_data = await run_rate_limit_test(
            AsyncMock(), [_request()], VariableContext(), config,
            "run-3", cancel,
        )

        verdict = next(r for r in phase_data if r["phase"] == "verdict")
        assert verdict["verdict"] == "too_strict"
        assert "too early" in verdict["message"].lower()


# ---------------------------------------------------------------------------
# run_rate_limit_test — structure and data flow
# ---------------------------------------------------------------------------

class TestRateLimitPhaseData:
    @pytest.mark.asyncio
    @patch("overload.engine.rate_limiter._PHASE_DURATION", 0.05)
    @patch("overload.engine.rate_limiter._COOLDOWN_SECONDS", 0)
    @patch("overload.engine.rate_limiter._fire_one", new_callable=AsyncMock)
    async def test_returns_three_entries(self, mock_fire: AsyncMock) -> None:
        mock_fire.return_value = _result(200)
        cancel = asyncio.Event()
        config = PatternConfig(rate_limit_cap=3, concurrency=10)

        _, phase_data = await run_rate_limit_test(
            AsyncMock(), [_request()], VariableContext(), config,
            "run-4", cancel,
        )
        assert len(phase_data) == 3
        assert [r["phase"] for r in phase_data] == ["steady", "exceed", "verdict"]

    @pytest.mark.asyncio
    @patch("overload.engine.rate_limiter._PHASE_DURATION", 0.05)
    @patch("overload.engine.rate_limiter._COOLDOWN_SECONDS", 0)
    @patch("overload.engine.rate_limiter._fire_one", new_callable=AsyncMock)
    async def test_steady_phase_rpm_matches_cap(self, mock_fire: AsyncMock) -> None:
        mock_fire.return_value = _result(200)
        cancel = asyncio.Event()
        config = PatternConfig(rate_limit_cap=7, concurrency=10)

        _, phase_data = await run_rate_limit_test(
            AsyncMock(), [_request()], VariableContext(), config,
            "run-5", cancel,
        )
        steady = phase_data[0]
        assert steady["rpm"] == 7
        assert steady["total"] == 7

    @pytest.mark.asyncio
    @patch("overload.engine.rate_limiter._PHASE_DURATION", 0.05)
    @patch("overload.engine.rate_limiter._COOLDOWN_SECONDS", 0)
    @patch("overload.engine.rate_limiter._fire_one", new_callable=AsyncMock)
    async def test_exceed_phase_rpm_is_double(self, mock_fire: AsyncMock) -> None:
        mock_fire.return_value = _result(200)
        cancel = asyncio.Event()
        config = PatternConfig(rate_limit_cap=4, concurrency=10)

        _, phase_data = await run_rate_limit_test(
            AsyncMock(), [_request()], VariableContext(), config,
            "run-6", cancel,
        )
        exceed = phase_data[1]
        assert exceed["rpm"] == 8
        assert exceed["total"] == 8

    @pytest.mark.asyncio
    @patch("overload.engine.rate_limiter._PHASE_DURATION", 0.05)
    @patch("overload.engine.rate_limiter._COOLDOWN_SECONDS", 0)
    @patch("overload.engine.rate_limiter._fire_one", new_callable=AsyncMock)
    async def test_phase_labels(self, mock_fire: AsyncMock) -> None:
        mock_fire.return_value = _result(200)
        cancel = asyncio.Event()
        config = PatternConfig(rate_limit_cap=10, concurrency=10)

        _, phase_data = await run_rate_limit_test(
            AsyncMock(), [_request()], VariableContext(), config,
            "run-7", cancel,
        )
        assert "10 req/min" in phase_data[0]["label"]
        assert "20 req/min" in phase_data[1]["label"]

    @pytest.mark.asyncio
    @patch("overload.engine.rate_limiter._PHASE_DURATION", 0.05)
    @patch("overload.engine.rate_limiter._COOLDOWN_SECONDS", 0)
    @patch("overload.engine.rate_limiter._fire_one", new_callable=AsyncMock)
    async def test_all_results_collected(self, mock_fire: AsyncMock) -> None:
        mock_fire.return_value = _result(200)
        cancel = asyncio.Event()
        cap = 3
        config = PatternConfig(rate_limit_cap=cap, concurrency=10)

        results, _ = await run_rate_limit_test(
            AsyncMock(), [_request()], VariableContext(), config,
            "run-8", cancel,
        )
        assert len(results) == cap + cap * 2


# ---------------------------------------------------------------------------
# run_rate_limit_test — progress callbacks
# ---------------------------------------------------------------------------

class TestRateLimitProgress:
    @pytest.mark.asyncio
    @patch("overload.engine.rate_limiter._PHASE_DURATION", 0.05)
    @patch("overload.engine.rate_limiter._COOLDOWN_SECONDS", 0)
    @patch("overload.engine.rate_limiter._fire_one", new_callable=AsyncMock)
    async def test_progress_reports_all_phases(self, mock_fire: AsyncMock) -> None:
        mock_fire.return_value = _result(200)
        cancel = asyncio.Event()
        config = PatternConfig(rate_limit_cap=3, concurrency=10)

        phases_seen: list[str] = []

        async def on_progress(p: RunProgress) -> None:
            phases_seen.append(p.phase)

        await run_rate_limit_test(
            AsyncMock(), [_request()], VariableContext(), config,
            "run-9", cancel, on_progress,
        )

        assert any("Phase 1" in p for p in phases_seen)
        assert any("Phase 2" in p for p in phases_seen)
        assert any(p == "complete" for p in phases_seen)

    @pytest.mark.asyncio
    @patch("overload.engine.rate_limiter._PHASE_DURATION", 0.05)
    @patch("overload.engine.rate_limiter._COOLDOWN_SECONDS", 1)
    @patch("overload.engine.rate_limiter._fire_one", new_callable=AsyncMock)
    async def test_progress_reports_cooldown(self, mock_fire: AsyncMock) -> None:
        mock_fire.return_value = _result(200)
        cancel = asyncio.Event()
        config = PatternConfig(rate_limit_cap=2, concurrency=10)

        phases_seen: list[str] = []

        async def on_progress(p: RunProgress) -> None:
            phases_seen.append(p.phase)

        await run_rate_limit_test(
            AsyncMock(), [_request()], VariableContext(), config,
            "run-10", cancel, on_progress,
        )

        assert any("Cooldown" in p for p in phases_seen)

    @pytest.mark.asyncio
    @patch("overload.engine.rate_limiter._PHASE_DURATION", 0.05)
    @patch("overload.engine.rate_limiter._COOLDOWN_SECONDS", 0)
    @patch("overload.engine.rate_limiter._fire_one", new_callable=AsyncMock)
    async def test_no_progress_when_callback_none(self, mock_fire: AsyncMock) -> None:
        mock_fire.return_value = _result(200)
        cancel = asyncio.Event()
        config = PatternConfig(rate_limit_cap=3, concurrency=10)

        results, phase_data = await run_rate_limit_test(
            AsyncMock(), [_request()], VariableContext(), config,
            "run-11", cancel, None,
        )
        assert len(results) > 0
        assert len(phase_data) == 3


# ---------------------------------------------------------------------------
# run_rate_limit_test — cancellation
# ---------------------------------------------------------------------------

class TestRateLimitCancellation:
    @pytest.mark.asyncio
    @patch("overload.engine.rate_limiter._PHASE_DURATION", 0.5)
    @patch("overload.engine.rate_limiter._COOLDOWN_SECONDS", 0)
    @patch("overload.engine.rate_limiter._fire_one", new_callable=AsyncMock)
    async def test_cancel_during_phase1_skips_phase2(self, mock_fire: AsyncMock) -> None:
        cancel = asyncio.Event()
        call_count = 0

        async def fire_then_cancel(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                cancel.set()
            return _result(200)

        mock_fire.side_effect = fire_then_cancel
        config = PatternConfig(rate_limit_cap=10, concurrency=10)

        _, phase_data = await run_rate_limit_test(
            AsyncMock(), [_request()], VariableContext(), config,
            "run-12", cancel,
        )

        exceed = next(r for r in phase_data if r["phase"] == "exceed")
        assert exceed["total"] == 0

    @pytest.mark.asyncio
    @patch("overload.engine.rate_limiter._PHASE_DURATION", 0.05)
    @patch("overload.engine.rate_limiter._COOLDOWN_SECONDS", 5)
    @patch("overload.engine.rate_limiter._fire_one", new_callable=AsyncMock)
    async def test_cancel_during_cooldown_skips_phase2(self, mock_fire: AsyncMock) -> None:
        mock_fire.return_value = _result(200)
        cancel = asyncio.Event()
        config = PatternConfig(rate_limit_cap=2, concurrency=10)

        async def cancel_after_delay():
            await asyncio.sleep(0.1)
            cancel.set()

        asyncio.create_task(cancel_after_delay())

        _, phase_data = await run_rate_limit_test(
            AsyncMock(), [_request()], VariableContext(), config,
            "run-13", cancel,
        )

        exceed = next(r for r in phase_data if r["phase"] == "exceed")
        assert exceed["total"] == 0

    @pytest.mark.asyncio
    @patch("overload.engine.rate_limiter._PHASE_DURATION", 0.05)
    @patch("overload.engine.rate_limiter._COOLDOWN_SECONDS", 0)
    @patch("overload.engine.rate_limiter._fire_one", new_callable=AsyncMock)
    async def test_pre_cancelled_runs_nothing(self, mock_fire: AsyncMock) -> None:
        cancel = asyncio.Event()
        cancel.set()
        config = PatternConfig(rate_limit_cap=5, concurrency=10)

        results, phase_data = await run_rate_limit_test(
            AsyncMock(), [_request()], VariableContext(), config,
            "run-14", cancel,
        )

        steady = next(r for r in phase_data if r["phase"] == "steady")
        exceed = next(r for r in phase_data if r["phase"] == "exceed")
        assert steady["total"] == 0
        assert exceed["total"] == 0


# ---------------------------------------------------------------------------
# _run_phase — live progress during execution
# ---------------------------------------------------------------------------

class TestRunPhaseLiveProgress:
    @pytest.mark.asyncio
    @patch("overload.engine.rate_limiter._PHASE_DURATION", 0.05)
    @patch("overload.engine.rate_limiter._fire_one", new_callable=AsyncMock)
    async def test_emits_progress_during_phase(self, mock_fire: AsyncMock) -> None:
        """Progress callback must be called at least once per request during the phase."""
        mock_fire.return_value = _result(200)
        sem = asyncio.Semaphore(10)
        cancel = asyncio.Event()
        progress_calls: list[RunProgress] = []

        async def on_progress(p: RunProgress) -> None:
            progress_calls.append(p)

        await _run_phase(
            AsyncMock(), [_request()], VariableContext(), sem, 5, cancel, 0,
            on_progress, "run-live-1", "Phase 1", [], 5, time.monotonic(),
        )

        assert len(progress_calls) >= 1

    @pytest.mark.asyncio
    @patch("overload.engine.rate_limiter._PHASE_DURATION", 0.05)
    @patch("overload.engine.rate_limiter._fire_one", new_callable=AsyncMock)
    async def test_total_requests_unchanged_across_calls(self, mock_fire: AsyncMock) -> None:
        """total_requests in progress must match the value passed in, not reset."""
        mock_fire.return_value = _result(200)
        sem = asyncio.Semaphore(10)
        cancel = asyncio.Event()
        totals_seen: list[int] = []

        async def on_progress(p: RunProgress) -> None:
            totals_seen.append(p.total_requests)

        await _run_phase(
            AsyncMock(), [_request()], VariableContext(), sem, 4, cancel, 0,
            on_progress, "run-live-2", "Phase 1", [], 12, time.monotonic(),
        )

        assert all(t == 12 for t in totals_seen)

    @pytest.mark.asyncio
    @patch("overload.engine.rate_limiter._PHASE_DURATION", 0.05)
    @patch("overload.engine.rate_limiter._fire_one", new_callable=AsyncMock)
    async def test_progress_includes_prior_results(self, mock_fire: AsyncMock) -> None:
        """completed_requests must include prior_results, not just current phase."""
        mock_fire.return_value = _result(200)
        sem = asyncio.Semaphore(10)
        cancel = asyncio.Event()
        prior = [_result(200), _result(200), _result(200)]
        completed_seen: list[int] = []

        async def on_progress(p: RunProgress) -> None:
            completed_seen.append(p.completed_requests)

        await _run_phase(
            AsyncMock(), [_request()], VariableContext(), sem, 3, cancel, 0,
            on_progress, "run-live-3", "Phase 1", prior, 6, time.monotonic(),
        )

        assert all(c >= len(prior) for c in completed_seen)

    @pytest.mark.asyncio
    @patch("overload.engine.rate_limiter._PHASE_DURATION", 0.05)
    @patch("overload.engine.rate_limiter._fire_one", new_callable=AsyncMock)
    async def test_progress_phase_label_contains_sent_count(self, mock_fire: AsyncMock) -> None:
        """Phase label must include how many requests have been sent."""
        mock_fire.return_value = _result(200)
        sem = asyncio.Semaphore(10)
        cancel = asyncio.Event()
        phase_labels: list[str] = []

        async def on_progress(p: RunProgress) -> None:
            phase_labels.append(p.phase)

        await _run_phase(
            AsyncMock(), [_request()], VariableContext(), sem, 4, cancel, 0,
            on_progress, "run-live-4", "My Phase", [], 4, time.monotonic(),
        )

        assert any("sent" in label for label in phase_labels)

    @pytest.mark.asyncio
    @patch("overload.engine.rate_limiter._PHASE_DURATION", 0.05)
    @patch("overload.engine.rate_limiter._fire_one", new_callable=AsyncMock)
    async def test_no_error_when_callback_is_none(self, mock_fire: AsyncMock) -> None:
        """_run_phase must not raise when on_progress is None."""
        mock_fire.return_value = _result(200)
        sem = asyncio.Semaphore(10)
        cancel = asyncio.Event()

        results, _ = await _run_phase(
            AsyncMock(), [_request()], VariableContext(), sem, 3, cancel, 0,
            None, "run-live-5", "Phase 1", [], 3, time.monotonic(),
        )
        assert len(results) == 3


# ---------------------------------------------------------------------------
# run_rate_limit_test — cumulative total_requests across phases
# ---------------------------------------------------------------------------

class TestRateLimitCumulativeTotal:
    @pytest.mark.asyncio
    @patch("overload.engine.rate_limiter._PHASE_DURATION", 0.05)
    @patch("overload.engine.rate_limiter._COOLDOWN_SECONDS", 0)
    @patch("overload.engine.rate_limiter._fire_one", new_callable=AsyncMock)
    async def test_total_requests_is_cumulative(self, mock_fire: AsyncMock) -> None:
        """total_requests in every progress message must equal cap + 2*cap, not reset per phase."""
        mock_fire.return_value = _result(200)
        cancel = asyncio.Event()
        cap = 4
        config = PatternConfig(rate_limit_cap=cap, concurrency=10)
        totals: list[int] = []

        async def on_progress(p: RunProgress) -> None:
            totals.append(p.total_requests)

        await run_rate_limit_test(
            AsyncMock(), [_request()], VariableContext(), config,
            "run-cum-1", cancel, on_progress,
        )

        expected_total = cap + cap * 2
        assert all(t == expected_total for t in totals), (
            f"total_requests should always be {expected_total}, got: {set(totals)}"
        )

    @pytest.mark.asyncio
    @patch("overload.engine.rate_limiter._PHASE_DURATION", 0.05)
    @patch("overload.engine.rate_limiter._COOLDOWN_SECONDS", 0)
    @patch("overload.engine.rate_limiter._fire_one", new_callable=AsyncMock)
    async def test_status_codes_tracked_in_progress(self, mock_fire: AsyncMock) -> None:
        """Progress messages during Phase 2 must include status codes from both phases."""
        call_count = 0
        cap = 3

        async def mixed_statuses(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return _result(429 if call_count > cap else 200)

        mock_fire.side_effect = mixed_statuses
        cancel = asyncio.Event()
        config = PatternConfig(rate_limit_cap=cap, concurrency=10)
        final_status_codes: dict[int, int] = {}

        async def on_progress(p: RunProgress) -> None:
            if p.phase == "complete":
                final_status_codes.update(p.status_codes)

        await run_rate_limit_test(
            AsyncMock(), [_request()], VariableContext(), config,
            "run-cum-2", cancel, on_progress,
        )

        assert 200 in final_status_codes
        assert 429 in final_status_codes
