from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlmodel import select

from app.api.v1 import auth as auth_api
from app.core.config import get_settings
from app.core.rate_limit import _google_auth_rate_limiter
from app.core.security import create_refresh_token, hash_token, verify_password
from app.models.auth import PasswordResetToken, RefreshToken
from app.models.user import User, UserRole


@pytest.fixture(autouse=True)
def _reset_google_auth_rate_limiter():
    """The Google auth limiter is process-wide in-memory state. Reset between
    tests so accumulated hits do not leak across cases."""
    _google_auth_rate_limiter.reset()
    yield
    _google_auth_rate_limiter.reset()


@pytest.mark.asyncio
async def test_register_creates_user_with_hashed_password(client, db_session):
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "NewUser@Test.com",
            "password": "StrongPass123",
            "full_name": "  New User  ",
        },
    )

    assert resp.status_code == 201
    data = resp.json()
    assert data["access_token"]
    assert data["refresh_token"]
    assert "hashed_password" not in data

    user = (
        await db_session.exec(select(User).where(User.email == "newuser@test.com"))
    ).first()
    assert user is not None
    assert user.full_name == "New User"
    assert user.hashed_password is not None
    assert user.hashed_password != "StrongPass123"
    assert verify_password("StrongPass123", user.hashed_password) is True


@pytest.mark.asyncio
async def test_register_requires_full_name(client):
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "noname@test.com", "password": "StrongPass123"},
    )
    assert resp.status_code == 422

    resp_blank = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "blank@test.com",
            "password": "StrongPass123",
            "full_name": "   ",
        },
    )
    assert resp_blank.status_code == 422


@pytest.mark.asyncio
async def test_register_rejects_existing_user(client, db_session):
    existing_user = User(
        email="exists@test.com",
        hashed_password="already-hashed",
        role=UserRole.USER,
    )
    db_session.add(existing_user)
    await db_session.commit()

    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "exists@test.com",
            "password": "StrongPass123",
            "full_name": "Existing Person",
        },
    )

    assert resp.status_code == 409
    assert resp.json()["detail"] == "User already exists"


@pytest.mark.asyncio
async def test_register_validates_password_format(client):
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "format@test.com",
            "password": "short",
            "full_name": "Format User",
        },
    )

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_login_returns_tokens_for_native_user(client, db_session):
    user = User(
        email="native@test.com",
        hashed_password=auth_api.hash_password("StrongPass123"),
        role=UserRole.USER,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "native@test.com", "password": "StrongPass123"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["user_id"] == str(user.id)


@pytest.mark.asyncio
async def test_login_rejects_invalid_credentials(client, db_session):
    user = User(
        email="native@test.com",
        hashed_password=auth_api.hash_password("StrongPass123"),
        role=UserRole.USER,
    )
    db_session.add(user)
    await db_session.commit()

    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "native@test.com", "password": "WrongPass123"},
    )

    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid credentials"


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
        await db_session.exec(
            select(RefreshToken).where(RefreshToken.id == original_id)
        )
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

    monkeypatch.setattr(
        auth_api, "verify_google_id_token", _fake_verify_google_id_token
    )

    statuses = []
    for _ in range(6):
        resp = await client.post(
            "/api/v1/auth/google",
            json={"id_token": "fake-token"},
        )
        statuses.append(resp.status_code)

    assert statuses[:5] == [200, 200, 200, 200, 200]
    assert statuses[5] == 429


# --- /auth/google flows -----------------------------------------------------


def _stub_google_verifier(monkeypatch, payload: dict) -> None:
    async def _fake(_token: str) -> dict:
        return payload

    monkeypatch.setattr(auth_api, "verify_google_id_token", _fake)


