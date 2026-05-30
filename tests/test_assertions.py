from __future__ import annotations

import math
import os
import xml.etree.ElementTree as ET

from overload.engine.assertions import evaluate, parse_threshold, print_verdict, write_junit_xml
from overload.engine.models import Threshold, Verdict


def _make_stats(
    total: int = 100,
    ok: int = 95,
    errors: int = 5,
    rate_limited: int = 0,
    avg_rps: float = 50.0,
    p95: float = 300.0,
    p99: float = 450.0,
    median: float = 150.0,
    mean: float = 180.0,
    max_lat: float = 600.0,
) -> dict:
    return {
        "total": total,
        "ok": ok,
        "errors": errors,
        "rate_limited": rate_limited,
        "avg_rps": avg_rps,
        "latency": {
            "median": median,
            "mean": mean,
            "p95": p95,
            "p99": p99,
            "max": max_lat,
        },
    }


class TestEvaluatePassCases:
    def test_single_threshold_passes(self) -> None:
        stats = _make_stats(p95=300.0)
        thresholds = [Threshold("p95_latency_ms", "<", 500.0)]
        verdict = evaluate(stats, thresholds)
        assert verdict.passed is True
        assert len(verdict.results) == 1
        assert verdict.results[0].actual == 300.0
        assert verdict.results[0].passed is True

    def test_multiple_thresholds_all_pass(self) -> None:
        stats = _make_stats(p95=200.0, ok=98, errors=2, total=100)
        thresholds = [
            Threshold("p95_latency_ms", "<", 500.0),
            Threshold("error_rate_pct", "<", 5.0),
            Threshold("avg_rps", ">", 10.0),
        ]
        verdict = evaluate(stats, thresholds)
        assert verdict.passed is True
        assert all(r.passed for r in verdict.results)

    def test_empty_thresholds_passes(self) -> None:
        stats = _make_stats()
        verdict = evaluate(stats, [])
        assert verdict.passed is True
        assert verdict.results == []


class TestEvaluateFailCases:
    def test_single_threshold_fails(self) -> None:
        stats = _make_stats(p95=700.0)
        thresholds = [Threshold("p95_latency_ms", "<", 500.0)]
        verdict = evaluate(stats, thresholds)
        assert verdict.passed is False
        assert verdict.results[0].actual == 700.0
        assert verdict.results[0].passed is False

    def test_one_fail_makes_verdict_fail(self) -> None:
        stats = _make_stats(p95=200.0, ok=80, errors=20, total=100)
        thresholds = [
            Threshold("p95_latency_ms", "<", 500.0),
            Threshold("error_rate_pct", "<", 5.0),
        ]
        verdict = evaluate(stats, thresholds)
        assert verdict.passed is False
        assert verdict.results[0].passed is True
        assert verdict.results[1].passed is False
        assert verdict.results[1].actual == 20.0


class TestEvaluateMissingMetric:
    def test_unknown_metric_fails(self) -> None:
        stats = _make_stats()
        thresholds = [Threshold("nonexistent_metric", "<", 100.0)]
        verdict = evaluate(stats, thresholds)
        assert verdict.passed is False
        assert math.isnan(verdict.results[0].actual)

    def test_missing_latency_key_fails(self) -> None:
        stats: dict = {"total": 100, "ok": 95, "errors": 5}
        thresholds = [Threshold("p95_latency_ms", "<", 500.0)]
        verdict = evaluate(stats, thresholds)
        assert verdict.passed is False
        assert math.isnan(verdict.results[0].actual)


class TestEvaluateOperators:
    def test_less_than(self) -> None:
        stats = _make_stats(p95=300.0)
        assert evaluate(stats, [Threshold("p95_latency_ms", "<", 500.0)]).passed is True
        assert evaluate(stats, [Threshold("p95_latency_ms", "<", 300.0)]).passed is False
        assert evaluate(stats, [Threshold("p95_latency_ms", "<", 200.0)]).passed is False

    def test_less_than_or_equal(self) -> None:
        stats = _make_stats(p95=300.0)
        assert evaluate(stats, [Threshold("p95_latency_ms", "<=", 300.0)]).passed is True
        assert evaluate(stats, [Threshold("p95_latency_ms", "<=", 299.0)]).passed is False

    def test_greater_than(self) -> None:
        stats = _make_stats(avg_rps=50.0)
        assert evaluate(stats, [Threshold("avg_rps", ">", 10.0)]).passed is True
        assert evaluate(stats, [Threshold("avg_rps", ">", 50.0)]).passed is False

    def test_greater_than_or_equal(self) -> None:
        stats = _make_stats(avg_rps=50.0)
        assert evaluate(stats, [Threshold("avg_rps", ">=", 50.0)]).passed is True
        assert evaluate(stats, [Threshold("avg_rps", ">=", 51.0)]).passed is False

    def test_equal(self) -> None:
        stats = _make_stats(total=100)
        assert evaluate(stats, [Threshold("total_requests", "==", 100.0)]).passed is True
        assert evaluate(stats, [Threshold("total_requests", "==", 99.0)]).passed is False


