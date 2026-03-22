from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest

from app.core.config import get_settings
from app.core.security import create_refresh_token, create_access_token
from app.models.user import User, UserRole


@pytest.fixture
async def regular_user_with_token(db_session, client):
    """Create a regular user and return (user, refresh_token)."""
    user = User(
        email="user@test.com",
        full_name="Test User",
        google_id="google-user-999",
        role=UserRole.USER,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    token = create_refresh_token(user.id)
    return user, token


async def test_refresh_returns_new_tokens(client, regular_user_with_token):
    user, refresh_token = regular_user_with_token
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"
    assert data["user_id"] == str(user.id)


async def test_refresh_new_access_token_is_valid(client, regular_user_with_token):
    """The returned access token should be accepted by protected endpoints."""
    user, refresh_token = regular_user_with_token
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert resp.status_code == 200
    new_access_token = resp.json()["access_token"]

    me_resp = await client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {new_access_token}"}
    )
    assert me_resp.status_code == 200


async def test_refresh_with_access_token_returns_401(client, regular_user_with_token):
    """Passing an access token to /auth/refresh must be rejected."""
    user, _ = regular_user_with_token
    access_token = create_access_token(user.id)
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": access_token})
    assert resp.status_code == 401


async def test_refresh_with_invalid_token_returns_401(client):
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": "not.a.real.token"})
    assert resp.status_code == 401


async def test_refresh_with_expired_token_returns_401(client, regular_user_with_token):
    user, _ = regular_user_with_token
    settings = get_settings()
    expired_payload = {
        "sub": str(user.id),
        "exp": datetime.now(UTC) - timedelta(minutes=1),
        "type": "refresh",
    }
    expired_token = jwt.encode(
        expired_payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
    )
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": expired_token})
    assert resp.status_code == 401


async def test_refresh_for_nonexistent_user_returns_401(client):
    """Refresh token with valid signature but unknown user_id must be rejected."""
    settings = get_settings()
    phantom_id = uuid4()
    payload = {
        "sub": str(phantom_id),
        "exp": datetime.now(UTC) + timedelta(days=30),
        "type": "refresh",
    }
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": token})
    assert resp.status_code == 401
