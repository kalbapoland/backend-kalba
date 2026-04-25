import enum
import re
from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, field_validator
from sqlmodel import Field, SQLModel


EXPO_TOKEN_PATTERN = re.compile(r"^ExponentPushToken\[[A-Za-z0-9_-]+\]$")


class PushPlatform(str, enum.Enum):
    IOS = "ios"
    ANDROID = "android"


class PushToken(SQLModel, table=True):
    __tablename__ = "push_token"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(foreign_key="user.id", index=True)
    token: str = Field(unique=True, index=True)
    platform: PushPlatform
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_seen_at: datetime = Field(default_factory=datetime.utcnow)


class PushTokenRegister(BaseModel):
    token: str
    platform: PushPlatform

    @field_validator("token")
    @classmethod
    def validate_expo_format(cls, v: str) -> str:
        if not EXPO_TOKEN_PATTERN.match(v):
            raise ValueError("token must be a valid ExponentPushToken[...] string")
        return v
