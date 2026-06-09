from __future__ import annotations

import asyncio
import json
import os

import httpx
import pytest

from overload.collection.models import ParsedCollection, ParsedRequest, RequestBody
from overload.collection.variables import VariableContext
from overload.engine import http_client as hc
from overload.engine import service
from overload.engine.models import PatternConfig


def _collection() -> ParsedCollection:
    req = ParsedRequest(
        name="r", method="GET", url_raw="https://api.com/x",
        body=RequestBody(mode="none", content=None),
    )
    return ParsedCollection(name="t", description="", requests=[req])


@pytest.fixture
def mock_transport(monkeypatch):
    """Patch HttpClient so every request hits an in-memory slow mock server."""
    def install(handler):
        orig = hc.HttpClient.__aenter__

        async def patched(self):
            client = await orig(self)
            self._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            return client

        monkeypatch.setattr(hc.HttpClient, "__aenter__", patched)
    return install


class TestRunFolderLayout:
    @pytest.mark.asyncio
    async def test_report_responses_meta_in_run_folder(self, tmp_path, mock_transport) -> None:
        async def handler(request):
            return httpx.Response(200, json={"echo": str(request.url)})
        mock_transport(handler)

        cfg = PatternConfig(concurrency=4, total_requests=12, save_responses=True)
        result = await service.run_test(
            _collection(), "burst", cfg,
            variables=VariableContext(), output_dir=str(tmp_path),
            run_id="layout_001", cancel_event=asyncio.Event(),
        )

        run_dir = tmp_path / "run_layout_001"
        assert (run_dir / "report.html").exists()
        assert (run_dir / "responses.json").exists()
        assert (run_dir / "meta.json").exists()
        assert result.report_path == str(run_dir / "report.html")

        # Response bodies live in responses.json, not embedded in the HTML report.
        assert '"response_body"' not in (run_dir / "report.html").read_text()
        responses = json.loads((run_dir / "responses.json").read_text())
        assert responses["count"] == 12

    @pytest.mark.asyncio
    async def test_no_responses_file_without_save_responses(self, tmp_path, mock_transport) -> None:
        async def handler(request):
            return httpx.Response(200, text="ok")
        mock_transport(handler)

        cfg = PatternConfig(concurrency=4, total_requests=8, save_responses=False)
        await service.run_test(
            _collection(), "burst", cfg,
            variables=VariableContext(), output_dir=str(tmp_path),
            run_id="nosave_001", cancel_event=asyncio.Event(),
        )
        assert not (tmp_path / "run_nosave_001" / "responses.json").exists()


class TestHardCancelPreservesResults:
    @pytest.mark.asyncio
    async def test_hard_cancel_generates_report_from_partial_results(
        self, tmp_path, mock_transport
    ) -> None:
        async def slow_handler(request):
            await asyncio.sleep(0.05)
            return httpx.Response(200, text="ok")
        mock_transport(slow_handler)

        cfg = PatternConfig(concurrency=5, total_requests=500)
        task = asyncio.create_task(service.run_test(
            _collection(), "burst", cfg,
            variables=VariableContext(), output_dir=str(tmp_path),
            run_id="hard_001", cancel_event=asyncio.Event(),
        ))
        await asyncio.sleep(0.3)
        task.cancel()  # simulate the watchdog's hard cancel
        result = await task

        assert result.status == "stopped"
        assert result.stats is not None
        assert result.stats["total"] > 0
        assert result.report_path is not None
        assert (tmp_path / "run_hard_001" / "report.html").exists()
        assert (tmp_path / "run_hard_001" / "meta.json").exists()
