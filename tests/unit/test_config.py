"""Smoke tests for application Settings.

The OAuth client IDs (web, iOS, Android) and the JWT secret are loaded from
environment variables. A missing or renamed field would silently break
production logins, so these tests guard the schema itself.
"""
from __future__ import annotations

from app.core.config import Settings


def test_settings_exposes_all_three_google_client_id_fields():
    """Regression guard: all three Google OAuth client IDs must be addressable
    on Settings. If a field is renamed or removed, verify_google_id_token
    silently stops accepting tokens from that platform."""
    fields = Settings.model_fields
    for field in (
        "google_client_id",
        "google_ios_client_id",
        "google_android_client_id",
    ):
        assert field in fields, f"Settings is missing OAuth field: {field}"


def test_settings_loads_google_client_ids_from_environment(monkeypatch, tmp_path):
    """Each Google client ID env var must round-trip into Settings. Catches
    bugs where pydantic-settings stops mapping an env name to the field."""
    monkeypatch.chdir(tmp_path)  # avoid picking up real .env.local
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "web-id-test")
    monkeypatch.setenv("GOOGLE_IOS_CLIENT_ID", "ios-id-test")
    monkeypatch.setenv("GOOGLE_ANDROID_CLIENT_ID", "android-id-test")
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/x")
    monkeypatch.setenv(
        "JWT_SECRET_KEY", "test-secret-min-32-bytes-length-1234"
    )

    settings = Settings()

    assert settings.google_client_id == "web-id-test"
    assert settings.google_ios_client_id == "ios-id-test"
    assert settings.google_android_client_id == "android-id-test"


def test_settings_treats_unset_google_client_ids_as_empty_string(
    monkeypatch, tmp_path
):
    """When a client ID env var is unset, the field defaults to "" (not
    None). verify_google_id_token relies on this to skip empty values when
    building the audience allowlist."""
    monkeypatch.chdir(tmp_path)
    for var in (
        "GOOGLE_CLIENT_ID",
        "GOOGLE_IOS_CLIENT_ID",
        "GOOGLE_ANDROID_CLIENT_ID",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/x")
    monkeypatch.setenv(
        "JWT_SECRET_KEY", "test-secret-min-32-bytes-length-1234"
    )

    settings = Settings()

    assert settings.google_client_id == ""
    assert settings.google_ios_client_id == ""
    assert settings.google_android_client_id == ""
