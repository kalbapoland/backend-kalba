from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from fastapi import HTTPException

from app.core.config import Settings
from app.core.security import create_access_token, decode_access_token


def make_settings(**overrides) -> Settings:
    return Settings.model_validate(
        {
            "app_env": "local",
            "database_url": "postgresql://localhost/test",
            "jwt_secret_key": "test-secret",
            "jwt_algorithm": "HS256",
            "jwt_expire_minutes": 60,
            "google_client_id": "",
            "google_ios_client_id": "",
            "google_android_client_id": "",
            "daily_api_key": "",
            "daily_domain": "",
            **overrides,
        }
    )


def test_create_access_token_returns_string():
    token = create_access_token(uuid4(), make_settings())
    assert isinstance(token, str) and len(token) > 0


def test_decode_access_token_returns_correct_user_id():
    settings = make_settings()
    user_id = uuid4()
    token = create_access_token(user_id, settings)
    payload = decode_access_token(token, settings)
    assert payload["sub"] == str(user_id)


def test_decode_expired_token_raises_401():
    settings = make_settings()
    expired_payload = {
        "sub": str(uuid4()),
        "exp": datetime.now(UTC) - timedelta(minutes=1),
    }
    token = jwt.encode(
        expired_payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
    )
    with pytest.raises(HTTPException) as exc:
        decode_access_token(token, settings)
    assert exc.value.status_code == 401


def test_decode_invalid_token_raises_401():
    with pytest.raises(HTTPException) as exc:
        decode_access_token("not.a.valid.token", make_settings())
    assert exc.value.status_code == 401


def test_decode_token_wrong_secret_raises_401():
    user_id = uuid4()
    token = create_access_token(user_id, make_settings(jwt_secret_key="secret-a"))
    with pytest.raises(HTTPException) as exc:
        decode_access_token(token, make_settings(jwt_secret_key="secret-b"))
    assert exc.value.status_code == 401
