from enum import Enum
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    LOCAL = "local"
    DEV = "dev"
    STAGE = "stage"
    PROD = "prod"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env.local",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Environment = Environment.LOCAL
    debug: bool = False

    # Database
    database_url: str = "postgresql://postgres:postgres@localhost:5432/kalba"

    # JWT
    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # 1 week

    # Google OAuth
    google_client_id: str = ""
    google_ios_client_id: str = ""

    # CORS
    cors_origins: list[str] = ["*"]

    @property
    def env_file_for_environment(self) -> str:
        return f".env.{self.app_env.value}"


def _build_settings() -> Settings:
    """Build settings, loading the correct .env file based on APP_ENV."""
    # First pass: read APP_ENV from default .env.local or environment
    preliminary = Settings()
    # Second pass: reload with the environment-specific file
    return Settings(
        _env_file=preliminary.env_file_for_environment,  # type: ignore[call-arg]
    )


@lru_cache
def get_settings() -> Settings:
    return _build_settings()
