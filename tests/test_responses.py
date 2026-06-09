from __future__ import annotations

import json
import os

from overload.engine.models import RequestResult, Stats
from overload.report.responses import write_responses_json


def _stats_with_bodies(bodies: list[str | None]) -> Stats:
    s = Stats()
    for i, body in enumerate(bodies):
        s.add(RequestResult(
            request_name=f"req_{i}",
            method="GET",
            url=f"https://api.com/{i}",
            status_code=200,
            latency_ms=10.0 + i,
            timestamp=1000.0 + i * 0.1,
            response_body=body,
        ))
    return s


class TestWriteResponsesJson:
    def test_writes_only_captured_bodies(self, tmp_path) -> None:
        stats = _stats_with_bodies(['{"a":1}', None, '{"b":2}'])
        path = write_responses_json(str(tmp_path), stats, "run_x")
        assert path.endswith("responses.json")
        assert os.path.isfile(path)

        data = json.load(open(path))
        assert data["run_id"] == "run_x"
        assert data["count"] == 2
        urls = [e["url"] for e in data["responses"]]
        assert "https://api.com/0" in urls
        assert "https://api.com/2" in urls
        assert "https://api.com/1" not in urls
        assert data["responses"][0]["response_body"] == '{"a":1}'

    def test_no_bodies_writes_nothing(self, tmp_path) -> None:
        stats = _stats_with_bodies([None, None])
        path = write_responses_json(str(tmp_path), stats, "run_y")
        assert path == ""
        assert not os.path.exists(os.path.join(str(tmp_path), "responses.json"))

    def test_empty_stats(self, tmp_path) -> None:
        path = write_responses_json(str(tmp_path), Stats(), "run_z")
        assert path == ""
