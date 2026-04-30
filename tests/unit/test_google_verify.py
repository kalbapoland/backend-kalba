"""Unit tests for verify_google_id_token.

Mocks Google's tokeninfo endpoint via httpx.MockTransport so the audience
matching logic is exercised against every supported client ID (web, iOS,
Android) without hitting the network.
"""
from __future__ import annotations

import types
import httpx
import pytest
from fastapi import HTTPException

from app.core import security as security_module
from app.core.config import Settings
from app.core.security import GOOGLE_CERTS_URL


def _make_settings(
    *,
    web: str = "web-client-id.apps.googleusercontent.com",
    ios: str = "ios-client-id.apps.googleusercontent.com",
    android: str = "android-client-id.apps.googleusercontent.com",
) -> Settings:
    return Settings.model_validate(
        {
            "app_env": "local",
            "database_url": "postgresql://localhost/test",
            "jwt_secret_key": "test-secret-min-32-bytes-length-1234",
            "google_client_id": web,
            "google_ios_client_id": ios,
            "google_android_client_id": android,
        }
    )


def _patch_httpx(monkeypatch, *, status_code: int, payload: dict) -> None:
    """Replace httpx.AsyncClient inside the security module with a stub that
    returns a canned response. Patches only the security module's namespace
    rather than the global httpx module, so other concurrent tests are
    unaffected. Also validates the stub is called with the expected URL and
    id_token parameter so a regression that sends the token to the wrong
    endpoint would be caught."""

    response = httpx.Response(status_code=status_code, json=payload)

    class _StubAsyncClient:
        def __init__(self, *_, **__):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def get(self, url, *, params=None):
            assert url == GOOGLE_CERTS_URL, f"Unexpected tokeninfo URL: {url!r}"
            assert params is not None and "id_token" in params, (
                "id_token missing from tokeninfo request params"
            )
            return response

    monkeypatch.setattr(
        security_module,
        "httpx",
        types.SimpleNamespace(AsyncClient=_StubAsyncClient),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "client_kind",
    ["web", "ios", "android"],
)
async def test_verify_google_token_accepts_each_supported_client_id(
    monkeypatch, client_kind
):
    """A token whose `aud` matches the web / iOS / Android client ID must be
    accepted. Catches regressions where any of the three env-bound values
    stops being read."""
    settings = _make_settings()
    aud_for_kind = {
        "web": settings.google_client_id,
        "ios": settings.google_ios_client_id,
        "android": settings.google_android_client_id,
    }
    expected_aud = aud_for_kind[client_kind]

    _patch_httpx(
        monkeypatch,
        status_code=200,
        payload={
            "sub": f"google-{client_kind}-user",
            "email": f"{client_kind}@test.com",
            "name": f"{client_kind.title()} User",
            "aud": expected_aud,
        },
    )

    payload = await security_module.verify_google_id_token(
        "fake-id-token", settings
    )

    assert payload["aud"] == expected_aud
    assert payload["sub"] == f"google-{client_kind}-user"


@pytest.mark.asyncio
async def test_verify_google_token_rejects_unknown_audience(monkeypatch):
    """A token issued for a different OAuth client (e.g. an old, rotated
    Android client ID still in circulation) must be rejected with 401."""
    settings = _make_settings()
    _patch_httpx(
        monkeypatch,
        status_code=200,
        payload={
            "sub": "rogue-user",
            "email": "rogue@test.com",
            "aud": "stranger-client-id.apps.googleusercontent.com",
        },
    )

    with pytest.raises(HTTPException) as exc:
        await security_module.verify_google_id_token("fake-id-token", settings)

    assert exc.value.status_code == 401
    assert exc.value.detail == "Token was not issued for this application"


@pytest.mark.asyncio
async def test_verify_google_token_rejects_non_200_response(monkeypatch):
    """When Google rejects the token (400/401), we must surface 401 — not
    leak Google's status code or proceed with an empty payload."""
    settings = _make_settings()
    _patch_httpx(
        monkeypatch,
        status_code=400,
        payload={"error": "invalid_token"},
    )

    with pytest.raises(HTTPException) as exc:
        await security_module.verify_google_id_token("bad-token", settings)

    assert exc.value.status_code == 401
    assert exc.value.detail == "Invalid Google ID token"


@pytest.mark.asyncio
async def test_verify_google_token_skips_audience_check_when_no_client_ids(
    monkeypatch,
):
    """In local/test setups all three client IDs may be empty. The function
    must not enforce `aud` matching against an empty allowlist (which would
    block every token). Documents the dev-friendliness invariant."""
    settings = _make_settings(web="", ios="", android="")
    _patch_httpx(
        monkeypatch,
        status_code=200,
        payload={
            "sub": "local-dev-user",
            "email": "dev@test.com",
            "aud": "anything-goes",
        },
    )

    payload = await security_module.verify_google_id_token(
        "fake-id-token", settings
    )

    assert payload["sub"] == "local-dev-user"


@pytest.mark.asyncio
async def test_verify_google_token_accepts_when_only_android_configured(
    monkeypatch,
):
    """Edge case: only the Android client ID is set (e.g. mobile-only build).
    Token from Android client must still pass; tokens with empty aud must not."""
    settings = _make_settings(
        web="",
        ios="",
        android="android-client-id.apps.googleusercontent.com",
    )
    _patch_httpx(
        monkeypatch,
        status_code=200,
        payload={
            "sub": "android-only-user",
            "email": "android@test.com",
            "aud": "android-client-id.apps.googleusercontent.com",
        },
    )

    payload = await security_module.verify_google_id_token(
        "fake-id-token", settings
    )

    assert payload["aud"] == "android-client-id.apps.googleusercontent.com"
