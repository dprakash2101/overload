from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

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
