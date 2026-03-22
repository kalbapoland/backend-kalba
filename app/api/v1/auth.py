import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.security import create_access_token, create_refresh_token, decode_refresh_token, verify_google_id_token
from app.db import get_db_session
from app.models.auth import AuthResponse, GoogleAuthRequest, RefreshRequest
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/google", response_model=AuthResponse)
async def google_auth(
    body: GoogleAuthRequest,
    db_session: AsyncSession = Depends(get_db_session),
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

    access_token = create_access_token(user.id)
    refresh_token = create_refresh_token(user.id)
    return AuthResponse(access_token=access_token, refresh_token=refresh_token, user_id=user.id)


@router.post("/refresh", response_model=AuthResponse)
async def refresh_token(
    body: RefreshRequest,
    db_session: AsyncSession = Depends(get_db_session),
):
    """Exchange a valid refresh token for a new access + refresh token pair."""
    from uuid import UUID

    payload = decode_refresh_token(body.refresh_token)
    user_id = UUID(payload["sub"])

    user = await db_session.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    access_token = create_access_token(user_id)
    new_refresh_token = create_refresh_token(user_id)
    logger.info("Tokens refreshed for user %s", user_id)
    return AuthResponse(access_token=access_token, refresh_token=new_refresh_token, user_id=user_id)
