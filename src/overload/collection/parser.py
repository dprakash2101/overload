from __future__ import annotations

import json
from pathlib import Path
from collections.abc import Generator
from typing import Any

from overload.collection.models import (
    AuthConfig,
    CollectionVariable,
    ParsedCollection,
    ParsedRequest,
    QueryParam,
    RequestBody,
)

SUPPORTED_SCHEMA_VERSIONS = ("v2.1.0", "v2.0.0")


def parse_collection(source: str | Path | dict) -> ParsedCollection:
    if isinstance(source, dict):
        data = source
    else:
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"Collection file not found: {path}")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

    _validate_schema(data)

    info = data.get("info", {})
    collection_auth = _parse_auth(data.get("auth"))
    collection_vars = [
        CollectionVariable(
            key=v.get("key", ""),
            value=v.get("value", ""),
            type=v.get("type", "string"),
        )
        for v in data.get("variable", [])
    ]

    requests = list(
        _flatten_items(data.get("item", []), path=[], parent_auth=collection_auth)
    )

    return ParsedCollection(
        name=info.get("name", "Unnamed Collection"),
        description=info.get("description", ""),
        requests=requests,
        variables=collection_vars,
        auth=collection_auth,
    )


def _validate_schema(data: dict) -> None:
    schema = data.get("info", {}).get("schema", "")
    if not any(version in schema for version in SUPPORTED_SCHEMA_VERSIONS):
        if not data.get("info", {}).get("name"):
            raise ValueError(
                "Invalid collection format. Expected a Postman Collection v2.x JSON file."
            )


def _flatten_items(
    items: list[dict],
    path: list[str],
    parent_auth: AuthConfig | None,
) -> Generator[ParsedRequest, None, None]:
    for item in items:
        if "item" in item and "request" not in item:
            folder_name = item.get("name", "Unnamed Folder")
            folder_auth = _parse_auth(item.get("auth")) or parent_auth
            yield from _flatten_items(
                item["item"], path=path + [folder_name], parent_auth=folder_auth
            )
        elif "request" in item:
            yield _parse_request(item, path, parent_auth)


def _parse_request(
    item: dict, folder_path: list[str], inherited_auth: AuthConfig | None
) -> ParsedRequest:
    req = item["request"]

    if isinstance(req, str):
        return ParsedRequest(
            name=item.get("name", "Unnamed Request"),
            method="GET",
            url_raw=req,
            folder_path=folder_path,
        )

    method = req.get("method", "GET").upper()
    url_raw, query_params = _parse_url(req.get("url", ""))
    headers = _parse_headers(req.get("header", []))
    body = _parse_body(req.get("body"))
    auth = _parse_auth(req.get("auth")) or inherited_auth

    return ParsedRequest(
        name=item.get("name", "Unnamed Request"),
        method=method,
        url_raw=url_raw,
        headers=headers,
        body=body,
        auth=auth,
        query_params=query_params,
        folder_path=folder_path,
    )


def _parse_url(url: Any) -> tuple[str, list[QueryParam]]:
    if isinstance(url, str):
        return url, []

    if isinstance(url, dict):
        raw = url.get("raw", "")
        query_params = [
            QueryParam(
                key=q.get("key", ""),
                value=q.get("value", ""),
                disabled=q.get("disabled", False),
            )
            for q in url.get("query", [])
        ]

        if not raw:
            protocol = url.get("protocol", "https")
            host = ".".join(url.get("host", []))
            path = "/".join(url.get("path", []))
            raw = f"{protocol}://{host}"
            if path:
                raw += f"/{path}"

        return raw, query_params

    return str(url), []


def _parse_headers(headers: list[dict] | None) -> dict[str, str]:
    if not headers:
        return {}
    return {
        h["key"]: h.get("value", "")
        for h in headers
        if not h.get("disabled", False) and "key" in h
    }


def _parse_body(body: dict | None) -> RequestBody:
    if not body:
        return RequestBody(mode="none")

    mode = body.get("mode", "none")

    if mode == "raw":
        content = body.get("raw", "")
        lang = body.get("options", {}).get("raw", {}).get("language", "json")
        content_type_map = {
            "json": "application/json",
            "xml": "application/xml",
            "text": "text/plain",
            "html": "text/html",
            "javascript": "application/javascript",
        }
        return RequestBody(
            mode="raw",
            content=content,
            content_type=content_type_map.get(lang, "text/plain"),
        )

    if mode == "formdata":
        fields = [
            {"key": f["key"], "value": f.get("value", ""), "type": f.get("type", "text")}
            for f in body.get("formdata", [])
            if not f.get("disabled", False)
        ]
        return RequestBody(mode="formdata", content=fields)

    if mode == "urlencoded":
        fields = [
            {"key": f["key"], "value": f.get("value", "")}
            for f in body.get("urlencoded", [])
            if not f.get("disabled", False)
        ]
        return RequestBody(
            mode="urlencoded",
            content=fields,
            content_type="application/x-www-form-urlencoded",
        )

    if mode == "graphql":
        gql = body.get("graphql", {})
        return RequestBody(
            mode="graphql",
            content={"query": gql.get("query", ""), "variables": gql.get("variables", "{}")},
            content_type="application/json",
        )

    if mode == "file":
        src = body.get("file", {}).get("src", "")
        return RequestBody(mode="file", content=src)

    return RequestBody(mode="none")


def _parse_auth(auth: dict | None) -> AuthConfig | None:
    if not auth:
        return None

    auth_type = auth.get("type", "noauth")
    if auth_type == "noauth":
        return None

    params: dict[str, str] = {}
    for item in auth.get(auth_type, []):
        if isinstance(item, dict) and "key" in item:
            params[item["key"]] = item.get("value", "")

    return AuthConfig(type=auth_type, params=params)
