from __future__ import annotations

import json

import pytest

from overload.collection.parser import parse_collection


MINIMAL_COLLECTION = {
    "info": {
        "name": "Test Collection",
        "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
    },
    "item": [
        {
            "name": "Get Users",
            "request": {
                "method": "GET",
                "url": {"raw": "https://api.example.com/users", "host": ["api", "example", "com"], "path": ["users"]},
            },
        }
    ],
}


class TestParseCollection:
    def test_parse_from_dict(self) -> None:
        coll = parse_collection(MINIMAL_COLLECTION)
        assert coll.name == "Test Collection"
        assert len(coll.requests) == 1
        assert coll.requests[0].name == "Get Users"
        assert coll.requests[0].method == "GET"

    def test_parse_from_file(self, tmp_path) -> None:
        path = tmp_path / "test.json"
        path.write_text(json.dumps(MINIMAL_COLLECTION))
        coll = parse_collection(str(path))
        assert coll.name == "Test Collection"
        assert len(coll.requests) == 1

    def test_file_not_found(self) -> None:
        with pytest.raises(FileNotFoundError):
            parse_collection("/nonexistent/path.json")

    def test_nested_folders(self) -> None:
        data = {
            "info": {"name": "Nested", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
            "item": [
                {
                    "name": "Folder A",
                    "item": [
                        {"name": "Req 1", "request": {"method": "GET", "url": "https://a.com/1"}},
                        {
                            "name": "Subfolder",
                            "item": [
                                {"name": "Req 2", "request": {"method": "POST", "url": "https://a.com/2"}},
                            ],
                        },
                    ],
                }
            ],
        }
        coll = parse_collection(data)
        assert len(coll.requests) == 2
        assert coll.requests[0].folder_path == ["Folder A"]
        assert coll.requests[1].folder_path == ["Folder A", "Subfolder"]

    def test_collection_variables(self) -> None:
        data = {
            **MINIMAL_COLLECTION,
            "variable": [
                {"key": "base_url", "value": "https://api.example.com", "type": "string"},
                {"key": "token", "value": "abc123"},
            ],
        }
        coll = parse_collection(data)
        assert len(coll.variables) == 2
        assert coll.variables[0].key == "base_url"

    def test_request_with_headers(self) -> None:
        data = {
            "info": {"name": "Headers", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
            "item": [
                {
                    "name": "With Headers",
                    "request": {
                        "method": "POST",
                        "url": "https://api.com/data",
                        "header": [
                            {"key": "Content-Type", "value": "application/json"},
                            {"key": "Disabled", "value": "skip", "disabled": True},
                        ],
                    },
                }
            ],
        }
        coll = parse_collection(data)
        assert "Content-Type" in coll.requests[0].headers
        assert "Disabled" not in coll.requests[0].headers

    def test_request_with_body_raw(self) -> None:
        data = {
            "info": {"name": "Body", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
            "item": [
                {
                    "name": "POST",
                    "request": {
                        "method": "POST",
                        "url": "https://api.com/data",
                        "body": {
                            "mode": "raw",
                            "raw": '{"name": "test"}',
                            "options": {"raw": {"language": "json"}},
                        },
                    },
                }
            ],
        }
        coll = parse_collection(data)
        assert coll.requests[0].body.mode == "raw"
        assert coll.requests[0].body.content_type == "application/json"

    def test_auth_inheritance(self) -> None:
        data = {
            "info": {"name": "Auth", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
            "auth": {
                "type": "bearer",
                "bearer": [{"key": "token", "value": "collection-token"}],
            },
            "item": [
                {
                    "name": "Inherits",
                    "request": {"method": "GET", "url": "https://api.com/a"},
                },
                {
                    "name": "Overrides",
                    "request": {
                        "method": "GET",
                        "url": "https://api.com/b",
                        "auth": {
                            "type": "basic",
                            "basic": [
                                {"key": "username", "value": "user"},
                                {"key": "password", "value": "pass"},
                            ],
                        },
                    },
                },
            ],
        }
        coll = parse_collection(data)
        assert coll.requests[0].auth.type == "bearer"
        assert coll.requests[0].auth.params["token"] == "collection-token"
        assert coll.requests[1].auth.type == "basic"

    def test_query_params(self) -> None:
        data = {
            "info": {"name": "QP", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
            "item": [
                {
                    "name": "Query",
                    "request": {
                        "method": "GET",
                        "url": {
                            "raw": "https://api.com/search?q=test&page=1",
                            "query": [
                                {"key": "q", "value": "test"},
                                {"key": "page", "value": "1"},
                                {"key": "disabled", "value": "skip", "disabled": True},
                            ],
                        },
                    },
                }
            ],
        }
        coll = parse_collection(data)
        qp = coll.requests[0].query_params
        assert len(qp) == 3
        assert qp[0].key == "q"
        assert qp[2].disabled is True

    def test_string_url_request(self) -> None:
        data = {
            "info": {"name": "StrReq", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
            "item": [
                {"name": "Simple", "request": "https://api.com/simple"},
            ],
        }
        coll = parse_collection(data)
        assert coll.requests[0].method == "GET"
        assert coll.requests[0].url_raw == "https://api.com/simple"

    def test_to_dict_roundtrip(self) -> None:
        coll = parse_collection(MINIMAL_COLLECTION)
        d = coll.to_dict()
        assert d["name"] == "Test Collection"
        assert len(d["requests"]) == 1
        assert d["requests"][0]["method"] == "GET"
