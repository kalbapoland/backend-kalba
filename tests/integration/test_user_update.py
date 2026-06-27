import pytest

from app.core.security import create_access_token
from app.models.user import User, UserRole


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _make_user(db_session, email: str, full_name: str) -> User:
    user = User(email=email, full_name=full_name, hashed_password="hashed", role=UserRole.USER)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.mark.asyncio
async def test_patch_me_updates_full_name(client, db_session):
    user = await _make_user(db_session, "updateme@test.com", "Original Name")
    token = create_access_token(user.id)

    resp = await client.patch(
        "/api/v1/users/me",
        json={"full_name": "Updated Name"},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["full_name"] == "Updated Name"
    assert data["email"] == "updateme@test.com"

    db_session.expunge_all()
    refreshed = await db_session.get(User, user.id)
    assert refreshed.full_name == "Updated Name"


@pytest.mark.asyncio
async def test_patch_me_trims_whitespace(client, db_session):
    user = await _make_user(db_session, "trimme@test.com", "Old Name")
    token = create_access_token(user.id)

    resp = await client.patch(
        "/api/v1/users/me",
        json={"full_name": "  Trimmed Name  "},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["full_name"] == "Trimmed Name"


@pytest.mark.asyncio
async def test_patch_me_rejects_empty_name(client, db_session):
    user = await _make_user(db_session, "emptyname@test.com", "Has Name")
    token = create_access_token(user.id)

    resp = await client.patch(
        "/api/v1/users/me",
        json={"full_name": "   "},
        headers=_auth(token),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_patch_me_rejects_name_too_long(client, db_session):
    user = await _make_user(db_session, "longname@test.com", "Short")
    token = create_access_token(user.id)

    resp = await client.patch(
        "/api/v1/users/me",
        json={"full_name": "A" * 101},
        headers=_auth(token),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_patch_me_rejects_null_name(client, db_session):
    user = await _make_user(db_session, "nullname@test.com", "Has Name")
    token = create_access_token(user.id)

    resp = await client.patch(
        "/api/v1/users/me",
        json={"full_name": None},
        headers=_auth(token),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_patch_me_empty_body_is_noop(client, db_session):
    user = await _make_user(db_session, "noop@test.com", "Unchanged")
    token = create_access_token(user.id)

    resp = await client.patch("/api/v1/users/me", json={}, headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["full_name"] == "Unchanged"


@pytest.mark.asyncio
async def test_patch_me_requires_auth(client):
    resp = await client.patch("/api/v1/users/me", json={"full_name": "Hacker"})
    assert resp.status_code in (401, 403)
