from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import Environment, get_settings
from app.core.security import hash_password
from app.db import _prepare_async_url
from app.models.user import User, UserRole

USER_EMAIL = "e2e.user@kalba.dev"
USER_PASSWORD = "Pass1234"
USER_NAME = "E2E User"
LOCAL_DB_HOSTS = {"localhost", "127.0.0.1", "::1", "db"}


def database_host(pg_url: str) -> str | None:
    try:
        return urlparse(pg_url).hostname
    except ValueError:
        return None


def is_local_database_host(hostname: str | None) -> bool:
    if hostname is None:
        return False
    return hostname.lower() in LOCAL_DB_HOSTS


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ensure deterministic user account for smoke flows.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="allow running outside APP_ENV=local",
    )
    parser.add_argument(
        "--reset-password",
        action="store_true",
        help="reset existing user password to deterministic smoke password",
    )
    return parser.parse_args()


async def ensure_smoke_user(*, force: bool, reset_password: bool) -> int:
    settings = get_settings()
    db_host = database_host(settings.pg_url)

    if settings.app_env in (Environment.STAGE, Environment.PROD):
        print("refusing to run against stage/prod environments", file=sys.stderr)
        return 2

    if settings.app_env != Environment.LOCAL and not force:
        print(
            (
                f"refusing to run against APP_ENV={settings.app_env.value!r}; "
                "only `local` is allowed. Use --force to override."
            ),
            file=sys.stderr,
        )
        return 2

    if not is_local_database_host(db_host) and not force:
        print(
            (
                f"refusing to run against non-local database host {db_host!r}; "
                "use --force to override"
            ),
            file=sys.stderr,
        )
        return 2

    user_password = USER_PASSWORD
    if settings.app_env != Environment.LOCAL or not is_local_database_host(db_host):
        user_password = os.getenv("KALBA_E2E_PASSWORD", "")
        if not user_password:
            print(
                "KALBA_E2E_PASSWORD is required when running outside APP_ENV=local",
                file=sys.stderr,
            )
            return 2

    url, connect_args = _prepare_async_url(settings.pg_url)
    engine = create_async_engine(url, connect_args=connect_args)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with factory() as session:
            user = (await session.exec(select(User).where(User.email == USER_EMAIL))).first()

            if user is None:
                user = User(
                    email=USER_EMAIL,
                    full_name=USER_NAME,
                    hashed_password=hash_password(user_password),
                    role=UserRole.USER,
                )
                session.add(user)
                await session.flush()
                print(f"Created user account: {USER_EMAIL}")
            else:
                user.role = UserRole.USER
                if reset_password or user.hashed_password is None:
                    user.hashed_password = hash_password(user_password)
                if not user.full_name:
                    user.full_name = USER_NAME
                session.add(user)
                if reset_password:
                    print(f"Updated user account role/password: {USER_EMAIL}")
                else:
                    print(f"Updated user account role: {USER_EMAIL}")

            await session.commit()
    finally:
        await engine.dispose()

    return 0


if __name__ == "__main__":
    args = parse_args()
    raise SystemExit(asyncio.run(ensure_smoke_user(force=args.force, reset_password=args.reset_password)))