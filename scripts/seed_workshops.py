"""Seed random non-colliding workshops for a trainer in the next N days.

Uses the same DATABASE_URL as the running app — run locally and it hits the
local Postgres. Never point this at staging or prod.

Usage:
    uv run python scripts/seed_workshops.py --user trainer@example.com --count 20
    uv run python scripts/seed_workshops.py --user trainer@example.com --count 30 --horizon-days 90 --seed 42
"""

from __future__ import annotations

import argparse
import asyncio
import random
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

# Ensure the app package is importable when invoked via `python scripts/...`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import Environment, get_settings
from app.db import _prepare_async_url
from app.models.user import User, UserRole
from app.models.video import WorkshopRules
from app.models.workshop import Workshop
from app.services.hashtags import set_workshop_tags

TITLES = [
    "Poranna medytacja",
    "Yoga flow",
    "Praca z oddechem",
    "Joga regeneracyjna",
    "Medytacja prowadzona",
    "Yin yoga",
    "Pilates dla każdego",
    "Mindfulness wieczorny",
    "Praca z ciałem",
    "Warsztat oddechu",
    "Rozciąganie i mobilność",
    "Joga dla początkujących",
    "Medytacja w ciszy",
    "Hatha yoga",
    "Power yoga",
]

DESCRIPTIONS = [
    "Spokojna sesja na otwarcie dnia. #joga #medytacja #spokój",
    "Dynamiczny flow dla każdego poziomu. #joga #ruch #energia",
    "Praca z oddechem i intencją. #oddech #mindfulness",
    "Regeneracyjna sesja po długim tygodniu. #regeneracja #joga",
    "Spotkanie z ciałem i emocjami. #ciało #emocje #praca",
    "Łagodne otwarcie ciała przed pracą. #mobilność #poranek",
    "Wieczorne wyciszenie. #medytacja #wieczór #relaks",
    "Praca nad siłą i stabilnością. #siła #pilates #core",
]

DURATIONS = [30, 45, 60, 75, 90]
HOUR_RANGE = range(7, 20)          # start godzina 7:00–19:xx
MINUTE_GRID = (0, 15, 30, 45)
PRICES = (Decimal("0"), Decimal("25"), Decimal("35"), Decimal("50"), Decimal("75"))
MAX_PARTICIPANTS = (5, 8, 10, 12, 15, 20)


def random_start(horizon_days: int) -> datetime:
    """Pick a UTC-naive future datetime within the horizon, aligned to 15-min."""
    now_utc = datetime.now(UTC).replace(tzinfo=None)
    day_offset = random.randint(1, horizon_days)
    hour = random.choice(list(HOUR_RANGE))
    minute = random.choice(MINUTE_GRID)
    return (now_utc + timedelta(days=day_offset)).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )


def overlaps(
    a_start: datetime, a_dur: int, b_start: datetime, b_dur: int
) -> bool:
    a_end = a_start + timedelta(minutes=a_dur)
    b_end = b_start + timedelta(minutes=b_dur)
    return a_start < b_end and b_start < a_end


async def find_trainer(session: AsyncSession, identifier: str) -> User | None:
    # Accept email or UUID.
    try:
        user_id = UUID(identifier)
    except ValueError:
        statement = select(User).where(User.email == identifier)
        return (await session.exec(statement)).first()
    return await session.get(User, user_id)


async def load_existing_intervals(
    session: AsyncSession, trainer_id: UUID, horizon_days: int
) -> list[tuple[datetime, int]]:
    """Return (start_time, duration_minutes) for the trainer's live workshops
    in the horizon window — used as the collision baseline."""
    now_naive = datetime.now(UTC).replace(tzinfo=None)
    horizon_end = now_naive + timedelta(days=horizon_days + 1)
    statement = select(Workshop).where(
        Workshop.trainer_id == trainer_id,
        Workshop.deleted_at.is_(None),
        Workshop.start_time >= now_naive,
        Workshop.start_time <= horizon_end,
    )
    rows = (await session.exec(statement)).all()
    return [(w.start_time, w.duration_minutes) for w in rows]


async def seed(email: str, count: int, horizon_days: int, force: bool) -> int:
    settings = get_settings()

    # Hard refusal on non-local environments so a misconfigured `DATABASE_URL`
    # (e.g. an open `fly proxy` session) cannot accidentally seed staging or
    # prod. `--force` is an explicit escape hatch for advanced use.
    if settings.app_env != Environment.LOCAL and not force:
        print(
            f"refusing to run against APP_ENV={settings.app_env.value!r}; "
            f"only `local` is allowed. Use --force to override.",
            file=sys.stderr,
        )
        return 2

    url, connect_args = _prepare_async_url(settings.pg_url)
    engine = create_async_engine(url, connect_args=connect_args)
    factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    created = 0
    try:
        async with factory() as session:
            trainer = await find_trainer(session, email)
            if trainer is None:
                print(f"User {email!r} not found", file=sys.stderr)
                return 2
            if trainer.role != UserRole.TRAINER:
                print(
                    f"User {email!r} is not a trainer "
                    f"(role={trainer.role.value})",
                    file=sys.stderr,
                )
                return 2

            booked = await load_existing_intervals(
                session, trainer.id, horizon_days
            )
            print(
                f"Trainer: {trainer.email} ({trainer.id}); "
                f"{len(booked)} workshops already in the next {horizon_days} "
                f"days — will plan around them."
            )

            # Cap total attempts so the script can't spin forever when the
            # calendar is too dense to fit `count` more sessions.
            max_attempts = max(50, count * 50)
            attempts = 0

            while created < count and attempts < max_attempts:
                attempts += 1
                duration = random.choice(DURATIONS)
                start = random_start(horizon_days)

                if any(overlaps(start, duration, s, d) for s, d in booked):
                    continue

                description = random.choice(DESCRIPTIONS)
                workshop = Workshop(
                    trainer_id=trainer.id,
                    title=random.choice(TITLES),
                    description=description,
                    start_time=start,
                    duration_minutes=duration,
                    timezone="Europe/Warsaw",
                    price=random.choice(PRICES),
                    max_participants=random.choice(MAX_PARTICIPANTS),
                    reminder_minutes_before=60,
                )
                session.add(workshop)
                await session.flush()

                # Mirror the create_workshop handler: default rules + hashtags.
                session.add(WorkshopRules(workshop_id=workshop.id))
                await set_workshop_tags(session, workshop.id, description)

                booked.append((start, duration))
                created += 1
                print(
                    f"  [{created:>3}/{count}] {workshop.title:<26} "
                    f"{start.strftime('%a %Y-%m-%d %H:%M')} "
                    f"({duration} min)"
                )

            await session.commit()

            if created < count:
                print(
                    f"\nCreated {created}/{count} workshops; "
                    f"gave up after {attempts} attempts (calendar too dense)."
                )
            else:
                print(f"\nCreated {count} workshops for {trainer.email}.")
    finally:
        await engine.dispose()

    return 0 if created > 0 else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--user", required=True, help="trainer email or UUID"
    )
    parser.add_argument(
        "--count", type=int, default=20, help="how many workshops to seed (default: 20)"
    )
    parser.add_argument(
        "--horizon-days",
        type=int,
        default=90,
        help="days in the future to seed within (default: 90)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="random seed for reproducible runs",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="allow running against a non-local APP_ENV (dangerous)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.seed is not None:
        random.seed(args.seed)
    sys.exit(
        asyncio.run(
            seed(args.user, args.count, args.horizon_days, args.force)
        )
    )
