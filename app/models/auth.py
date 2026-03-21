from datetime import datetime
from uuid import UUID

from pydantic import BaseModel
from sqlmodel import Field, SQLModel


class GoogleAuthRequest(BaseModel):
    id_token: str


class AuthResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user_id: UUID


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class RefreshToken(SQLModel, table=True):
    __tablename__ = "refresh_token"

    id: UUID = Field(primary_key=True)
    user_id: UUID = Field(foreign_key="user.id", index=True)
    token_hash: str = Field(index=True, unique=True)
    expires_at: datetime
    issued_at: datetime
    revoked_at: datetime | None = None
