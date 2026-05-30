from __future__ import annotations

import time

from overload.engine.models import (
    PatternConfig,
    RequestResult,
    Stats,
    TestType,
    Threshold,
    Verdict,
)


class TestRequestResult:
    def test_defaults(self) -> None:
        r = RequestResult(
            request_name="test",
            method="GET",
            url="https://api.com",
            status_code=200,
            latency_ms=100.0,
            timestamp=time.time(),
        )
        assert r.error is None
        assert r.body_size_bytes == 0
        assert r.headers_sent == {}

    def test_with_error(self) -> None:
        r = RequestResult(
            request_name="fail",
            method="POST",
            url="https://api.com",
            status_code=0,
            latency_ms=5000.0,
            timestamp=time.time(),
            error="timeout",
        )
        assert r.error == "timeout"
        assert r.status_code == 0


class TestStats:
    def _make_results(self, count: int = 10, status: int = 200) -> list[RequestResult]:
        t0 = 1000000.0
        return [
            RequestResult(
                request_name=f"req_{i}",
                method="GET",
                url="https://api.com",
                status_code=status,
                latency_ms=50.0 + i * 10,
                timestamp=t0 + i * 0.1,
            )
            for i in range(count)
        ]

    def test_empty_stats(self) -> None:
        s = Stats()
        assert s.total == 0
        assert s.compute() is None

    def test_add_results(self) -> None:
        s = Stats()
        results = self._make_results(5)
        s.add_all(results)
        assert s.total == 5
        assert s.success_count == 5
        assert s.error_count == 0

    def test_add_single(self) -> None:
        s = Stats()
        s.add(self._make_results(1)[0])
        assert s.total == 1

    def test_error_count(self) -> None:
        s = Stats()
        s.add_all(self._make_results(3, status=200))
        s.add_all(self._make_results(2, status=500))
        assert s.success_count == 3
        assert s.error_count == 2

    def test_rate_limited_count(self) -> None:
        s = Stats()
        s.add_all(self._make_results(3, status=200))
        s.add_all(self._make_results(2, status=429))
        assert s.rate_limited_count == 2

    def test_compute_structure(self) -> None:
        s = Stats()
        s.add_all(self._make_results(10))
        computed = s.compute()
        assert computed is not None
        assert "total" in computed
        assert "ok" in computed
        assert "errors" in computed
        assert "latency" in computed
        assert "per_second" in computed
        assert "timeline" in computed
        assert "request_log" in computed
        assert "duration_seconds" in computed
        assert "avg_rps" in computed

    def test_compute_latency_percentiles(self) -> None:
        s = Stats()
        s.add_all(self._make_results(100))
        computed = s.compute()
        lat = computed["latency"]
        assert lat["min"] <= lat["median"] <= lat["p95"] <= lat["p99"] <= lat["max"]

    def test_compute_status_codes(self) -> None:
        s = Stats()
        s.add_all(self._make_results(3, status=200))
        s.add_all(self._make_results(2, status=404))
        computed = s.compute()
        assert computed["status_codes"][200] == 3
        assert computed["status_codes"][404] == 2


class TestPatternConfig:
    def test_defaults(self) -> None:
        c = PatternConfig()
        assert c.concurrency == 20
        assert c.timeout_seconds == 30.0
        assert c.target_rps == 50
        assert c.total_requests == 200

    def test_custom_values(self) -> None:
        c = PatternConfig(concurrency=50, target_rps=200)
        assert c.concurrency == 50
        assert c.target_rps == 200


class TestTestType:
    def test_all_types(self) -> None:
        types = [t.value for t in TestType]
        assert "load" in types
        assert "burst" in types
        assert "sequential" in types
        assert len(types) == 10


class TestThresholdVerdict:
    def test_threshold_creation(self) -> None:
        t = Threshold(metric="p95_latency_ms", operator="<", value=500.0)
        assert t.metric == "p95_latency_ms"
        assert t.value == 500.0

    def test_verdict_all_pass(self) -> None:
        from overload.engine.models import AssertionResult
        results = [AssertionResult("p95", "<", 500.0, 300.0, True)]
        v = Verdict(passed=True, results=results)
        assert v.passed is True

    def test_verdict_has_failure(self) -> None:
        from overload.engine.models import AssertionResult
        results = [
            AssertionResult("p95", "<", 500.0, 300.0, True),
            AssertionResult("errors", "<", 1.0, 5.0, False),
        ]
        v = Verdict(passed=False, results=results)
        assert v.passed is False
