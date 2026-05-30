from __future__ import annotations

import logging
import operator as op
import xml.etree.ElementTree as ET
from typing import Callable

from overload.engine.models import AssertionResult, Threshold, Verdict

logger = logging.getLogger(__name__)

_OPERATORS: dict[str, Callable[[float, float], bool]] = {
    "<": op.lt,
    "<=": op.le,
    ">": op.gt,
    ">=": op.ge,
    "==": op.eq,
}

_METRIC_EXTRACTORS: dict[str, Callable[[dict], float | None]] = {
    "p50_latency_ms": lambda s: s.get("latency", {}).get("median"),
    "p95_latency_ms": lambda s: s.get("latency", {}).get("p95"),
    "p99_latency_ms": lambda s: s.get("latency", {}).get("p99"),
    "max_latency_ms": lambda s: s.get("latency", {}).get("max"),
    "mean_latency_ms": lambda s: s.get("latency", {}).get("mean"),
    "error_rate_pct": lambda s: (
        (s["errors"] / s["total"]) * 100 if s.get("total", 0) > 0 else 0.0
    ),
    "success_rate_pct": lambda s: (
        (s["ok"] / s["total"]) * 100 if s.get("total", 0) > 0 else 0.0
    ),
    "avg_rps": lambda s: s.get("avg_rps"),
    "total_requests": lambda s: float(s["total"]) if "total" in s else None,
    "rate_limited_count": lambda s: float(s.get("rate_limited", 0)),
}


def evaluate(computed: dict, thresholds: list[Threshold]) -> Verdict:
    results: list[AssertionResult] = []

    for threshold in thresholds:
        extractor = _METRIC_EXTRACTORS.get(threshold.metric)
        if extractor is None:
            logger.warning("Unknown metric: %s — skipping assertion", threshold.metric)
            results.append(AssertionResult(
                metric=threshold.metric,
                operator=threshold.operator,
                expected=threshold.value,
                actual=float("nan"),
                passed=False,
            ))
            continue

        actual = extractor(computed)
        if actual is None:
            logger.warning("Metric %s not available in stats", threshold.metric)
            results.append(AssertionResult(
                metric=threshold.metric,
                operator=threshold.operator,
                expected=threshold.value,
                actual=float("nan"),
                passed=False,
            ))
            continue

        comparator = _OPERATORS.get(threshold.operator)
        if comparator is None:
            logger.error("Invalid operator: %s", threshold.operator)
            results.append(AssertionResult(
                metric=threshold.metric,
                operator=threshold.operator,
                expected=threshold.value,
                actual=actual,
                passed=False,
            ))
            continue

        passed = comparator(actual, threshold.value)
        results.append(AssertionResult(
            metric=threshold.metric,
            operator=threshold.operator,
            expected=threshold.value,
            actual=actual,
            passed=passed,
        ))

    return Verdict(
        passed=all(r.passed for r in results),
        results=results,
    )


def parse_threshold(expr: str) -> Threshold:
    for symbol in ("<=", ">=", "==", "<", ">"):
        if symbol in expr:
            metric, value_str = expr.split(symbol, 1)
            return Threshold(
                metric=metric.strip(),
                operator=symbol,
                value=float(value_str.strip()),
            )
    raise ValueError(f"Invalid threshold expression: {expr!r}")


def _format_value(metric: str, value: float) -> str:
    if "latency" in metric:
        return f"{value:.1f}ms"
    if "pct" in metric:
        return f"{value:.1f}%"
    if "rps" in metric:
        return f"{value:.1f}/s"
    if value == int(value):
        return str(int(value))
    return f"{value:.1f}"


def print_verdict(verdict: Verdict) -> None:
    print("\n  Assertions:")
    for r in verdict.results:
        mark = "\033[32m✓\033[0m" if r.passed else "\033[31m✗\033[0m"
        actual_str = _format_value(r.metric, r.actual)
        expected_str = _format_value(r.metric, r.expected)
        print(f"    {mark} {r.metric}  {actual_str} {r.operator} {expected_str}")

    label = "\033[32mPASS\033[0m" if verdict.passed else "\033[31mFAIL\033[0m"
    print(f"\n  Verdict: {label}")


def write_junit_xml(verdict: Verdict, path: str, test_name: str = "overload") -> None:
    suite = ET.Element("testsuite", {
        "name": test_name,
        "tests": str(len(verdict.results)),
        "failures": str(sum(1 for r in verdict.results if not r.passed)),
    })

    for r in verdict.results:
        case = ET.SubElement(suite, "testcase", {
            "name": f"{r.metric} {r.operator} {_format_value(r.metric, r.expected)}",
            "classname": "overload.assertions",
        })
        if not r.passed:
            failure = ET.SubElement(case, "failure", {
                "message": (
                    f"{r.metric}: expected {r.operator} {_format_value(r.metric, r.expected)}, "
                    f"got {_format_value(r.metric, r.actual)}"
                ),
            })

    tree = ET.ElementTree(suite)
    ET.indent(tree)
    tree.write(path, encoding="unicode", xml_declaration=True)
