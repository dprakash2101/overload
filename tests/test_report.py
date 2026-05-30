from __future__ import annotations

import os
import time

from overload.engine.models import RequestResult, Stats
from overload.report.exporters import export_csv, export_json
from overload.report.generator import generate_report


def _make_stats(count: int = 10) -> Stats:
    s = Stats()
    t0 = 1000000.0
    for i in range(count):
        s.add(RequestResult(
            request_name=f"req_{i}",
            method="GET",
            url="https://api.com",
            status_code=200,
            latency_ms=50.0 + i * 10,
            timestamp=t0 + i * 0.1,
        ))
    return s


class TestGenerateReport:
    def test_generates_html_file(self, tmp_path) -> None:
        stats = _make_stats()
        path = generate_report(
            stats, "burst", {"concurrency": 20},
            run_id="test_run_123", output_dir=str(tmp_path),
        )
        assert path.endswith(".html")
        assert os.path.isfile(path)
        content = open(path).read()
        assert "Overload Report" in content
        assert "test_run_123" in content

    def test_empty_stats_returns_empty(self, tmp_path) -> None:
        stats = Stats()
        path = generate_report(
            stats, "burst", {}, output_dir=str(tmp_path),
        )
        assert path == ""

    def test_report_with_verdict(self, tmp_path) -> None:
        stats = _make_stats()
        verdict_data = {
            "passed": True,
            "results": [
                {"metric": "p95_latency_ms", "operator": "<", "expected": 500.0, "actual": 300.0, "passed": True},
            ],
        }
        path = generate_report(
            stats, "load", {"concurrency": 10},
            run_id="verdict_run", output_dir=str(tmp_path),
            verdict=verdict_data,
        )
        content = open(path).read()
        assert "verdict" in content

    def test_creates_output_dir(self, tmp_path) -> None:
        out = str(tmp_path / "subdir" / "reports")
        stats = _make_stats()
        path = generate_report(stats, "burst", {}, output_dir=out)
        assert os.path.isfile(path)
        assert out in path


class TestExportJson:
    def test_exports_json(self, tmp_path) -> None:
        stats = _make_stats()
        path = export_json(stats, "burst", "run_123", str(tmp_path))
        assert path.endswith(".json")
        assert os.path.isfile(path)

        import json
        data = json.load(open(path))
        assert data["meta"]["run_id"] == "run_123"
        assert data["stats"]["total"] == 10

    def test_empty_stats(self, tmp_path) -> None:
        stats = Stats()
        path = export_json(stats, "burst", "empty", str(tmp_path))
        assert path == ""


class TestExportCsv:
    def test_exports_csv(self, tmp_path) -> None:
        stats = _make_stats()
        path = export_csv(stats, "run_123", str(tmp_path))
        assert path.endswith(".csv")
        assert os.path.isfile(path)

        import csv
        with open(path) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 10
        assert rows[0]["method"] == "GET"

    def test_empty_stats(self, tmp_path) -> None:
        stats = Stats()
        path = export_csv(stats, "empty", str(tmp_path))
        assert path == ""
