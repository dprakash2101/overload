from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum


class TestType(str, Enum):
    LOAD = "load"
    STRESS = "stress"
    SPIKE = "spike"
    SOAK = "soak"
    RAMP = "ramp"
    BURST = "burst"
    BREAKPOINT = "breakpoint"
    CUSTOM = "custom"
    RATE_LIMIT = "ratelimit"
    SEQUENTIAL = "sequential"


class RequestDistribution(str, Enum):
    ROUND_ROBIN = "round-robin"
    RANDOM = "random"


@dataclass
class RequestResult:
    request_name: str
    method: str
    url: str
    status_code: int
    latency_ms: float
    timestamp: float
    error: str | None = None
    headers_sent: dict[str, str] = field(default_factory=dict)
    headers_received: dict[str, str] = field(default_factory=dict)
    body_size_bytes: int = 0
    response_body: str | None = None


@dataclass
class RunProgress:
    run_id: str
    total_requests: int
    completed_requests: int
    current_rps: float
    phase: str
    elapsed_seconds: float
    error_count: int = 0
    status_codes: dict[int, int] = field(default_factory=dict)
    avg_latency_ms: float = 0.0
    recent_results: list[dict] = field(default_factory=list)


@dataclass
class PatternConfig:
    concurrency: int = 20
    timeout_seconds: float = 30.0
    verify_ssl: bool = True
    follow_redirects: bool = True
    save_responses: bool = False
    distribution: RequestDistribution = RequestDistribution.ROUND_ROBIN
    think_time_ms: int = 0

    # Load test
    target_rps: int = 50
    ramp_up_seconds: int = 30
    hold_duration_seconds: int = 300
    ramp_down_seconds: int = 10

    # Stress test
    start_rps: int = 10
    step_rps: int = 20
    step_duration_seconds: int = 30
    failure_threshold_pct: float = 80.0
    max_rps: int = 500

    # Spike test
    baseline_rps: int = 20
    spike_rps: int = 200
    baseline_duration_seconds: int = 60
    spike_duration_seconds: int = 30
    recovery_duration_seconds: int = 60

    # Soak test
    soak_rps: int = 30
    soak_duration_seconds: int = 1800

    # Ramp test
    ramp_start_rps: int = 10
    ramp_end_rps: int = 200

    # Burst test
    total_requests: int = 200

    # Breakpoint test
    precision_rps: int = 5
    latency_threshold_ms: float = 2000.0
    error_threshold_pct: float = 10.0

    # Custom test
    stages: list[dict] = field(default_factory=list)

    # Rate limit test
    rate_limit_cap: int = 60
    rate_limit_requests: int = 120

    # Sequential runner
    iterations: int = 1
    delay_ms: int = 0


@dataclass
class Threshold:
    metric: str
    operator: str
    value: float


@dataclass
class AssertionResult:
    metric: str
    operator: str
    expected: float
    actual: float
    passed: bool


@dataclass
class Verdict:
    passed: bool
    results: list[AssertionResult]


class Stats:
    def __init__(self) -> None:
        self.results: list[RequestResult] = []

    def add(self, result: RequestResult) -> None:
        self.results.append(result)

    def add_all(self, results: list[RequestResult]) -> None:
        self.results.extend(results)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def success_count(self) -> int:
        return sum(1 for r in self.results if 200 <= r.status_code < 400)

    @property
    def error_count(self) -> int:
        return sum(
            1
            for r in self.results
            if r.status_code < 200 or r.status_code >= 400
        )

    @property
    def rate_limited_count(self) -> int:
        return sum(1 for r in self.results if r.status_code == 429)

    def compute(self) -> dict | None:
        if not self.results:
            return None

        status_counts: dict[int, int] = defaultdict(int)
        for r in self.results:
            status_counts[r.status_code] += 1

        latencies = [r.latency_ms for r in self.results]
        sorted_latencies = sorted(latencies)

        ok = sum(v for k, v in status_counts.items() if 200 <= k < 400)
        rl = status_counts.get(429, 0)
        total = len(self.results)

        t0 = self.results[0].timestamp
        buckets: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))
        for r in self.results:
            buckets[int(r.timestamp - t0)][r.status_code] += 1

        per_second = []
        for sec in sorted(buckets):
            b = buckets[sec]
            sec_total = sum(b.values())
            sec_ok = sum(v for k, v in b.items() if 200 <= k < 300)
            sec_redirect = sum(v for k, v in b.items() if 300 <= k < 400)
            sec_rl = b.get(429, 0)
            sec_client = sum(v for k, v in b.items() if 400 <= k < 500 and k != 429)
            sec_server = sum(v for k, v in b.items() if k >= 500)
            sec_conn = sum(v for k, v in b.items() if k <= 0)
            per_second.append({
                "second": sec,
                "total": sec_total,
                "ok": sec_ok + sec_redirect,
                "rate_limited": sec_rl,
                "client_errors": sec_client,
                "server_errors": sec_server,
                "conn_errors": sec_conn,
                "errors": sec_total - sec_ok - sec_redirect - sec_rl,
            })

        timeline = [
            {
                "timestamp": round(r.timestamp - t0, 3),
                "status": r.status_code,
                "latency_ms": round(r.latency_ms, 1),
                "request_name": r.request_name,
            }
            for r in self.results
        ]

        request_log = []
        for r in self.results:
            entry = {
                "timestamp": round(r.timestamp - t0, 3),
                "status": r.status_code,
                "latency_ms": round(r.latency_ms, 1),
                "method": r.method,
                "url": r.url,
                "request_name": r.request_name,
                "error": r.error,
            }
            if r.response_body is not None:
                entry["response_body"] = r.response_body
            request_log.append(entry)

        p95_idx = int(len(sorted_latencies) * 0.95)
        p99_idx = int(len(sorted_latencies) * 0.99)

        return {
            "total": total,
            "ok": ok,
            "rate_limited": rl,
            "errors": total - ok - rl,
            "status_codes": dict(status_counts),
            "latency": {
                "min": round(min(latencies), 1),
                "median": round(statistics.median(latencies), 1),
                "mean": round(statistics.mean(latencies), 1),
                "p95": round(sorted_latencies[min(p95_idx, total - 1)], 1),
                "p99": round(sorted_latencies[min(p99_idx, total - 1)], 1),
                "max": round(max(latencies), 1),
            },
            "per_second": per_second,
            "timeline": timeline,
            "request_log": request_log,
            "duration_seconds": round(max(self.results[-1].timestamp - t0, 0.1), 1) if total > 1 else 0.1,
            "avg_rps": round(total / max(self.results[-1].timestamp - t0, 0.1), 1),
        }
