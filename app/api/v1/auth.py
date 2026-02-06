from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.security import create_access_token, verify_google_id_token
from app.db import get_db_session
from app.models.user import User

router = APIRouter(prefix="/auth", tags=["auth"])


class GoogleAuthRequest(BaseModel):
    id_token: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: UUID


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
    google_payload = await verify_google_id_token(body.id_token)

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

    access_token = create_access_token(user.id)
    return AuthResponse(access_token=access_token, user_id=user.id)
