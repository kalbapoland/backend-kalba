"""Reset and seed deterministic mobile E2E fixtures for local development.

The fixture set is intentionally small and stable so Maestro flows can rely on
fixed emails, group titles, and workshop titles across Android and iOS.

Usage:
    uv run python tests/automated/seed_mobile_e2e_fixtures.py
    uv run python tests/automated/seed_mobile_e2e_fixtures.py --force
    uv run python tests/automated/seed_mobile_e2e_fixtures.py --cleanup
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import delete, or_
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import Environment, get_settings
from app.core.security import hash_password
from app.db import _prepare_async_url
from app.models.auth import RefreshToken
from app.models.group import Group, GroupMembership
from app.models.my_kalba import UserGoal, UserNotification, UserNotificationType
from app.models.notification import PushToken
from app.models.tag import WorkshopTag
from app.models.user import TrainerProfile, User, UserRole
from app.models.video import WorkshopParticipant, WorkshopRules
from app.models.workshop import Workshop, WorkshopEnrollment
from app.services.hashtags import set_workshop_tags

PASSWORD = "Pass1234"

TRAINER_EMAIL = "e2e.trainer@kalba.dev"
USER_EMAIL = "e2e.user@kalba.dev"
FULLER_EMAIL = "e2e.fuller@kalba.dev"

TRAINER_GROUP_TITLE = "E2E Trainer Group"
DISCOVER_GROUP_TITLE = "E2E Discover Group"

WORKSHOP_FREE_TITLE = "E2E Workshop Free"
WORKSHOP_FULL_TITLE = "E2E Workshop Full"
WORKSHOP_TRAINER_TITLE = "E2E Workshop Trainer"
WORKSHOP_PAST_TITLE = "E2E Workshop Past"

LOCAL_DB_HOSTS = {"localhost", "127.0.0.1", "::1", "db"}


def _utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _database_host(pg_url: str) -> str | None:
    try:
        return urlparse(pg_url).hostname
    except ValueError:
        return None


def _is_local_database_host(hostname: str | None) -> bool:
    if hostname is None:
        return False
    return hostname.lower() in LOCAL_DB_HOSTS


async def _delete_fixture_rows(session: AsyncSession) -> None:
    fixture_emails = [
        TRAINER_EMAIL,
        USER_EMAIL,
        FULLER_EMAIL,
        "e2e.register.smoke@kalba.dev",
        "e2e.trainer@kalba.local",
        "e2e.user@kalba.local",
        "e2e.fuller@kalba.local",
        "e2e.trainer@kalba.test",
        "e2e.user@kalba.test",
        "e2e.fuller@kalba.test",
    ]
    users = (
        await session.exec(select(User).where(User.email.in_(fixture_emails)))
    ).all()
    user_ids: list[UUID] = [user.id for user in users]

    if not user_ids:
        await session.commit()
        return

    groups = (await session.exec(select(Group).where(Group.trainer_id.in_(user_ids)))).all()
    group_ids: list[UUID] = [group.id for group in groups]

    workshop_conditions = [Workshop.trainer_id.in_(user_ids)]
    if group_ids:
        workshop_conditions.append(Workshop.group_id.in_(group_ids))
    workshops = (await session.exec(select(Workshop).where(or_(*workshop_conditions)))).all()
    workshop_ids: list[UUID] = [workshop.id for workshop in workshops]

    await session.exec(
        delete(WorkshopParticipant).where(WorkshopParticipant.user_id.in_(user_ids))
    )
    await session.exec(
        delete(WorkshopEnrollment).where(WorkshopEnrollment.user_id.in_(user_ids))
    )
    await session.exec(
        delete(GroupMembership).where(GroupMembership.user_id.in_(user_ids))
    )

    if workshop_ids:
        await session.exec(
            delete(WorkshopParticipant).where(
                WorkshopParticipant.workshop_id.in_(workshop_ids)
            )
        )
        await session.exec(
            delete(WorkshopRules).where(WorkshopRules.workshop_id.in_(workshop_ids))
        )
        await session.exec(
            delete(WorkshopTag).where(WorkshopTag.workshop_id.in_(workshop_ids))
        )
        await session.exec(
            delete(WorkshopEnrollment).where(
                WorkshopEnrollment.workshop_id.in_(workshop_ids)
            )
        )
        await session.exec(delete(Workshop).where(Workshop.id.in_(workshop_ids)))

    if group_ids:
        await session.exec(delete(GroupMembership).where(GroupMembership.group_id.in_(group_ids)))
        await session.exec(delete(Group).where(Group.id.in_(group_ids)))

    if user_ids:
        await session.exec(
            delete(UserNotification).where(UserNotification.user_id.in_(user_ids))
        )
        await session.exec(delete(UserGoal).where(UserGoal.user_id.in_(user_ids)))
        await session.exec(delete(PushToken).where(PushToken.user_id.in_(user_ids)))
        await session.exec(delete(RefreshToken).where(RefreshToken.user_id.in_(user_ids)))
        await session.exec(delete(TrainerProfile).where(TrainerProfile.user_id.in_(user_ids)))
        await session.exec(delete(User).where(User.id.in_(user_ids)))

    await session.commit()


async def _create_user(
    session: AsyncSession,
    *,
    email: str,
    full_name: str,
    role: UserRole,
    password: str,
) -> User:
    user = User(
        email=email,
        full_name=full_name,
        hashed_password=hash_password(password),
        role=role,
    )
    session.add(user)
    await session.flush()

    if role == UserRole.TRAINER:
        session.add(
            TrainerProfile(
                user_id=user.id,
                bio="E2E trainer profile",
                specialties=["mindfulness", "mobility"],
            )
        )

    session.add(
        UserGoal(
            user_id=user.id,
            monthly_target=8 if role == UserRole.TRAINER else 4,
        )
    )
    return user


async def _create_workshop(
    session: AsyncSession,
    *,
    trainer_id: UUID,
    group_id: UUID,
    title: str,
    description: str,
    start_time: datetime,
    duration_minutes: int,
    price: Decimal,
    max_participants: int,
) -> Workshop:
    workshop = Workshop(
        trainer_id=trainer_id,
        group_id=group_id,
        title=title,
        description=description,
        start_time=start_time,
        duration_minutes=duration_minutes,
        timezone="Europe/Warsaw",
        price=price,
        max_participants=max_participants,
        reminder_minutes_before=60,
    )
    session.add(workshop)
    await session.flush()

    session.add(WorkshopRules(workshop_id=workshop.id))
    await set_workshop_tags(session, workshop.id, description)
    return workshop


async def seed_mobile_e2e_fixtures(force: bool, cleanup_only: bool) -> int:
    settings = get_settings()
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

    db_host = _database_host(settings.pg_url)
    if not _is_local_database_host(db_host) and not force:
        print(
            (
                f"refusing to run against non-local database host {db_host!r}; "
                "use --force to override"
            ),
            file=sys.stderr,
        )
        return 2

    fixture_password = PASSWORD
    if settings.app_env != Environment.LOCAL or not _is_local_database_host(db_host):
        fixture_password = os.getenv("KALBA_E2E_PASSWORD", "")
        if not fixture_password:
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
            await _delete_fixture_rows(session)

            if cleanup_only:
                print("Cleaned mobile E2E fixtures.")
                return 0

            trainer = await _create_user(
                session,
                email=TRAINER_EMAIL,
                full_name="E2E Trainer",
                role=UserRole.TRAINER,
                password=fixture_password,
            )
            user = await _create_user(
                session,
                email=USER_EMAIL,
                full_name="E2E User",
                role=UserRole.USER,
                password=fixture_password,
            )
            fuller = await _create_user(
                session,
                email=FULLER_EMAIL,
                full_name="E2E Fuller",
                role=UserRole.USER,
                password=fixture_password,
            )

            trainer_group = Group(
                trainer_id=trainer.id,
                title=TRAINER_GROUP_TITLE,
                description="Primary trainer-owned group used in mobile E2E flows.",
            )
            discover_group = Group(
                trainer_id=trainer.id,
                title=DISCOVER_GROUP_TITLE,
                description="Discover-only group used to test subscribe flows.",
            )
            session.add(trainer_group)
            session.add(discover_group)
            await session.flush()

            session.add(
                GroupMembership(
                    group_id=trainer_group.id,
                    user_id=user.id,
                    role="member",
                )
            )
            session.add(
                GroupMembership(
                    group_id=trainer_group.id,
                    user_id=fuller.id,
                    role="member",
                )
            )

            now = _utc_now_naive()
            workshop_free = await _create_workshop(
                session,
                trainer_id=trainer.id,
                group_id=trainer_group.id,
                title=WORKSHOP_FREE_TITLE,
                description="Visible to the seeded user for enroll flow. #e2e #free",
                start_time=now + timedelta(days=1, hours=2),
                duration_minutes=60,
                price=Decimal("0.00"),
                max_participants=5,
            )
            workshop_full = await _create_workshop(
                session,
                trainer_id=trainer.id,
                group_id=trainer_group.id,
                title=WORKSHOP_FULL_TITLE,
                description="Already full for UI full-state assertions. #e2e #full",
                start_time=now + timedelta(days=2, hours=3),
                duration_minutes=60,
                price=Decimal("25.00"),
                max_participants=1,
            )
            workshop_trainer = await _create_workshop(
                session,
                trainer_id=trainer.id,
                group_id=trainer_group.id,
                title=WORKSHOP_TRAINER_TITLE,
                description="Owned by the trainer for edit/delete flows. #e2e #trainer",
                start_time=now + timedelta(days=3, hours=4),
                duration_minutes=75,
                price=Decimal("35.00"),
                max_participants=8,
            )

            # User enrolled in workshop_free so My Kalba schedule is non-empty
            session.add(WorkshopEnrollment(user_id=user.id, workshop_id=workshop_free.id))

            # Past workshop with user enrollment so My Kalba stats show completed > 0.
            # Using hours=2 (not days=5) so start_time stays in the current month even when
            # the seed runs on the 1st–5th of the month (window shrinks to 2 h past midnight).
            workshop_past = await _create_workshop(
                session,
                trainer_id=trainer.id,
                group_id=trainer_group.id,
                title=WORKSHOP_PAST_TITLE,
                description="Completed workshop for My Kalba stats testing. #e2e #past",
                start_time=now - timedelta(hours=2),
                duration_minutes=60,
                price=Decimal("0.00"),
                max_participants=5,
            )
            session.add(WorkshopEnrollment(user_id=user.id, workshop_id=workshop_past.id))

            session.add(
                WorkshopEnrollment(user_id=fuller.id, workshop_id=workshop_full.id)
            )

            session.add(
                UserNotification(
                    user_id=user.id,
                    type=UserNotificationType.WORKSHOP_REMINDER,
                    title="E2E Reminder",
                    body="Fixture notification for My Kalba smoke.",
                    payload={"workshop_id": str(workshop_free.id)},
                )
            )
            session.add(
                UserNotification(
                    user_id=user.id,
                    type=UserNotificationType.WORKSHOP_RESCHEDULED,
                    title="E2E Rescheduled",
                    body="Read fixture notification for filter checks.",
                    payload={"workshop_id": str(workshop_trainer.id)},
                    is_read=True,
                    read_at=now,
                )
            )

            await session.commit()

            print("Seeded mobile E2E fixtures:")
            print(f"  trainer:  {TRAINER_EMAIL}")
            print(f"  user:     {USER_EMAIL}")
            print(f"  group:    {TRAINER_GROUP_TITLE} (user already subscribed)")
            print(f"  group:    {DISCOVER_GROUP_TITLE} (discover flow)")
            print(f"  workshop: {WORKSHOP_FREE_TITLE} (user enrolled)")
            print(f"  workshop: {WORKSHOP_FULL_TITLE} (fuller enrolled, full)")
            print(f"  workshop: {WORKSHOP_TRAINER_TITLE}")
            print(f"  workshop: {WORKSHOP_PAST_TITLE} (user enrolled, past — for stats)")
    finally:
        await engine.dispose()

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="allow running against a non-local APP_ENV (dangerous)",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="delete the deterministic mobile E2E fixtures without seeding them again",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    sys.exit(asyncio.run(seed_mobile_e2e_fixtures(args.force, args.cleanup)))
