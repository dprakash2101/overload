from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from overload.engine.models import RequestResult
from overload.web.app import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(working_dir=str(tmp_path))
    return TestClient(app)


@pytest.fixture
def client_with_collection(tmp_path):
    collection = {
        "info": {
            "name": "Test API",
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "item": [
            {
                "name": "Health Check",
                "request": {
                    "method": "GET",
                    "url": "https://httpbin.org/get",
                },
            }
        ],
    }
    coll_path = tmp_path / "test.json"
    coll_path.write_text(json.dumps(collection))

    app = create_app(working_dir=str(tmp_path))
    tc = TestClient(app)
    tc.post("/api/collection/load-local", json={"path": str(coll_path)})
    return tc


class TestDetectFiles:
    def test_detect_empty_dir(self, client) -> None:
        resp = client.get("/api/detect")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["collections"] == []

    def test_detect_collection(self, tmp_path) -> None:
        collection = {
            "info": {"name": "My API", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
            "item": [{"name": "Req", "request": {"method": "GET", "url": "https://a.com"}}],
        }
        (tmp_path / "api.json").write_text(json.dumps(collection))
        app = create_app(working_dir=str(tmp_path))
        tc = TestClient(app)
        resp = tc.get("/api/detect")
        assert len(resp.json()["collections"]) == 1
        assert resp.json()["collections"][0]["name"] == "My API"


class TestCollectionLoading:
    def test_load_local_collection(self, tmp_path) -> None:
        collection = {
            "info": {"name": "Local", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
            "item": [{"name": "R1", "request": {"method": "GET", "url": "https://a.com"}}],
        }
        path = tmp_path / "coll.json"
        path.write_text(json.dumps(collection))

        app = create_app(working_dir=str(tmp_path))
        tc = TestClient(app)
        resp = tc.post("/api/collection/load-local", json={"path": str(path)})
        assert resp.status_code == 200
        assert resp.json()["collection"]["name"] == "Local"

    def test_load_missing_file(self, client) -> None:
        resp = client.post("/api/collection/load-local", json={"path": "/nonexistent.json"})
        assert resp.status_code == 400

    def test_upload_collection(self, tmp_path) -> None:
        collection = {
            "info": {"name": "Upload", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
            "item": [],
        }
        app = create_app(working_dir=str(tmp_path))
        tc = TestClient(app)
        resp = tc.post("/api/collection/upload", files={"file": ("coll.json", json.dumps(collection), "application/json")})
        assert resp.status_code == 200
        assert resp.json()["collection"]["name"] == "Upload"


class TestEnvironmentLoading:
    def test_load_local_environment(self, tmp_path) -> None:
        env = {"name": "Dev", "values": [{"key": "host", "value": "dev.api.com"}]}
        path = tmp_path / "env.json"
        path.write_text(json.dumps(env))

        app = create_app(working_dir=str(tmp_path))
        tc = TestClient(app)
        resp = tc.post("/api/environment/load-local", json={"path": str(path)})
        assert resp.status_code == 200
        assert resp.json()["variables"]["host"] == "dev.api.com"


class TestVariableUpdate:
    def test_update_variables(self, client_with_collection) -> None:
        resp = client_with_collection.post("/api/variables/update", json={"variables": {"host": "new.api.com"}})
        assert resp.status_code == 200


class TestTestStatus:
    def test_idle_status(self, client) -> None:
        resp = client.get("/api/test/status")
        assert resp.json()["status"] == "idle"


class TestRunsList:
    def test_empty_runs(self, client) -> None:
        resp = client.get("/api/runs")
        assert resp.json()["runs"] == []


class TestStartTestValidation:
    def test_no_collection_loaded(self, tmp_path) -> None:
        from overload.web.routes.api import _state
        _state["collection"] = None
        app = create_app(working_dir=str(tmp_path))
        tc = TestClient(app)
        resp = tc.post("/api/test/start", json={"test_type": "burst", "config": {}})
        assert resp.status_code == 400
        assert "No collection loaded" in resp.json()["message"]


class TestConfigEndpoints:
    def test_save_and_load_config(self, tmp_path) -> None:
        app = create_app(working_dir=str(tmp_path))
        tc = TestClient(app)

        payload = {
            "test_type": "load",
            "config": {"target_rps": 100},
            "thresholds": [
                {"metric": "p95_latency_ms", "operator": "<", "value": 500},
            ],
        }
        resp = tc.post("/api/config/save", json=payload)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        resp = tc.get("/api/config/load")
        assert resp.status_code == 200
        data = resp.json()["config"]
        assert data["test_type"] == "load"
        assert data["config"]["target_rps"] == 100
        assert len(data["thresholds"]) == 1

    def test_load_config_not_found(self, client) -> None:
        resp = client.get("/api/config/load")
        assert resp.status_code == 404


@pytest.fixture
def multi_request_collection(tmp_path):
    collection = {
        "info": {
            "name": "Multi",
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "item": [
            {"name": "R1", "request": {"method": "GET", "url": "https://a.com/1"}},
            {"name": "R2", "request": {"method": "GET", "url": "https://a.com/2"}},
            {"name": "R3", "request": {"method": "GET", "url": "https://a.com/3"}},
        ],
    }
    coll_path = tmp_path / "multi.json"
    coll_path.write_text(json.dumps(collection))
    app = create_app(working_dir=str(tmp_path))
    tc = TestClient(app)
    tc.post("/api/collection/load-local", json={"path": str(coll_path)})
    return tc


class TestSelectedRequests:
    def test_empty_selection_returns_400(self, multi_request_collection) -> None:
        resp = multi_request_collection.post(
            "/api/test/start",
            json={"test_type": "burst", "config": {}, "selected_requests": []},
        )
        assert resp.status_code == 400
        assert "No requests selected" in resp.json()["message"]

    def test_valid_selection_accepted(self, multi_request_collection) -> None:
        resp = multi_request_collection.post(
            "/api/test/start",
            json={"test_type": "burst", "config": {}, "selected_requests": [0, 2]},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_no_selection_field_runs_all(self, multi_request_collection) -> None:
        resp = multi_request_collection.post(
            "/api/test/start",
            json={"test_type": "burst", "config": {}},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestStopGeneratesReport:
    async def test_graceful_stop_produces_stopped_status(self, tmp_path) -> None:
        """Stopping a test gracefully should produce status 'stopped' with a report."""
        fake_results = [
            RequestResult(
                request_name="req",
                method="GET",
                url="https://a.com",
                status_code=200,
                latency_ms=50.0,
                timestamp=float(i),
            )
            for i in range(5)
        ]

        async def fake_execute(client, requests, variables, config, run_id, cancel_event, on_progress):
            cancel_event.set()
            return fake_results

        mock_pattern = AsyncMock()
        mock_pattern.execute.side_effect = fake_execute

        collection = {
            "info": {
                "name": "Stop Test",
                "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
            },
            "item": [{"name": "R1", "request": {"method": "GET", "url": "https://a.com"}}],
        }
        coll_path = tmp_path / "coll.json"
        coll_path.write_text(json.dumps(collection))

        with patch("overload.engine.service.get_pattern", return_value=mock_pattern):
            app = create_app(working_dir=str(tmp_path))
            from httpx import ASGITransport, AsyncClient

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                await ac.post("/api/collection/load-local", json={"path": str(coll_path)})
                resp = await ac.post("/api/test/start", json={"test_type": "burst", "config": {}})
                assert resp.status_code == 200
                run_id = resp.json()["run_id"]

                # Give the background task time to complete
                await asyncio.sleep(0.5)

                runs_resp = await ac.get("/api/runs")
                runs = {r["run_id"]: r for r in runs_resp.json()["runs"]}

                assert run_id in runs
                assert runs[run_id]["status"] == "stopped"

                data_resp = await ac.get(f"/api/runs/{run_id}/data")
                data = data_resp.json()
                assert data["report_path"] is not None
                assert Path(data["report_path"]).exists()

    async def test_hard_cancel_still_stores_stopped_status(self, tmp_path) -> None:
        """Hard-cancelling the task should still result in status 'stopped', not 'cancelled'."""
        collection = {
            "info": {
                "name": "Hard Cancel",
                "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
            },
            "item": [{"name": "R1", "request": {"method": "GET", "url": "https://a.com"}}],
        }
        coll_path = tmp_path / "coll2.json"
        coll_path.write_text(json.dumps(collection))

        hang_event = asyncio.Event()

        async def fake_execute_hang(client, requests, variables, config, run_id, cancel_event, on_progress):
            await hang_event.wait()  # blocks until cancelled
            return []

        mock_pattern = AsyncMock()
        mock_pattern.execute.side_effect = fake_execute_hang

        with patch("overload.engine.service.get_pattern", return_value=mock_pattern):
            app = create_app(working_dir=str(tmp_path))
            from httpx import ASGITransport, AsyncClient

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                await ac.post("/api/collection/load-local", json={"path": str(coll_path)})
                resp = await ac.post("/api/test/start", json={"test_type": "burst", "config": {}})
                run_id = resp.json()["run_id"]

                await asyncio.sleep(0.1)

                # Directly cancel the task (simulates watchdog)
                from overload.web.routes.api import _state
                task = _state.get("current_task")
                if task and not task.done():
                    task.cancel()

                await asyncio.sleep(0.3)

                data_resp = await ac.get(f"/api/runs/{run_id}/data")
                data = data_resp.json()
                assert data.get("status") == "stopped"


class TestCsvUpload:
    def test_upload_csv_bytes_not_path(self, multi_request_collection) -> None:
        """Uploading CSV bytes must succeed — not raise FileNotFoundError from from_csv()."""
        csv_content = b"email,token\nalice@a.com,tok-a\nbob@b.com,tok-b\n"
        resp = multi_request_collection.post(
            "/api/data/upload",
            files={"file": ("data.csv", csv_content, "text/csv")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["row_count"] == 2
        assert "email" in data["columns"]

    def test_upload_csv_with_bom(self, multi_request_collection) -> None:
        csv_content = b"\xef\xbb\xbfemail,token\nalice@a.com,tok-a\n"
        resp = multi_request_collection.post(
            "/api/data/upload",
            files={"file": ("data.csv", csv_content, "text/csv")},
        )
        assert resp.status_code == 200
        assert resp.json()["columns"][0] == "email"


class TestSelectedRequestsValidation:
    def test_negative_index_rejected(self, multi_request_collection) -> None:
        resp = multi_request_collection.post(
            "/api/test/start",
            json={"test_type": "burst", "config": {}, "selected_requests": [-1]},
        )
        assert resp.status_code == 400
        assert "Invalid request indices" in resp.json()["message"]

    def test_out_of_range_index_rejected(self, multi_request_collection) -> None:
        resp = multi_request_collection.post(
            "/api/test/start",
            json={"test_type": "burst", "config": {}, "selected_requests": [999]},
        )
        assert resp.status_code == 400
        assert "Invalid request indices" in resp.json()["message"]

    def test_mixed_valid_and_invalid_rejected(self, multi_request_collection) -> None:
        resp = multi_request_collection.post(
            "/api/test/start",
            json={"test_type": "burst", "config": {}, "selected_requests": [0, -1]},
        )
        assert resp.status_code == 400


class TestRunHistory:
    def test_historical_runs_loaded_from_disk(self, tmp_path) -> None:
        """Runs saved as _meta.json sidecars must appear in /api/runs after restart."""
        import json as _json
        from overload.engine import service

        # Write a fake sidecar as if a previous session had run a test
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        sidecar = {
            "run_id": "burst_historical_abc",
            "test_type": "burst",
            "status": "complete",
            "stats": {"total": 50, "ok": 50, "errors": 0, "avg_rps": 12.5, "duration_seconds": 4.0,
                      "latency": {"median": 30, "p95": 80, "p99": 100, "max": 150},
                      "per_second": [], "status_codes": {}, "timeline": [], "request_log": []},
            "verdict": None,
            "ramp_rows": [],
            "report_path": str(reports_dir / "overload_report_burst_historical_abc.html"),
        }
        (reports_dir / "burst_historical_abc_meta.json").write_text(_json.dumps(sidecar))

        service._runs.clear()

        app = create_app(working_dir=str(tmp_path))
        tc = TestClient(app)
        resp = tc.get("/api/runs")
        assert resp.status_code == 200
        run_ids = [r["run_id"] for r in resp.json()["runs"]]
        assert "burst_historical_abc" in run_ids

    async def test_sidecar_written_after_run(self, tmp_path) -> None:
        """After a test completes, a _meta.json sidecar must exist in reports/."""
        from unittest.mock import AsyncMock, patch

        from overload.engine.models import RequestResult

        fake_results = [
            RequestResult(request_name="r", method="GET", url="https://a.com",
                          status_code=200, latency_ms=20.0, timestamp=float(i))
            for i in range(3)
        ]

        async def fake_execute(client, requests, variables, config, run_id, cancel_event, on_progress):
            return fake_results

        mock_pattern = AsyncMock()
        mock_pattern.execute.side_effect = fake_execute

        coll_data = {
            "info": {"name": "Sidecar", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
            "item": [{"name": "R1", "request": {"method": "GET", "url": "https://a.com"}}],
        }
        coll_path = tmp_path / "sidecar.json"
        coll_path.write_text(json.dumps(coll_data))

        with patch("overload.engine.service.get_pattern", return_value=mock_pattern):
            from httpx import ASGITransport, AsyncClient

            app = create_app(working_dir=str(tmp_path))
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                await ac.post("/api/collection/load-local", json={"path": str(coll_path)})
                r = await ac.post("/api/test/start", json={"test_type": "burst", "config": {}})
                run_id = r.json()["run_id"]
                await asyncio.sleep(0.5)

        reports_dir = tmp_path / "reports"
        sidecar = reports_dir / f"{run_id}_meta.json"
        assert sidecar.exists(), f"Sidecar not found at {sidecar}"
        import json as _json
        data = _json.loads(sidecar.read_text())
        assert data["run_id"] == run_id
        assert data["status"] == "complete"
