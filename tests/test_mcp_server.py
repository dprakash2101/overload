from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from overload.engine.models import RequestResult
from overload.mcp_server import (
    describe_collection,
    get_run_results,
    get_run_status,
    list_patterns,
    run_load_test,
    stop_run,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def simple_collection(tmp_path: Path) -> Path:
    data = {
        "info": {
            "name": "MCP Test Collection",
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "item": [
            {
                "name": "Health",
                "request": {"method": "GET", "url": "https://api.example.com/{{env}}/health"},
            },
            {
                "name": "Create User",
                "request": {
                    "method": "POST",
                    "url": "https://api.example.com/users",
                    "body": {"mode": "raw", "raw": '{"email": "{{email}}"}'},
                },
            },
        ],
    }
    p = tmp_path / "collection.json"
    p.write_text(json.dumps(data))
    return p


@pytest.fixture(autouse=True)
def _clear_service_runs():
    """Reset service state between tests so runs don't leak across tests."""
    from overload.engine import service
    service._runs.clear()
    service._tasks.clear()
    service._cancel_events.clear()
    service._progress.clear()
    yield
    service._runs.clear()
    service._tasks.clear()
    service._cancel_events.clear()
    service._progress.clear()


# ---------------------------------------------------------------------------
# list_patterns
# ---------------------------------------------------------------------------

class TestListPatterns:
    def test_returns_all_ten_patterns(self) -> None:
        result = list_patterns()
        names = {p["name"] for p in result}
        expected = {"burst", "load", "stress", "spike", "soak", "ramp", "breakpoint", "custom", "ratelimit", "sequential"}
        assert names == expected

    def test_each_entry_has_name_and_description(self) -> None:
        for entry in list_patterns():
            assert "name" in entry
            assert "description" in entry
            assert len(entry["description"]) > 10


# ---------------------------------------------------------------------------
# describe_collection
# ---------------------------------------------------------------------------

class TestDescribeCollection:
    def test_returns_name_and_requests(self, simple_collection: Path) -> None:
        result = describe_collection(str(simple_collection))
        assert result["name"] == "MCP Test Collection"
        assert result["request_count"] == 2

    def test_detects_placeholders(self, simple_collection: Path) -> None:
        result = describe_collection(str(simple_collection))
        placeholders = result["placeholders"]
        assert "env" in placeholders
        assert "email" in placeholders

    def test_missing_file_returns_error(self) -> None:
        result = describe_collection("/nonexistent/path/collection.json")
        assert "error" in result

    def test_request_list_shape(self, simple_collection: Path) -> None:
        result = describe_collection(str(simple_collection))
        req = result["requests"][0]
        assert "name" in req
        assert "method" in req
        assert "url" in req


# ---------------------------------------------------------------------------
# run_load_test (guardrails + validation)
# ---------------------------------------------------------------------------

class TestRunLoadTest:
    async def test_missing_collection_returns_error(self) -> None:
        result = await run_load_test("/nonexistent/collection.json")
        assert "error" in result

    async def test_empty_selected_requests_returns_error(self, simple_collection: Path) -> None:
        result = await run_load_test(str(simple_collection), selected_requests=[])
        assert "error" in result

    async def test_invalid_assertion_returns_error(self, simple_collection: Path) -> None:
        result = await run_load_test(str(simple_collection), assertions=["bad_metric_name<<500"])
        assert "error" in result

    async def test_concurrency_capped(self, simple_collection: Path) -> None:
        fake_results = [
            RequestResult("req", "GET", "https://a.com", 200, 10.0, float(i))
            for i in range(3)
        ]

        async def fake_execute(client, reqs, variables, config, run_id, cancel_event, on_progress):
            return fake_results

        mock_pattern = AsyncMock()
        mock_pattern.execute.side_effect = fake_execute

        with patch("overload.engine.service.get_pattern", return_value=mock_pattern):
            result = await run_load_test(
                str(simple_collection),
                concurrency=9999,
                total_requests=9999,
            )

        assert "error" not in result
        applied = result["guardrails_applied"]
        assert applied["concurrency"] <= 200
        assert applied["total_requests"] <= 10_000

    async def test_returns_run_id_immediately(self, simple_collection: Path) -> None:
        fake_results = [
            RequestResult("req", "GET", "https://a.com", 200, 10.0, float(i))
            for i in range(2)
        ]

        async def fake_execute(client, reqs, variables, config, run_id, cancel_event, on_progress):
            return fake_results

        mock_pattern = AsyncMock()
        mock_pattern.execute.side_effect = fake_execute

        with patch("overload.engine.service.get_pattern", return_value=mock_pattern):
            result = await run_load_test(str(simple_collection), pattern="burst")

        assert "run_id" in result
        assert "error" not in result


# ---------------------------------------------------------------------------
# get_run_status
# ---------------------------------------------------------------------------

class TestGetRunStatus:
    def test_missing_run_returns_error(self) -> None:
        result = get_run_status("nonexistent-run-id")
        assert "error" in result

    def test_running_status(self) -> None:
        from overload.engine import service
        service._runs["test-run"] = {"run_id": "test-run", "test_type": "burst", "status": "running"}
        result = get_run_status("test-run")
        assert result["status"] == "running"

    def test_complete_status(self) -> None:
        from overload.engine import service
        service._runs["done-run"] = {"run_id": "done-run", "test_type": "burst", "status": "complete", "stats": None}
        result = get_run_status("done-run")
        assert result["status"] == "complete"

    def test_includes_progress_when_available(self) -> None:
        from overload.engine import service
        from overload.engine.models import RunProgress
        service._runs["prog-run"] = {"run_id": "prog-run", "test_type": "burst", "status": "running"}
        service._progress["prog-run"] = RunProgress(
            run_id="prog-run",
            total_requests=100,
            completed_requests=50,
            current_rps=25.0,
            phase="firing",
            elapsed_seconds=2.0,
        )
        result = get_run_status("prog-run")
        assert result["completed_requests"] == 50
        assert result["current_rps"] == 25.0


# ---------------------------------------------------------------------------
# get_run_results
# ---------------------------------------------------------------------------

class TestGetRunResults:
    def test_missing_run_returns_error(self) -> None:
        result = get_run_results("nonexistent")
        assert "error" in result

    def test_still_running_returns_error(self) -> None:
        from overload.engine import service
        service._runs["active"] = {"run_id": "active", "test_type": "burst", "status": "running"}
        result = get_run_results("active")
        assert "error" in result

    def test_complete_run_with_stats(self) -> None:
        from overload.engine import service
        service._runs["fin"] = {
            "run_id": "fin",
            "test_type": "burst",
            "status": "complete",
            "stats": {
                "total": 10,
                "ok": 9,
                "errors": 1,
                "rate_limited": 0,
                "avg_rps": 5.0,
                "duration_seconds": 2.0,
                "latency": {"min": 5.0, "median": 10.0, "mean": 11.0, "p95": 20.0, "p99": 25.0, "max": 30.0},
            },
            "verdict": None,
            "report_path": None,
        }
        result = get_run_results("fin")
        assert result["status"] == "complete"
        assert result["summary"]["total_requests"] == 10
        assert result["summary"]["success_rate_pct"] == 90.0
        assert result["summary"]["latency_p95_ms"] == 20.0

    def test_verdict_included_when_present(self) -> None:
        from overload.engine import service
        service._runs["v-run"] = {
            "run_id": "v-run",
            "test_type": "burst",
            "status": "complete",
            "stats": {
                "total": 5, "ok": 5, "errors": 0, "rate_limited": 0,
                "avg_rps": 5.0, "duration_seconds": 1.0,
                "latency": {"min": 5.0, "median": 5.0, "mean": 5.0, "p95": 5.0, "p99": 5.0, "max": 5.0},
            },
            "verdict": {"passed": True, "results": []},
            "report_path": None,
        }
        result = get_run_results("v-run")
        assert result["verdict"]["passed"] is True


# ---------------------------------------------------------------------------
# stop_run
# ---------------------------------------------------------------------------

class TestStopRun:
    async def test_missing_run_returns_error(self) -> None:
        result = await stop_run("nonexistent")
        assert "error" in result

    async def test_completed_run_returns_ok(self) -> None:
        from overload.engine import service
        service._runs["done"] = {"run_id": "done", "test_type": "burst", "status": "complete"}
        result = await stop_run("done")
        assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# service.run_test integration (happy path via mock transport)
# ---------------------------------------------------------------------------

class TestServiceRunTest:
    @pytest.mark.asyncio
    async def test_happy_path_stores_run_and_returns_result(self, simple_collection: Path, tmp_path: Path) -> None:
        from overload.collection.parser import parse_collection
        from overload.collection.variables import VariableContext
        from overload.engine import service
        from overload.engine.models import PatternConfig

        collection = parse_collection(str(simple_collection))
        variables = VariableContext(collection_vars=collection.variables)
        config = PatternConfig(total_requests=3, concurrency=2)

        fake_results = [
            RequestResult("Health", "GET", "https://api.example.com/prod/health", 200, 15.0, time.time() + i)
            for i in range(3)
        ]

        async def fake_execute(client, reqs, variables, cfg, run_id, cancel_event, on_progress):
            return fake_results

        mock_pattern = AsyncMock()
        mock_pattern.execute.side_effect = fake_execute

        with patch("overload.engine.service.get_pattern", return_value=mock_pattern):
            result = await service.run_test(
                collection, "burst", config,
                variables=variables,
                output_dir=str(tmp_path / "reports"),
            )

        assert result.status == "complete"
        assert result.stats is not None
        assert result.stats["total"] == 3
        assert result.run_id in service._runs
        assert service._runs[result.run_id]["status"] == "complete"

    @pytest.mark.asyncio
    async def test_cancel_event_produces_stopped_status(self, simple_collection: Path, tmp_path: Path) -> None:
        from overload.collection.parser import parse_collection
        from overload.collection.variables import VariableContext
        from overload.engine import service
        from overload.engine.models import PatternConfig

        collection = parse_collection(str(simple_collection))
        variables = VariableContext(collection_vars=collection.variables)
        config = PatternConfig(total_requests=5, concurrency=2)

        fake_results = [
            RequestResult("Health", "GET", "https://api.example.com/prod/health", 200, 10.0, time.time() + i)
            for i in range(3)
        ]

        async def fake_execute_with_cancel(client, reqs, variables, cfg, run_id, cancel_event, on_progress):
            cancel_event.set()
            return fake_results

        mock_pattern = AsyncMock()
        mock_pattern.execute.side_effect = fake_execute_with_cancel

        with patch("overload.engine.service.get_pattern", return_value=mock_pattern):
            result = await service.run_test(
                collection, "burst", config,
                variables=variables,
                output_dir=str(tmp_path / "reports"),
            )

        assert result.status == "stopped"
        assert service._runs[result.run_id]["status"] == "stopped"


# ---------------------------------------------------------------------------
# describe_collection — completeness (query params, auth)
# ---------------------------------------------------------------------------

class TestDescribeCollectionCompleteness:
    def test_detects_query_param_placeholder(self, tmp_path: Path) -> None:
        data = {
            "info": {
                "name": "QP Test",
                "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
            },
            "item": [
                {
                    "name": "Search",
                    "request": {
                        "method": "GET",
                        "url": {
                            "raw": "https://api.example.com/search?q={{query}}",
                            "query": [{"key": "q", "value": "{{query}}"}],
                        },
                    },
                }
            ],
        }
        p = tmp_path / "qp.json"
        p.write_text(__import__("json").dumps(data))
        result = describe_collection(str(p))
        assert "query" in result["placeholders"]

    def test_detects_auth_placeholder(self, tmp_path: Path) -> None:
        data = {
            "info": {
                "name": "Auth Test",
                "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
            },
            "item": [
                {
                    "name": "Secured",
                    "request": {
                        "method": "GET",
                        "url": "https://api.example.com/secure",
                        "auth": {
                            "type": "bearer",
                            "bearer": [{"key": "token", "value": "{{bearer_token}}", "type": "string"}],
                        },
                    },
                }
            ],
        }
        p = tmp_path / "auth.json"
        p.write_text(__import__("json").dumps(data))
        result = describe_collection(str(p))
        assert "bearer_token" in result["placeholders"]


# ---------------------------------------------------------------------------
# run_load_test — invalid selected_requests
# ---------------------------------------------------------------------------

class TestRunLoadTestValidation:
    async def test_negative_index_returns_error(self, simple_collection: Path) -> None:
        result = await run_load_test(str(simple_collection), selected_requests=[-1])
        assert "error" in result
        assert "Invalid request indices" in result["error"]

    async def test_out_of_range_index_returns_error(self, simple_collection: Path) -> None:
        result = await run_load_test(str(simple_collection), selected_requests=[999])
        assert "error" in result
        assert "Invalid request indices" in result["error"]


# ---------------------------------------------------------------------------
# MCP registration text goes to stderr, not stdout
# ---------------------------------------------------------------------------

class TestMcpRegistrationOutput:
    def test_registration_instructions_not_empty(self) -> None:
        from overload.mcp_server import _registration_instructions
        text = _registration_instructions()
        assert "claude mcp add" in text
        assert "overload mcp" in text

    def test_main_writes_to_stderr_not_stdout(self, capsys) -> None:
        """Registration instructions must not pollute the MCP stdio stdout stream."""
        import sys
        from io import StringIO
        from unittest.mock import MagicMock, patch

        fake_mcp = MagicMock()
        fake_mcp.tool.return_value = lambda f: f
        fake_mcp.run.return_value = None

        old_stdout = sys.stdout
        old_stderr = sys.stderr
        captured_stdout = StringIO()
        captured_stderr = StringIO()
        sys.stdout = captured_stdout
        sys.stderr = captured_stderr
        try:
            with patch("overload.mcp_server.FastMCP", return_value=fake_mcp, create=True):
                try:
                    from overload.mcp_server import main
                    main()
                except Exception:
                    pass
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

        assert captured_stdout.getvalue() == "", "Registration text must not go to stdout"
        assert "claude mcp add" in captured_stderr.getvalue() or captured_stderr.getvalue() == ""


# ---------------------------------------------------------------------------
# Service — error status emits "error" phase, not "complete"
# ---------------------------------------------------------------------------

class TestServiceErrorProgress:
    async def test_error_run_emits_error_phase(self, simple_collection: Path, tmp_path: Path) -> None:
        from overload.collection.parser import parse_collection
        from overload.collection.variables import VariableContext
        from overload.engine import service
        from overload.engine.models import PatternConfig

        collection = parse_collection(str(simple_collection))
        variables = VariableContext(collection_vars=collection.variables)
        config = PatternConfig()

        phases_received: list[str] = []

        async def on_progress(p) -> None:
            phases_received.append(p.phase)

        with patch("overload.engine.service.get_pattern", side_effect=RuntimeError("boom")):
            result = await service.run_test(
                collection, "burst", config,
                variables=variables,
                output_dir=str(tmp_path / "reports"),
                on_progress=on_progress,
            )

        assert result.status == "error"
        assert phases_received[-1] == "error", f"Expected last phase 'error', got {phases_received}"