@pytest.mark.asyncio
async def test_google_auth_creates_new_user_on_first_login(
    client, db_session, monkeypatch
):
    _stub_google_verifier(
        monkeypatch,
        {
            "sub": "google-new-user",
            "email": "new@test.com",
            "name": "New User",
        },
    )

    resp = await client.post(
        "/api/v1/auth/google", json={"id_token": "fake-token"}
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["access_token"]
    assert data["refresh_token"]

    user = (
        await db_session.exec(select(User).where(User.email == "new@test.com"))
    ).first()
    assert user is not None
    assert user.google_id == "google-new-user"
    assert user.full_name == "New User"
    assert user.hashed_password is None


@pytest.mark.asyncio
async def test_google_auth_returns_existing_user_by_google_id(
    client, db_session, monkeypatch
):
    existing = User(
        email="existing@test.com",
        full_name="Existing User",
        google_id="google-existing-id",
        role=UserRole.USER,
    )
    db_session.add(existing)
    await db_session.commit()
    await db_session.refresh(existing)

    _stub_google_verifier(
        monkeypatch,
        {
            "sub": "google-existing-id",
            "email": "existing@test.com",
            "name": "Existing User",
        },
    )

    resp = await client.post(
        "/api/v1/auth/google", json={"id_token": "fake-token"}
    )

    assert resp.status_code == 200
    assert resp.json()["user_id"] == str(existing.id)

    rows = (
        await db_session.exec(select(User).where(User.email == "existing@test.com"))
    ).all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_google_auth_links_existing_email_account(
    client, db_session, monkeypatch
):
    """A user previously registered natively (email/password, no google_id)
    must get linked to their Google identity on first Google login."""
    native_user = User(
        email="native@test.com",
        full_name="",
        hashed_password=auth_api.hash_password("StrongPass123"),
        role=UserRole.USER,
    )
    db_session.add(native_user)
    await db_session.commit()
    await db_session.refresh(native_user)

    _stub_google_verifier(
        monkeypatch,
        {
            "sub": "google-link-id",
            "email": "native@test.com",
            "name": "Linked Name",
        },
    )

    resp = await client.post(
        "/api/v1/auth/google", json={"id_token": "fake-token"}
    )

    assert resp.status_code == 200
    assert resp.json()["user_id"] == str(native_user.id)

    await db_session.refresh(native_user)
    assert native_user.google_id == "google-link-id"
    assert native_user.full_name == "Linked Name"
    # hashed_password must be preserved — a bug that wipes it would silently
    # block the user from their native login.
    assert native_user.hashed_password is not None
    assert verify_password("StrongPass123", native_user.hashed_password)


@pytest.mark.asyncio
async def test_google_auth_rejects_email_collision_with_other_google_id(
    client, db_session, monkeypatch
):
    """If email is already attached to a different google_id, refuse the
    login with 409 — never silently re-bind the account."""
    existing = User(
        email="conflict@test.com",
        full_name="Conflict User",
        google_id="google-original-id",
        role=UserRole.USER,
    )
    db_session.add(existing)
    await db_session.commit()

    _stub_google_verifier(
        monkeypatch,
        {
            "sub": "google-imposter-id",
            "email": "conflict@test.com",
            "name": "Conflict User",
        },
    )

    resp = await client.post(
        "/api/v1/auth/google", json={"id_token": "fake-token"}
    )

    assert resp.status_code == 409
    assert resp.json()["detail"] == "Account already linked to another Google identity"


@pytest.mark.asyncio
async def test_google_auth_normalizes_email_case(
    client, db_session, monkeypatch
):
    """Google may return mixed-case emails. They must be normalized to
    lowercase before lookup/storage so two casings cannot create duplicate
    accounts."""
    _stub_google_verifier(
        monkeypatch,
        {
            "sub": "google-case-id",
            "email": "MixedCase@Test.com",
            "name": "Case User",
        },
    )

    resp = await client.post(
        "/api/v1/auth/google", json={"id_token": "fake-token"}
    )
    assert resp.status_code == 200

    user = (
        await db_session.exec(
            select(User).where(User.google_id == "google-case-id")
        )
    ).first()
    assert user is not None
    assert user.email == "mixedcase@test.com"


@pytest.mark.asyncio
async def test_google_auth_finds_existing_user_by_normalized_email(
    client, db_session, monkeypatch
):
    """Most dangerous normalization regression: an existing native user has a
    lowercase email; Google returns the same address in mixed case. Without
    normalization the email-fallback lookup would miss the existing user and
    create a duplicate account with a duplicate email unique-constraint error
    (or a silent second row if the constraint were ever dropped)."""
    native = User(
        email="mixedcase@test.com",
        hashed_password=auth_api.hash_password("SomePass1"),
        role=UserRole.USER,
    )
    db_session.add(native)
    await db_session.commit()
    await db_session.refresh(native)

    _stub_google_verifier(
        monkeypatch,
        {
            "sub": "google-dedup-id",
            "email": "MixedCase@Test.com",
            "name": "Case User",
        },
    )

    resp = await client.post(
        "/api/v1/auth/google", json={"id_token": "fake-token"}
    )
    assert resp.status_code == 200
    assert resp.json()["user_id"] == str(native.id)

    all_rows = (
        await db_session.exec(select(User).where(User.email == "mixedcase@test.com"))
    ).all()
    assert len(all_rows) == 1


@pytest.mark.asyncio
async def test_google_auth_propagates_verifier_failure_as_401(
    client, monkeypatch
):
    """If verify_google_id_token raises (invalid token, network error, etc.)
    the endpoint must not crash with 500 — it must surface the 401 the
    verifier already raises."""
    from fastapi import HTTPException, status as http_status

    async def _fake_fail(_token: str) -> dict:
        raise HTTPException(
            status_code=http_status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Google ID token",
        )

    monkeypatch.setattr(auth_api, "verify_google_id_token", _fake_fail)

    resp = await client.post(
        "/api/v1/auth/google", json={"id_token": "rubbish"}
    )

    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid Google ID token"


# --- password reset ----------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_password_reset_rate_limiter():
    from app.core.rate_limit import _password_reset_rate_limiter

    _password_reset_rate_limiter.reset()
    yield
    _password_reset_rate_limiter.reset()


def _capture_reset_emails(monkeypatch) -> list[dict]:
    """Stub EmailService.send_password_reset and record the calls."""
    sent: list[dict] = []

    async def _fake(self, *, to: str, reset_url: str) -> None:
        sent.append({"to": to, "reset_url": reset_url})

    monkeypatch.setattr(
        "app.api.v1.auth.EmailService.send_password_reset", _fake
    )
    return sent


@pytest.mark.asyncio
async def test_forgot_password_creates_token_and_sends_email(
    client, db_session, monkeypatch
):
    sent = _capture_reset_emails(monkeypatch)
    user = User(
        email="reset@test.com",
        full_name="Reset User",
        hashed_password=auth_api.hash_password("StrongPass123"),
        role=UserRole.USER,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    resp = await client.post(
        "/api/v1/auth/forgot-password",
        json={"email": "Reset@Test.com"},
    )

    assert resp.status_code == 202
    assert len(sent) == 1
    assert sent[0]["to"] == "reset@test.com"
    assert "token=" in sent[0]["reset_url"]

    rows = (
        await db_session.exec(
            select(PasswordResetToken).where(PasswordResetToken.user_id == user.id)
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].used_at is None


@pytest.mark.asyncio
async def test_forgot_password_unknown_email_is_silent(
    client, db_session, monkeypatch
):
    sent = _capture_reset_emails(monkeypatch)

    resp = await client.post(
        "/api/v1/auth/forgot-password",
        json={"email": "nobody@test.com"},
    )

    assert resp.status_code == 202
    assert sent == []
    rows = (await db_session.exec(select(PasswordResetToken))).all()
    assert rows == []


@pytest.mark.asyncio
async def test_forgot_password_google_only_account_is_silent(
    client, db_session, monkeypatch
):
    sent = _capture_reset_emails(monkeypatch)
    user = User(
        email="googleonly@test.com",
        full_name="Google User",
        google_id="google-only-id",
        role=UserRole.USER,
    )
    db_session.add(user)
    await db_session.commit()

    resp = await client.post(
        "/api/v1/auth/forgot-password",
        json={"email": "googleonly@test.com"},
    )

    assert resp.status_code == 202
    assert sent == []
    rows = (await db_session.exec(select(PasswordResetToken))).all()
    assert rows == []


@pytest.mark.asyncio
async def test_reset_password_updates_password_and_revokes_sessions(
    client, db_session
):
    user = User(
        email="resetflow@test.com",
        full_name="Reset Flow",
        hashed_password=auth_api.hash_password("OldPass123"),
        role=UserRole.USER,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    # An active refresh token that must be revoked by the reset.
    refresh_id = uuid4()
    refresh = create_refresh_token(user.id, token_id=refresh_id, settings=get_settings())
    db_session.add(
        RefreshToken(
            id=refresh_id,
            user_id=user.id,
            token_hash=hash_token(refresh),
            issued_at=datetime.now(UTC).replace(tzinfo=None),
            expires_at=(datetime.now(UTC) + timedelta(days=30)).replace(tzinfo=None),
        )
    )

    raw_token = "valid-reset-token"
    db_session.add(
        PasswordResetToken(
            id=uuid4(),
            user_id=user.id,
            token_hash=hash_token(raw_token),
            created_at=datetime.now(UTC).replace(tzinfo=None),
            expires_at=(datetime.now(UTC) + timedelta(minutes=60)).replace(tzinfo=None),
        )
    )
    await db_session.commit()

    resp = await client.post(
        "/api/v1/auth/reset-password",
        json={"token": raw_token, "password": "BrandNew123"},
    )

    assert resp.status_code == 200
    assert resp.json()["access_token"]

    await db_session.refresh(user)
    assert verify_password("BrandNew123", user.hashed_password)
    assert not verify_password("OldPass123", user.hashed_password)

    used = (
        await db_session.exec(
            select(PasswordResetToken).where(
                PasswordResetToken.token_hash == hash_token(raw_token)
            )
        )
    ).first()
    assert used is not None and used.used_at is not None

    revoked = (
        await db_session.exec(
            select(RefreshToken).where(RefreshToken.id == refresh_id)
        )
    ).first()
    assert revoked is not None and revoked.revoked_at is not None


@pytest.mark.asyncio
async def test_reset_password_rejects_invalid_token(client):
    resp = await client.post(
        "/api/v1/auth/reset-password",
        json={"token": "does-not-exist", "password": "BrandNew123"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_reset_password_rejects_expired_token(client, db_session):
    user = User(
        email="expired@test.com",
        full_name="Expired User",
        hashed_password=auth_api.hash_password("OldPass123"),
        role=UserRole.USER,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    raw_token = "expired-reset-token"
    db_session.add(
        PasswordResetToken(
            id=uuid4(),
            user_id=user.id,
            token_hash=hash_token(raw_token),
            created_at=(datetime.now(UTC) - timedelta(hours=2)).replace(tzinfo=None),
            expires_at=(datetime.now(UTC) - timedelta(hours=1)).replace(tzinfo=None),
        )
    )
    await db_session.commit()

    resp = await client.post(
        "/api/v1/auth/reset-password",
        json={"token": raw_token, "password": "BrandNew123"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_reset_password_rejects_already_used_token(client, db_session):
    user = User(
        email="used@test.com",
        full_name="Used User",
        hashed_password=auth_api.hash_password("OldPass123"),
        role=UserRole.USER,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    raw_token = "used-reset-token"
    db_session.add(
        PasswordResetToken(
            id=uuid4(),
            user_id=user.id,
            token_hash=hash_token(raw_token),
            created_at=datetime.now(UTC).replace(tzinfo=None),
            expires_at=(datetime.now(UTC) + timedelta(minutes=60)).replace(tzinfo=None),
            used_at=datetime.now(UTC).replace(tzinfo=None),
        )
    )
    await db_session.commit()

    resp = await client.post(
        "/api/v1/auth/reset-password",
        json={"token": raw_token, "password": "BrandNew123"},
    )
    assert resp.status_code == 400