class TestEvaluateComputedMetrics:
    def test_error_rate_pct(self) -> None:
        stats = _make_stats(total=200, ok=190, errors=10)
        verdict = evaluate(stats, [Threshold("error_rate_pct", "<", 10.0)])
        assert verdict.passed is True
        assert verdict.results[0].actual == 5.0

    def test_success_rate_pct(self) -> None:
        stats = _make_stats(total=200, ok=190, errors=10)
        verdict = evaluate(stats, [Threshold("success_rate_pct", ">=", 90.0)])
        assert verdict.passed is True
        assert verdict.results[0].actual == 95.0

    def test_rate_limited_count(self) -> None:
        stats = _make_stats(rate_limited=15)
        verdict = evaluate(stats, [Threshold("rate_limited_count", "<", 20.0)])
        assert verdict.passed is True
        assert verdict.results[0].actual == 15.0

    def test_zero_total_requests(self) -> None:
        stats = _make_stats(total=0, ok=0, errors=0)
        verdict = evaluate(stats, [Threshold("error_rate_pct", "<", 5.0)])
        assert verdict.passed is True
        assert verdict.results[0].actual == 0.0


class TestParseThreshold:
    def test_less_than(self) -> None:
        t = parse_threshold("p95_latency_ms<500")
        assert t.metric == "p95_latency_ms"
        assert t.operator == "<"
        assert t.value == 500.0

    def test_less_than_or_equal(self) -> None:
        t = parse_threshold("error_rate_pct<=5.0")
        assert t.metric == "error_rate_pct"
        assert t.operator == "<="
        assert t.value == 5.0

    def test_greater_than(self) -> None:
        t = parse_threshold("avg_rps>100")
        assert t.metric == "avg_rps"
        assert t.operator == ">"
        assert t.value == 100.0

    def test_greater_than_or_equal(self) -> None:
        t = parse_threshold("success_rate_pct>=99.5")
        assert t.metric == "success_rate_pct"
        assert t.operator == ">="
        assert t.value == 99.5

    def test_equal(self) -> None:
        t = parse_threshold("total_requests==1000")
        assert t.metric == "total_requests"
        assert t.operator == "=="
        assert t.value == 1000.0

    def test_with_spaces(self) -> None:
        t = parse_threshold("  p95_latency_ms < 500  ")
        assert t.metric == "p95_latency_ms"
        assert t.operator == "<"
        assert t.value == 500.0

    def test_invalid_raises(self) -> None:
        import pytest
        with pytest.raises(ValueError, match="Invalid threshold expression"):
            parse_threshold("p95_latency_ms 500")


class TestPrintVerdict:
    def test_pass_output(self, capsys) -> None:
        stats = _make_stats(p95=300.0)
        verdict = evaluate(stats, [Threshold("p95_latency_ms", "<", 500.0)])
        print_verdict(verdict)
        out = capsys.readouterr().out
        assert "p95_latency_ms" in out
        assert "300.0ms" in out
        assert "PASS" in out

    def test_fail_output(self, capsys) -> None:
        stats = _make_stats(p95=700.0)
        verdict = evaluate(stats, [Threshold("p95_latency_ms", "<", 500.0)])
        print_verdict(verdict)
        out = capsys.readouterr().out
        assert "700.0ms" in out
        assert "FAIL" in out


class TestJunitXml:
    def test_writes_valid_xml(self, tmp_path) -> None:
        stats = _make_stats(p95=300.0, ok=95, errors=5, total=100)
        verdict = evaluate(stats, [
            Threshold("p95_latency_ms", "<", 500.0),
            Threshold("error_rate_pct", "<", 1.0),
        ])
        path = str(tmp_path / "report.xml")
        write_junit_xml(verdict, path)

        tree = ET.parse(path)
        suite = tree.getroot()
        assert suite.tag == "testsuite"
        assert suite.attrib["tests"] == "2"
        assert suite.attrib["failures"] == "1"

        cases = suite.findall("testcase")
        assert len(cases) == 2
        assert cases[0].find("failure") is None
        assert cases[1].find("failure") is not None

    def test_all_pass_no_failures(self, tmp_path) -> None:
        stats = _make_stats(p95=200.0)
        verdict = evaluate(stats, [Threshold("p95_latency_ms", "<", 500.0)])
        path = str(tmp_path / "report.xml")
        write_junit_xml(verdict, path)

        tree = ET.parse(path)
        suite = tree.getroot()
        assert suite.attrib["failures"] == "0"
        assert suite.findall(".//failure") == []
