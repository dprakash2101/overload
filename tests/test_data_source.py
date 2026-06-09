from __future__ import annotations

import io
import textwrap

import pytest

from overload.collection.data_source import DataSource
from overload.collection.models import AuthConfig, ParsedCollection, ParsedRequest, QueryParam, RequestBody
from overload.collection.variables import VariableContext, discover_placeholders


class TestDataSourceFromCsv:
    def test_from_string_path(self, tmp_path) -> None:
        csv_file = tmp_path / "data.csv"
        csv_file.write_text("email,token\nalice@a.com,tok-a\nbob@b.com,tok-b\n")
        ds = DataSource.from_csv(str(csv_file))
        assert ds.columns == ["email", "token"]
        assert len(ds.rows) == 2
        assert ds.rows[0]["email"] == "alice@a.com"

    def test_from_file_like_bytes(self) -> None:
        content = b"name,value\nfoo,1\nbar,2\n"
        ds = DataSource.from_csv(io.BytesIO(content))
        assert ds.columns == ["name", "value"]
        assert len(ds.rows) == 2

    def test_from_file_like_str(self) -> None:
        content = "x,y\n10,20\n30,40\n"
        ds = DataSource.from_csv(io.StringIO(content))
        assert ds.columns == ["x", "y"]
        assert ds.rows[1]["x"] == "30"

    def test_empty_csv(self, tmp_path) -> None:
        csv_file = tmp_path / "empty.csv"
        csv_file.write_text("col1,col2\n")
        ds = DataSource.from_csv(str(csv_file))
        assert ds.columns == ["col1", "col2"]
        assert ds.rows == []

    def test_bom_stripped(self, tmp_path) -> None:
        csv_file = tmp_path / "bom.csv"
        csv_file.write_bytes(b"\xef\xbb\xbfkey,val\nfoo,bar\n")
        ds = DataSource.from_csv(str(csv_file))
        assert ds.columns[0] == "key"


class TestDataSourceRowFor:
    def test_round_robin(self) -> None:
        ds = DataSource(
            rows=[{"k": "a"}, {"k": "b"}, {"k": "c"}],
            columns=["k"],
        )
        assert ds.row_for(0)["k"] == "a"
        assert ds.row_for(1)["k"] == "b"
        assert ds.row_for(2)["k"] == "c"
        assert ds.row_for(3)["k"] == "a"
        assert ds.row_for(100)["k"] == "b"

    def test_empty_returns_empty_dict(self) -> None:
        ds = DataSource(rows=[], columns=["k"])
        assert ds.row_for(0) == {}
        assert ds.row_for(99) == {}


class TestVariableContextDerive:
    def test_csv_row_overrides_collection(self) -> None:
        ctx = VariableContext(
            collection_vars=[],
            environment_vars={"token": "env-token"},
            runtime_vars={},
        )
        row_ctx = ctx.derive({"token": "csv-token"})
        assert row_ctx.resolve("{{token}}") == "csv-token"

    def test_base_context_unchanged(self) -> None:
        ctx = VariableContext(environment_vars={"k": "original"})
        ctx.derive({"k": "derived"})
        assert ctx.resolve("{{k}}") == "original"

    def test_non_overridden_vars_still_resolve(self) -> None:
        ctx = VariableContext(environment_vars={"host": "api.example.com", "token": "env-tok"})
        row_ctx = ctx.derive({"token": "row-tok"})
        assert row_ctx.resolve("{{host}}") == "api.example.com"
        assert row_ctx.resolve("{{token}}") == "row-tok"

    def test_multiple_derives_stack(self) -> None:
        ctx = VariableContext(environment_vars={"a": "env"})
        ctx2 = ctx.derive({"a": "first"})
        ctx3 = ctx2.derive({"a": "second"})
        assert ctx3.resolve("{{a}}") == "second"
        assert ctx2.resolve("{{a}}") == "first"


