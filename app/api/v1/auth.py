import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import Settings, get_settings
from app.core.rate_limit import enforce_google_auth_rate_limit
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    hash_token,
    verify_google_id_token,
)
from app.db import get_db_session
from app.models.auth import (
    AuthResponse,
    GoogleAuthRequest,
    RefreshToken,
    RefreshTokenRequest,
)
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/google", response_model=AuthResponse)
async def google_auth(
    body: GoogleAuthRequest,
    db_session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    _: None = Depends(enforce_google_auth_rate_limit),
):
    """Authenticate with a Google ID token.

    The mobile app handles the Google sign-in flow and sends the resulting
    ``id_token`` here.  The backend verifies it, creates the user if needed,
    and returns a local JWT for subsequent requests.
    """
    try:
        google_payload = await verify_google_id_token(body.id_token)
    except Exception:
        logger.warning("Google auth failed for token (invalid or rejected)")
        raise

    google_id: str = google_payload["sub"]
    email: str = google_payload.get("email", "")
    full_name: str = google_payload.get("name", "")

    # Look up existing user by Google ID
    statement = select(User).where(User.google_id == google_id)
    result = await db_session.exec(statement)
    user = result.first()

    if user is None:
        user = User(
            email=email,
            full_name=full_name,
            google_id=google_id,
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        logger.info("Google auth succeeded for %s (new user created)", email)
    else:
        logger.info("Google auth succeeded for %s (existing user)", email)

    access_token = create_access_token(user.id, settings)
    refresh_token_id = uuid4()
    refresh_token = create_refresh_token(
        user.id,
        token_id=refresh_token_id,
        settings=settings,
    )

    db_session.add(
        RefreshToken(
            id=refresh_token_id,
            user_id=user.id,
            token_hash=hash_token(refresh_token),
            issued_at=datetime.now(UTC).replace(tzinfo=None),
            expires_at=(
                datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days)
            ).replace(tzinfo=None),
        )
    )
    await db_session.commit()

    return AuthResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user_id=user.id,
    )


@router.post("/refresh", response_model=AuthResponse)
async def refresh_auth_token(
    body: RefreshTokenRequest,
    db_session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
):
    payload = decode_refresh_token(body.refresh_token, settings)
    user_id = UUID(payload["sub"])

    token_hash = hash_token(body.refresh_token)
    stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    token_row = (await db_session.exec(stmt)).first()

    now = datetime.now(UTC).replace(tzinfo=None)
    if token_row is None or token_row.revoked_at is not None or token_row.expires_at < now:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    user = await db_session.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    token_row.revoked_at = now
    db_session.add(token_row)

    new_refresh_id = uuid4()
    new_refresh_token = create_refresh_token(
        user_id,
        token_id=new_refresh_id,
        settings=settings,
    )

    db_session.add(
        RefreshToken(
            id=new_refresh_id,
            user_id=user_id,
            token_hash=hash_token(new_refresh_token),
            issued_at=now,
            expires_at=(
                datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days)
            ).replace(tzinfo=None),
        )
    )

    await db_session.commit()

    return AuthResponse(
        access_token=create_access_token(user_id, settings),
        refresh_token=new_refresh_token,
        user_id=user_id,
    )
