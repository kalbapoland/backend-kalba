from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlmodel import select

from app.api.v1 import auth as auth_api
from app.core.config import get_settings
from app.core.security import create_refresh_token, hash_token
from app.models.auth import RefreshToken
from app.models.user import User, UserRole


@pytest.mark.asyncio
async def test_refresh_token_rotates_and_returns_new_tokens(client, db_session):
    user = User(
        email="refresh-user@test.com",
        full_name="Refresh User",
        google_id="refresh-google-id",
        role=UserRole.USER,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    settings = get_settings()
    original_id = uuid4()
    original_refresh = create_refresh_token(
        user.id,
        token_id=original_id,
        settings=settings,
    )
    db_session.add(
        RefreshToken(
            id=original_id,
            user_id=user.id,
            token_hash=hash_token(original_refresh),
            issued_at=datetime.now(UTC).replace(tzinfo=None),
            expires_at=(
                datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days)
            ).replace(tzinfo=None),
        )
    )
    await db_session.commit()

    resp = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": original_refresh},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["refresh_token"] != original_refresh
    assert data["user_id"] == str(user.id)

    old_token = (
        await db_session.exec(select(RefreshToken).where(RefreshToken.id == original_id))
    ).first()
    assert old_token is not None
    assert old_token.revoked_at is not None


@pytest.mark.asyncio
async def test_refresh_endpoint_rejects_invalid_token(client):
    resp = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": "invalid-token"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_google_auth_is_rate_limited(client, monkeypatch):
    async def _fake_verify_google_id_token(_: str) -> dict:
        return {
            "sub": "rate-limited-google-user",
            "email": "rate-limit@test.com",
            "name": "Rate Limit User",
        }

    monkeypatch.setattr(auth_api, "verify_google_id_token", _fake_verify_google_id_token)

    statuses = []
    for _ in range(6):
        resp = await client.post(
            "/api/v1/auth/google",
            json={"id_token": "fake-token"},
        )
        statuses.append(resp.status_code)

    assert statuses[:5] == [200, 200, 200, 200, 200]
    assert statuses[5] == 429