class TestDiscoverPlaceholders:
    def _make_collection(self, requests: list[ParsedRequest], auth: AuthConfig | None = None) -> ParsedCollection:
        return ParsedCollection(name="Test", description="", requests=requests, auth=auth)

    def test_url_placeholder(self) -> None:
        req = ParsedRequest(name="r", method="GET", url_raw="https://api.com/{{base_path}}/users")
        coll = self._make_collection([req])
        assert "base_path" in discover_placeholders(coll)

    def test_header_placeholder(self) -> None:
        req = ParsedRequest(name="r", method="GET", url_raw="https://api.com", headers={"Authorization": "Bearer {{token}}"})
        coll = self._make_collection([req])
        assert "token" in discover_placeholders(coll)

    def test_query_param_placeholder(self) -> None:
        req = ParsedRequest(
            name="r", method="GET", url_raw="https://api.com",
            query_params=[QueryParam(key="api_key", value="{{api_key}}")]
        )
        coll = self._make_collection([req])
        assert "api_key" in discover_placeholders(coll)

    def test_auth_param_placeholder(self) -> None:
        req = ParsedRequest(
            name="r", method="GET", url_raw="https://api.com",
            auth=AuthConfig(type="bearer", params={"token": "{{bearer_token}}"})
        )
        coll = self._make_collection([req])
        assert "bearer_token" in discover_placeholders(coll)

    def test_collection_auth_placeholder(self) -> None:
        req = ParsedRequest(name="r", method="GET", url_raw="https://api.com")
        coll = self._make_collection([req], auth=AuthConfig(type="apikey", params={"value": "{{api_key}}"}))
        assert "api_key" in discover_placeholders(coll)

    def test_body_placeholder(self) -> None:
        req = ParsedRequest(
            name="r", method="POST", url_raw="https://api.com",
            body=RequestBody(mode="raw", content='{"email": "{{email}}"}')
        )
        coll = self._make_collection([req])
        assert "email" in discover_placeholders(coll)

    def test_deduplication(self) -> None:
        req = ParsedRequest(
            name="r", method="GET",
            url_raw="https://api.com/{{env}}/v1",
            headers={"X-Env": "{{env}}"},
        )
        coll = self._make_collection([req])
        placeholders = discover_placeholders(coll)
        assert placeholders.count("env") if isinstance(placeholders, list) else "env" in placeholders
        assert len([p for p in placeholders if p == "env"]) == 1

    def test_no_placeholders_returns_empty(self) -> None:
        req = ParsedRequest(name="r", method="GET", url_raw="https://api.com/health")
        coll = self._make_collection([req])
        assert discover_placeholders(coll) == set()


class TestHttpClientDataSource:
    @pytest.mark.asyncio
    async def test_consecutive_calls_cycle_rows(self) -> None:
        import httpx
        from overload.collection.models import ParsedRequest, RequestBody
        from overload.collection.variables import VariableContext
        from overload.engine.http_client import HttpClient

        ds = DataSource(
            rows=[{"user": "alice"}, {"user": "bob"}],
            columns=["user"],
        )

        captured: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(str(request.url))
            return httpx.Response(200, text="ok")

        transport = httpx.MockTransport(handler)

        req = ParsedRequest(
            name="test",
            method="GET",
            url_raw="https://api.example.com/users/{{user}}",
            headers={},
            query_params=[],
            body=RequestBody(mode="none", content=None),
        )

        async with HttpClient(data_source=ds) as client:
            client._client = httpx.AsyncClient(transport=transport)
            ctx = VariableContext()
            await client.execute(req, ctx)
            await client.execute(req, ctx)
            await client.execute(req, ctx)

        assert captured[0].endswith("/users/alice")
        assert captured[1].endswith("/users/bob")
        assert captured[2].endswith("/users/alice")

    @pytest.mark.asyncio
    async def test_no_data_source_works_normally(self) -> None:
        import httpx
        from overload.collection.models import ParsedRequest, RequestBody
        from overload.collection.variables import VariableContext
        from overload.engine.http_client import HttpClient

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="ok")

        transport = httpx.MockTransport(handler)

        req = ParsedRequest(
            name="test",
            method="GET",
            url_raw="https://api.example.com/health",
            headers={},
            query_params=[],
            body=RequestBody(mode="none", content=None),
        )

        async with HttpClient() as client:
            client._client = httpx.AsyncClient(transport=transport)
            result = await client.execute(req, VariableContext())

        assert result.status_code == 200
