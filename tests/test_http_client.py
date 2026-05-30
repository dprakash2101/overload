from __future__ import annotations

from overload.collection.models import AuthConfig
from overload.collection.variables import VariableContext
from overload.engine.http_client import HttpClient


class TestApplyAuth:
    def _client(self) -> HttpClient:
        return HttpClient()

    def test_bearer_auth(self) -> None:
        c = self._client()
        headers: dict[str, str] = {}
        auth = AuthConfig(type="bearer", params={"token": "my-token"})
        c._apply_auth(auth, headers, VariableContext())
        assert headers["Authorization"] == "Bearer my-token"

    def test_basic_auth(self) -> None:
        import base64

        c = self._client()
        headers: dict[str, str] = {}
        auth = AuthConfig(type="basic", params={"username": "user", "password": "pass"})
        c._apply_auth(auth, headers, VariableContext())
        expected = base64.b64encode(b"user:pass").decode()
        assert headers["Authorization"] == f"Basic {expected}"

    def test_apikey_header(self) -> None:
        c = self._client()
        headers: dict[str, str] = {}
        auth = AuthConfig(type="apikey", params={"key": "X-Api-Key", "value": "abc123", "in": "header"})
        c._apply_auth(auth, headers, VariableContext())
        assert headers["X-Api-Key"] == "abc123"

    def test_apikey_query(self) -> None:
        c = self._client()
        headers: dict[str, str] = {}
        query: dict[str, str] = {}
        auth = AuthConfig(type="apikey", params={"key": "api_key", "value": "abc123", "in": "query"})
        c._apply_auth(auth, headers, VariableContext(), query)
        assert "api_key" not in headers
        assert query["api_key"] == "abc123"

    def test_apikey_query_no_dict(self) -> None:
        c = self._client()
        headers: dict[str, str] = {}
        auth = AuthConfig(type="apikey", params={"key": "api_key", "value": "abc123", "in": "query"})
        c._apply_auth(auth, headers, VariableContext())
        assert "api_key" not in headers

    def test_no_auth(self) -> None:
        c = self._client()
        headers: dict[str, str] = {}
        c._apply_auth(None, headers, VariableContext())
        assert headers == {}

    def test_unsupported_auth_type(self) -> None:
        c = self._client()
        headers: dict[str, str] = {}
        auth = AuthConfig(type="ntlm", params={"username": "user"})
        c._apply_auth(auth, headers, VariableContext())
        assert "Authorization" not in headers

    def test_oauth2_with_token_in_context(self) -> None:
        c = self._client()
        headers: dict[str, str] = {}
        ctx = VariableContext(runtime_vars={"_oauth2_access_token": "my-oauth-token"})
        auth = AuthConfig(type="oauth2", params={})
        c._apply_auth(auth, headers, ctx)
        assert headers["Authorization"] == "Bearer my-oauth-token"

    def test_oauth2_without_token_in_context(self) -> None:
        c = self._client()
        headers: dict[str, str] = {}
        auth = AuthConfig(type="oauth2", params={})
        c._apply_auth(auth, headers, VariableContext())
        assert "Authorization" not in headers

    def test_variable_resolution_in_auth(self) -> None:
        c = self._client()
        headers: dict[str, str] = {}
        ctx = VariableContext(runtime_vars={"my_token": "resolved-token"})
        auth = AuthConfig(type="bearer", params={"token": "{{my_token}}"})
        c._apply_auth(auth, headers, ctx)
        assert headers["Authorization"] == "Bearer resolved-token"
