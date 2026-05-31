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
from app.models.user import TrainerProfile, User, UserRole

TRAINER_EMAIL = "e2e.trainer@kalba.dev"
TRAINER_PASSWORD = "Pass1234"
TRAINER_NAME = "E2E Trainer"
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
    parser = argparse.ArgumentParser(description="Ensure deterministic trainer account for smoke flows.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="allow running outside APP_ENV=local",
    )
    parser.add_argument(
        "--reset-password",
        action="store_true",
        help="reset existing trainer password to deterministic smoke password",
    )
    parser.add_argument(
        "--allow-promote-existing",
        action="store_true",
        help="allow promoting an existing non-trainer account for TRAINER_EMAIL",
    )
    return parser.parse_args()


async def ensure_smoke_trainer(
    *,
    force: bool,
    reset_password: bool,
    allow_promote_existing: bool,
) -> int:
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

    trainer_password = TRAINER_PASSWORD
    if settings.app_env != Environment.LOCAL or not is_local_database_host(db_host):
        trainer_password = os.getenv("KALBA_E2E_PASSWORD", "")
        if not trainer_password:
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
            user = (await session.exec(select(User).where(User.email == TRAINER_EMAIL))).first()

            if user is None:
                user = User(
                    email=TRAINER_EMAIL,
                    full_name=TRAINER_NAME,
                    hashed_password=hash_password(trainer_password),
                    role=UserRole.TRAINER,
                )
                session.add(user)
                await session.flush()
                print(f"Created trainer account: {TRAINER_EMAIL}")
            else:
                if user.role != UserRole.TRAINER and not allow_promote_existing:
                    print(
                        (
                            "refusing to promote existing non-trainer account; "
                            "pass --allow-promote-existing to override"
                        ),
                        file=sys.stderr,
                    )
                    await session.rollback()
                    return 3

                user.role = UserRole.TRAINER
                if reset_password or user.hashed_password is None:
                    user.hashed_password = hash_password(trainer_password)
                if not user.full_name:
                    user.full_name = TRAINER_NAME
                session.add(user)
                if reset_password:
                    print(f"Updated trainer account role/password: {TRAINER_EMAIL}")
                else:
                    print(f"Updated trainer account role: {TRAINER_EMAIL}")

            profile = (
                await session.exec(select(TrainerProfile).where(TrainerProfile.user_id == user.id))
            ).first()
            if profile is None:
                session.add(
                    TrainerProfile(
                        user_id=user.id,
                        bio="E2E trainer profile",
                        specialties=["mindfulness", "mobility"],
                    )
                )
                print("Created missing trainer_profile for smoke trainer")

            await session.commit()
    finally:
        await engine.dispose()

    return 0


if __name__ == "__main__":
    args = parse_args()
    raise SystemExit(
        asyncio.run(
            ensure_smoke_trainer(
                force=args.force,
                reset_password=args.reset_password,
                allow_promote_existing=args.allow_promote_existing,
            )
        )
    )
