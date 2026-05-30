from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from overload.collection.models import AuthConfig
from overload.collection.variables import VariableContext
from overload.engine.auth import _TOKEN_CACHE, clear_token_cache, fetch_oauth2_token


def _make_token_response(
    access_token: str = "test-token",
    expires_in: int = 3600,
    token_type: str = "Bearer",
) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "access_token": access_token,
        "expires_in": expires_in,
        "token_type": token_type,
    }
    resp.status_code = 200
    return resp


def _oauth2_auth(
    token_url: str = "https://auth.example.com/token",
    client_id: str = "cid",
    client_secret: str = "csecret",
    scope: str = "",
) -> AuthConfig:
    params = {
        "accessTokenUrl": token_url,
        "clientId": client_id,
        "clientSecret": client_secret,
    }
    if scope:
        params["scope"] = scope
    return AuthConfig(type="oauth2", params=params)


@pytest.fixture(autouse=True)
def reset_cache():
    clear_token_cache()
    yield
    clear_token_cache()


class TestFetchOAuth2Token:
    @pytest.mark.asyncio
    async def test_successful_token_fetch(self) -> None:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=_make_token_response("tok-abc"))

        auth = _oauth2_auth()
        token = await fetch_oauth2_token(auth, VariableContext(), mock_client)

        assert token == "tok-abc"
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "https://auth.example.com/token"
        assert call_args[1]["data"]["grant_type"] == "client_credentials"
        assert call_args[1]["data"]["client_id"] == "cid"
        assert call_args[1]["data"]["client_secret"] == "csecret"

    @pytest.mark.asyncio
    async def test_scope_included_when_set(self) -> None:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=_make_token_response())

        auth = _oauth2_auth(scope="read write")
        await fetch_oauth2_token(auth, VariableContext(), mock_client)

        call_data = mock_client.post.call_args[1]["data"]
        assert call_data["scope"] == "read write"

    @pytest.mark.asyncio
    async def test_scope_omitted_when_empty(self) -> None:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=_make_token_response())

        auth = _oauth2_auth(scope="")
        await fetch_oauth2_token(auth, VariableContext(), mock_client)

        call_data = mock_client.post.call_args[1]["data"]
        assert "scope" not in call_data

    @pytest.mark.asyncio
    async def test_missing_token_url_raises(self) -> None:
        mock_client = AsyncMock()
        auth = AuthConfig(type="oauth2", params={"clientId": "cid"})
        with pytest.raises(ValueError, match="accessTokenUrl"):
            await fetch_oauth2_token(auth, VariableContext(), mock_client)

    @pytest.mark.asyncio
    async def test_missing_access_token_in_response_raises(self) -> None:
        import httpx

        mock_client = AsyncMock()
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"error": "invalid_client"}
        mock_client.post = AsyncMock(return_value=resp)

        auth = _oauth2_auth()
        with pytest.raises(RuntimeError, match="access_token"):
            await fetch_oauth2_token(auth, VariableContext(), mock_client)

    @pytest.mark.asyncio
    async def test_http_error_raises(self) -> None:
        import httpx

        mock_client = AsyncMock()
        error_response = MagicMock()
        error_response.status_code = 401
        error_response.text = "Unauthorized"
        exc = httpx.HTTPStatusError("401", request=MagicMock(), response=error_response)
        resp = MagicMock()
        resp.raise_for_status = MagicMock(side_effect=exc)
        mock_client.post = AsyncMock(return_value=resp)

        auth = _oauth2_auth()
        with pytest.raises(RuntimeError, match="401"):
            await fetch_oauth2_token(auth, VariableContext(), mock_client)

    @pytest.mark.asyncio
    async def test_token_is_cached(self) -> None:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=_make_token_response("cached-tok", expires_in=3600))

        auth = _oauth2_auth()
        ctx = VariableContext()

        token1 = await fetch_oauth2_token(auth, ctx, mock_client)
        token2 = await fetch_oauth2_token(auth, ctx, mock_client)

        assert token1 == token2 == "cached-tok"
        assert mock_client.post.call_count == 1

    @pytest.mark.asyncio
    async def test_expired_cache_refetches(self) -> None:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=_make_token_response("new-tok"))

        auth = _oauth2_auth()
        cache_key = "cid:https://auth.example.com/token"
        from overload.engine.auth import _CachedToken
        _TOKEN_CACHE[cache_key] = _CachedToken(token="old-tok", expires_at=time.time() - 1)

        token = await fetch_oauth2_token(auth, VariableContext(), mock_client)

        assert token == "new-tok"
        mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_variable_resolution_in_params(self) -> None:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=_make_token_response("resolved-tok"))

        ctx = VariableContext(runtime_vars={
            "token_url": "https://auth.example.com/token",
            "my_client_id": "real-client",
            "my_secret": "real-secret",
        })
        auth = AuthConfig(type="oauth2", params={
            "accessTokenUrl": "{{token_url}}",
            "clientId": "{{my_client_id}}",
            "clientSecret": "{{my_secret}}",
        })

        token = await fetch_oauth2_token(auth, ctx, mock_client)
        assert token == "resolved-tok"

        call_data = mock_client.post.call_args[1]["data"]
        assert call_data["client_id"] == "real-client"
        assert call_data["client_secret"] == "real-secret"

    @pytest.mark.asyncio
    async def test_alternate_key_names(self) -> None:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=_make_token_response("alt-tok"))

        auth = AuthConfig(type="oauth2", params={
            "access_token_url": "https://auth.example.com/token",
            "client_id": "cid",
            "client_secret": "csecret",
        })
        token = await fetch_oauth2_token(auth, VariableContext(), mock_client)
        assert token == "alt-tok"


class TestPrepareCollectionAuth:
    @pytest.mark.asyncio
    async def test_injects_token_into_context(self) -> None:
        from overload.engine.http_client import HttpClient

        mock_resp = _make_token_response("injected-token")
        instance = MagicMock()
        instance.aclose = AsyncMock()
        instance.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=instance):
            async with HttpClient() as client:
                ctx = VariableContext()
                auth = _oauth2_auth()
                await client.prepare_collection_auth(auth, ctx)

        assert ctx.resolve("{{_oauth2_access_token}}") == "injected-token"

    @pytest.mark.asyncio
    async def test_no_op_for_non_oauth2(self) -> None:
        from overload.engine.http_client import HttpClient

        instance = MagicMock()
        instance.aclose = AsyncMock()
        instance.post = AsyncMock()

        with patch("httpx.AsyncClient", return_value=instance):
            async with HttpClient() as client:
                ctx = VariableContext()
                auth = AuthConfig(type="bearer", params={"token": "tok"})
                await client.prepare_collection_auth(auth, ctx)

        instance.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_op_for_none_auth(self) -> None:
        from overload.engine.http_client import HttpClient

        instance = MagicMock()
        instance.aclose = AsyncMock()
        instance.post = AsyncMock()

        with patch("httpx.AsyncClient", return_value=instance):
            async with HttpClient() as client:
                ctx = VariableContext()
                await client.prepare_collection_auth(None, ctx)

        instance.post.assert_not_called()
