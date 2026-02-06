from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings, get_settings

GOOGLE_CERTS_URL = "https://www.googleapis.com/oauth2/v3/tokeninfo"

bearer_scheme = HTTPBearer()


def create_access_token(user_id: UUID, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    expire = datetime.now(UTC) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {
        "sub": str(user_id),
        "exp": expire,
    }
    return jwt.encode(
        payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
    )


def decode_access_token(token: str, settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    try:
        return jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )


async def verify_google_id_token(
    id_token: str, settings: Settings | None = None
) -> dict:
    """Verify a Google ID token by calling Google's tokeninfo endpoint.

    Returns the token payload containing email, sub (Google user ID), name, etc.
    """
    settings = settings or get_settings()
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            GOOGLE_CERTS_URL,
            params={"id_token": id_token},
        )

    if resp.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Google ID token",
        )

    payload = resp.json()

    # Verify the token was issued for our app
    if settings.google_client_id and payload.get("aud") != settings.google_client_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token was not issued for this application",
        )

    return payload


def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> UUID:
    payload = decode_access_token(credentials.credentials, settings)
    return UUID(payload["sub"])
