import enum
import re
from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, field_validator
from sqlmodel import Field, SQLModel


EXPO_TOKEN_PATTERN = re.compile(r"^ExponentPushToken\[[A-Za-z0-9_-]+\]$")


def _utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class PushPlatform(str, enum.Enum):
    IOS = "ios"
    ANDROID = "android"


class PushToken(SQLModel, table=True):
    """Expo push token registered for a user's device.

    Ownership is keyed by `token`, not by `user_id` — a token belongs to a
    physical device, not an account. When the same token is re-registered
    by a different user (shared device, account switch), `user_id` is
    reassigned. See `app/services/notifications.py:register_push_token`.
    """

    __tablename__ = "push_token"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(foreign_key="user.id", index=True)
    token: str = Field(unique=True, index=True)
    platform: PushPlatform
    created_at: datetime = Field(default_factory=_utc_now_naive)
    last_seen_at: datetime = Field(default_factory=_utc_now_naive)


class PushTokenRegister(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str
    platform: PushPlatform

    @field_validator("token")
    @classmethod
    def validate_expo_format(cls, v: str) -> str:
        if not EXPO_TOKEN_PATTERN.match(v):
            raise ValueError("token must be a valid ExponentPushToken[...] string")
        return v


class PushTokenUnregister(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str

    @field_validator("token")
    @classmethod
    def validate_expo_format(cls, v: str) -> str:
        if not EXPO_TOKEN_PATTERN.match(v):
            raise ValueError("token must be a valid ExponentPushToken[...] string")
        return v
