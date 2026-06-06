from __future__ import annotations

import logging
import time

import httpx

from overload.collection.data_source import DataSource
from overload.collection.models import AuthConfig, ParsedRequest, RequestBody
from overload.collection.variables import VariableContext
from overload.engine.models import RequestResult

logger = logging.getLogger(__name__)


class HttpClient:
    def __init__(
        self,
        timeout: float = 30.0,
        verify_ssl: bool = True,
        follow_redirects: bool = True,
        max_connections: int = 100,
        save_responses: bool = False,
        data_source: DataSource | None = None,
    ) -> None:
        self._timeout = timeout
        self._verify_ssl = verify_ssl
        self._follow_redirects = follow_redirects
        self._max_connections = max_connections
        self._save_responses = save_responses
        self._data_source = data_source
        self._row_index = 0
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> HttpClient:
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self._timeout),
            verify=self._verify_ssl,
            follow_redirects=self._follow_redirects,
            limits=httpx.Limits(
                max_connections=self._max_connections,
                max_keepalive_connections=self._max_connections // 2,
            ),
        )
        return self

    async def __aexit__(self, *args: object) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def execute(
        self,
        request: ParsedRequest,
        variables: VariableContext | None = None,
    ) -> RequestResult:
        if self._client is None:
            raise RuntimeError("HttpClient must be used as an async context manager")

        ctx = variables or VariableContext()

        if self._data_source is not None:
            row = self._data_source.row_for(self._row_index)
            self._row_index += 1
            ctx = ctx.derive(row)

        url = ctx.resolve_url(request.url_raw)
        method = request.method
        headers = ctx.resolve_dict(request.headers)
        request_name = request.name

        query_params = {
            ctx.resolve(q.key): ctx.resolve(q.value)
            for q in request.query_params
            if not q.disabled
        }

        self._apply_auth(request.auth, headers, ctx, query_params)

        content, content_headers = self._prepare_body(request.body, ctx)
        headers.update(content_headers)

        logger.debug(
            "Executing %s %s (name=%s)", method, url, request_name,
        )

        timestamp = time.time()
        t0 = time.monotonic()

        try:
            response = await self._client.request(
                method=method,
                url=url,
                headers=headers,
                params=query_params if query_params else None,
                **content,
            )
            latency_ms = (time.monotonic() - t0) * 1000

            logger.debug(
                "%s %s -> %d (%.1fms)",
                method, url, response.status_code, latency_ms,
            )

            resp_body = None
            if self._save_responses:
                try:
                    resp_body = response.text[:10_000]
                except Exception:
                    resp_body = f"<binary {len(response.content)} bytes>"

            return RequestResult(
                request_name=request_name,
                method=method,
                url=url,
                status_code=response.status_code,
                latency_ms=latency_ms,
                timestamp=timestamp,
                headers_sent=dict(headers),
                headers_received=dict(response.headers),
                body_size_bytes=len(response.content),
                response_body=resp_body,
            )

        except httpx.TimeoutException:
            latency_ms = (time.monotonic() - t0) * 1000
            logger.warning("Timeout: %s %s after %.1fms", method, url, latency_ms)
            return RequestResult(
                request_name=request_name,
                method=method,
                url=url,
                status_code=0,
                latency_ms=latency_ms,
                timestamp=timestamp,
                error="timeout",
            )

        except httpx.ConnectError as exc:
            latency_ms = (time.monotonic() - t0) * 1000
            logger.error("Connection error: %s %s - %s", method, url, exc)
            return RequestResult(
                request_name=request_name,
                method=method,
                url=url,
                status_code=-1,
                latency_ms=latency_ms,
                timestamp=timestamp,
                error=f"connection_error: {exc}",
            )

        except httpx.HTTPError as exc:
            latency_ms = (time.monotonic() - t0) * 1000
            logger.error("HTTP error: %s %s - %s", method, url, exc)
            return RequestResult(
                request_name=request_name,
                method=method,
                url=url,
                status_code=-1,
                latency_ms=latency_ms,
                timestamp=timestamp,
                error=str(exc),
            )

    async def prepare_collection_auth(
        self,
        auth: AuthConfig | None,
        ctx: VariableContext,
    ) -> None:
        if not auth or auth.type != "oauth2":
            return
        if self._client is None:
            raise RuntimeError("HttpClient must be used as an async context manager")
        from overload.engine.auth import fetch_oauth2_token
        token = await fetch_oauth2_token(auth, ctx, self._client)
        ctx.set_variable("_oauth2_access_token", token)
        logger.info("OAuth2: access token ready, injected into variable context")

    def _apply_auth(
        self,
        auth: AuthConfig | None,
        headers: dict[str, str],
        ctx: VariableContext,
        query_params: dict[str, str] | None = None,
    ) -> None:
        if not auth:
            return

        if auth.type == "bearer":
            token = ctx.resolve(auth.params.get("token", ""))
            if token:
                headers["Authorization"] = f"Bearer {token}"

        elif auth.type == "basic":
            import base64
            username = ctx.resolve(auth.params.get("username", ""))
            password = ctx.resolve(auth.params.get("password", ""))
            credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
            headers["Authorization"] = f"Basic {credentials}"

        elif auth.type == "apikey":
            key = ctx.resolve(auth.params.get("key", ""))
            value = ctx.resolve(auth.params.get("value", ""))
            location = auth.params.get("in", "header")
            if location == "header" and key:
                headers[key] = value
            elif location == "query" and key and query_params is not None:
                query_params[key] = value

        elif auth.type == "oauth2":
            token = ctx.resolve("{{_oauth2_access_token}}")
            if token and token != "{{_oauth2_access_token}}":
                headers["Authorization"] = f"Bearer {token}"
            else:
                logger.warning(
                    "OAuth2: no access token found in context — "
                    "prepare_collection_auth() may not have been called"
                )

        else:
            logger.warning(
                "Unsupported auth type: %s — request will be sent without authentication",
                auth.type,
            )

    def _prepare_body(
        self,
        body: RequestBody,
        ctx: VariableContext,
    ) -> tuple[dict, dict[str, str]]:
        extra_headers: dict[str, str] = {}

        if body.mode == "none":
            return {}, extra_headers

        if body.mode == "raw":
            content_str = ctx.resolve(str(body.content))
            if body.content_type:
                extra_headers["Content-Type"] = body.content_type
            return {"content": content_str}, extra_headers

        if body.mode == "urlencoded":
            fields = body.content if isinstance(body.content, list) else []
            data = {
                ctx.resolve(f["key"]): ctx.resolve(f.get("value", ""))
                for f in fields
                if isinstance(f, dict)
            }
            return {"data": data}, extra_headers

        if body.mode == "formdata":
            fields = body.content if isinstance(body.content, list) else []
            files = {}
            data = {}
            for f in fields:
                if not isinstance(f, dict):
                    continue
                key = ctx.resolve(f["key"])
                if f.get("type") == "file":
                    file_path = f.get("value", "") or f.get("src", "")
                    try:
                        files[key] = open(file_path, "rb")
                    except (OSError, FileNotFoundError):
                        logger.warning("Cannot open file: %s", file_path)
                else:
                    data[key] = ctx.resolve(f.get("value", ""))
            kwargs: dict = {}
            if data:
                kwargs["data"] = data
            if files:
                kwargs["files"] = files
            return kwargs, extra_headers

        if body.mode == "graphql":
            import json
            gql = body.content if isinstance(body.content, dict) else {}
            payload = {
                "query": ctx.resolve(gql.get("query", "")),
                "variables": ctx.resolve(gql.get("variables", "{}")),
            }
            extra_headers["Content-Type"] = "application/json"
            return {"content": json.dumps(payload)}, extra_headers

        return {}, extra_headers
