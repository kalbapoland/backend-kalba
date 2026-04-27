from sqlalchemy.dialects import postgresql

from app.models.notification import PUSH_PLATFORM_ENUM, PushPlatform


def test_push_platform_enum_uses_lowercase_values() -> None:
    assert PUSH_PLATFORM_ENUM.enums == ["ios", "android"]


def test_push_platform_bind_processor_serializes_enum_values() -> None:
    processor = PUSH_PLATFORM_ENUM.bind_processor(postgresql.dialect())
    assert processor is not None
    assert processor(PushPlatform.IOS) == "ios"
    assert processor(PushPlatform.ANDROID) == "android"
