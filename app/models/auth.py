import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, field_validator
from sqlmodel import Field, SQLModel

PASSWORD_LETTER_RE = re.compile(r"[A-Za-z]")
PASSWORD_DIGIT_RE = re.compile(r"\d")


def _validate_password_strength(value: str) -> str:
    if len(value) < 8:
        raise ValueError("Password must be at least 8 characters long")
    if PASSWORD_LETTER_RE.search(value) is None:
        raise ValueError("Password must contain at least one letter")
    if PASSWORD_DIGIT_RE.search(value) is None:
        raise ValueError("Password must contain at least one number")
    return value


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
    full_name: str

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Name is required")
        return trimmed

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, value: str) -> str:
        return _validate_password_strength(value)


class LoginRequest(NativeAuthRequest):
    pass


class ForgotPasswordRequest(BaseModel):
    email: EmailStr

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()


class ResetPasswordRequest(BaseModel):
    token: str
    password: str

    @field_validator("token")
    @classmethod
    def validate_token_present(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Reset token is required")
        return value.strip()

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, value: str) -> str:
        return _validate_password_strength(value)


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


class PasswordResetToken(SQLModel, table=True):
    __tablename__ = "password_reset_token"

    id: UUID = Field(primary_key=True)
    user_id: UUID = Field(foreign_key="user.id", index=True)
    token_hash: str = Field(index=True, unique=True)
    expires_at: datetime
    created_at: datetime
    used_at: datetime | None = None
