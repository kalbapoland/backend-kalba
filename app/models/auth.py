import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, field_validator
from sqlmodel import Field, SQLModel

PASSWORD_LETTER_RE = re.compile(r"[A-Za-z]")
PASSWORD_DIGIT_RE = re.compile(r"\d")


class GoogleAuthRequest(BaseModel):
    id_token: str


class NativeAuthRequest(BaseModel):
    email: EmailStr
    password: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()

    @field_validator("password")
    @classmethod
    def validate_password_present(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Password is required")
        return value


class RegisterRequest(NativeAuthRequest):
    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, value: str) -> str:
        if len(value) < 8:
            raise ValueError("Password must be at least 8 characters long")
        if PASSWORD_LETTER_RE.search(value) is None:
            raise ValueError("Password must contain at least one letter")
        if PASSWORD_DIGIT_RE.search(value) is None:
            raise ValueError("Password must contain at least one number")
        return value


class LoginRequest(NativeAuthRequest):
    pass


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
