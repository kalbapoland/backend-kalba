import logging
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import Settings, get_settings
from app.core.rate_limit import (
    enforce_google_auth_rate_limit,
    enforce_password_reset_rate_limit,
)
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    hash_token,
    hash_password,
    verify_password,
    verify_google_id_token,
)
from app.db import get_db_session
from app.models.auth import (
    AuthResponse,
    ForgotPasswordRequest,
    GoogleAuthRequest,
    LoginRequest,
    PasswordResetToken,
    RegisterRequest,
    RefreshToken,
    RefreshTokenRequest,
    ResetPasswordRequest,
)
from app.models.user import User
from app.services.email import EmailService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


def _normalize_email(email: str) -> str:
    return email.strip().lower()


async def _issue_auth_response(
    user_id: UUID,
    db_session: AsyncSession,
    settings: Settings,
) -> AuthResponse:
    access_token = create_access_token(user_id, settings)
    refresh_token_id = uuid4()
    refresh_token = create_refresh_token(
        user_id,
        token_id=refresh_token_id,
        settings=settings,
    )

    db_session.add(
        RefreshToken(
            id=refresh_token_id,
            user_id=user_id,
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
        user_id=user_id,
    )


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register_auth(
    body: RegisterRequest,
    db_session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
):
    email = _normalize_email(str(body.email))
    existing_user = (
        await db_session.exec(select(User).where(User.email == email))
    ).first()
    if existing_user is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User already exists",
        )

    user = User(
        email=email,
        full_name=body.full_name,
        hashed_password=hash_password(body.password),
    )
    db_session.add(user)

    try:
        await db_session.commit()
    except IntegrityError:
        await db_session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User already exists",
        )

    await db_session.refresh(user)
    return await _issue_auth_response(user.id, db_session, settings)


@router.post("/login", response_model=AuthResponse)
async def login_auth(
    body: LoginRequest,
    db_session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
):
    email = _normalize_email(str(body.email))
    user = (await db_session.exec(select(User).where(User.email == email))).first()

    if (
        user is None
        or user.hashed_password is None
        or not verify_password(body.password, user.hashed_password)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    return await _issue_auth_response(user.id, db_session, settings)


@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED)
async def forgot_password(
    body: ForgotPasswordRequest,
    db_session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    _: None = Depends(enforce_password_reset_rate_limit),
):
    """Begin a password reset.

    Always returns 202 regardless of whether the email exists or is a native
    account — never leak account existence. When the account is eligible
    (exists and has a password) a reset link is emailed.
    """
    email = _normalize_email(str(body.email))
    user = (await db_session.exec(select(User).where(User.email == email))).first()

    # Only native (password) accounts can reset a password. Google-only accounts
    # have no password to reset.
    if user is not None and user.hashed_password is not None:
        # Invalidate any outstanding tokens for this user before issuing a new one.
        existing = (
            await db_session.exec(
                select(PasswordResetToken).where(
                    PasswordResetToken.user_id == user.id,
                    PasswordResetToken.used_at.is_(None),  # type: ignore[union-attr]
                )
            )
        ).all()
        now = datetime.now(UTC).replace(tzinfo=None)
        for row in existing:
            row.used_at = now
            db_session.add(row)

        raw_token = secrets.token_urlsafe(32)
        db_session.add(
            PasswordResetToken(
                id=uuid4(),
                user_id=user.id,
                token_hash=hash_token(raw_token),
                created_at=now,
                expires_at=(
                    datetime.now(UTC)
                    + timedelta(minutes=settings.password_reset_token_expire_minutes)
                ).replace(tzinfo=None),
            )
        )
        await db_session.commit()

        separator = "&" if "?" in settings.password_reset_url_base else "?"
        reset_url = f"{settings.password_reset_url_base}{separator}token={raw_token}"
        await EmailService(settings).send_password_reset(to=email, reset_url=reset_url)
        logger.info("Password reset requested for %s (email dispatched)", email)
    else:
        logger.info(
            "Password reset requested for %s (no eligible account; no email sent)",
            email,
        )

    return {"message": "If an account exists, a reset link has been sent."}


@router.post("/reset-password", response_model=AuthResponse)
async def reset_password(
    body: ResetPasswordRequest,
    db_session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
):
    """Complete a password reset with a valid token and sign the user in."""
    token_hash = hash_token(body.token)
    token_row = (
        await db_session.exec(
            select(PasswordResetToken).where(
                PasswordResetToken.token_hash == token_hash
            )
        )
    ).first()

    now = datetime.now(UTC).replace(tzinfo=None)
    if (
        token_row is None
        or token_row.used_at is not None
        or token_row.expires_at < now
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This reset link is invalid or has expired.",
        )

    user = await db_session.get(User, token_row.user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This reset link is invalid or has expired.",
        )

    user.hashed_password = hash_password(body.password)
    db_session.add(user)

    token_row.used_at = now
    db_session.add(token_row)

    # Revoke all active refresh tokens — a password reset should log out any
    # other sessions (e.g. if the reset was triggered by a compromised account).
    active_refresh = (
        await db_session.exec(
            select(RefreshToken).where(
                RefreshToken.user_id == user.id,
                RefreshToken.revoked_at.is_(None),  # type: ignore[union-attr]
            )
        )
    ).all()
    for row in active_refresh:
        row.revoked_at = now
        db_session.add(row)

    await db_session.commit()
    logger.info("Password reset completed for user %s", user.id)

    return await _issue_auth_response(user.id, db_session, settings)


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
    email: str = _normalize_email(google_payload.get("email", ""))
    full_name: str = google_payload.get("name", "")

    # Look up existing user by Google ID
    statement = select(User).where(User.google_id == google_id)
    result = await db_session.exec(statement)
    user = result.first()

    if user is None and email:
        user = (await db_session.exec(select(User).where(User.email == email))).first()

    if user is not None and user.google_id not in (None, google_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Account already linked to another Google identity",
        )

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
        if user.google_id is None:
            user.google_id = google_id
            if full_name and not user.full_name:
                user.full_name = full_name
            db_session.add(user)
            await db_session.commit()
            await db_session.refresh(user)
        logger.info("Google auth succeeded for %s (existing user)", email)

    return await _issue_auth_response(user.id, db_session, settings)


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
    if (
        token_row is None
        or token_row.revoked_at is not None
        or token_row.expires_at < now
    ):
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
