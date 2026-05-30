from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx

from overload.collection.models import AuthConfig
from overload.collection.variables import VariableContext

logger = logging.getLogger(__name__)


@dataclass
class _CachedToken:
    token: str
    expires_at: float


_TOKEN_CACHE: dict[str, _CachedToken] = {}


async def fetch_oauth2_token(
    auth: AuthConfig,
    ctx: VariableContext,
    client: httpx.AsyncClient,
) -> str:
    params = auth.params

    # Postman uses "accessTokenUrl"; some environments expose it as "access_token_url"
    token_url = ctx.resolve(
        params.get("accessTokenUrl")
        or params.get("access_token_url")
        or params.get("tokenUrl")
        or ""
    )
    client_id = ctx.resolve(params.get("clientId") or params.get("client_id") or "")
    client_secret = ctx.resolve(params.get("clientSecret") or params.get("client_secret") or "")
    scope = ctx.resolve(params.get("scope") or "")

    if not token_url:
        raise ValueError("OAuth2 auth: accessTokenUrl is required but missing")

    cache_key = f"{client_id}:{token_url}"
    cached = _TOKEN_CACHE.get(cache_key)
    if cached and cached.expires_at > time.time() + 30:
        logger.debug("OAuth2: using cached token for client_id=%s", client_id)
        return cached.token

    logger.info("OAuth2: fetching token from %s (client_id=%s)", token_url, client_id)

    post_data: dict[str, str] = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }
    if scope:
        post_data["scope"] = scope

    try:
        response = await client.post(token_url, data=post_data)
        response.raise_for_status()
        body = response.json()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"OAuth2 token request failed: {exc.response.status_code} — {exc.response.text}"
        ) from exc
    except Exception as exc:
        raise RuntimeError(f"OAuth2 token request failed: {exc}") from exc

    access_token: str | None = body.get("access_token")
    if not access_token:
        raise RuntimeError(f"OAuth2 response missing 'access_token' field: {body}")

    expires_in = int(body.get("expires_in", 3600))
    _TOKEN_CACHE[cache_key] = _CachedToken(
        token=access_token,
        expires_at=time.time() + expires_in,
    )

    logger.info("OAuth2: token acquired, expires in %ds", expires_in)
    return access_token


def clear_token_cache() -> None:
    _TOKEN_CACHE.clear()
