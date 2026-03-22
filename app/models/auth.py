from uuid import UUID

from pydantic import BaseModel


class GoogleAuthRequest(BaseModel):
    id_token: str


class AuthResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user_id: UUID


class RefreshRequest(BaseModel):
    refresh_token: str
