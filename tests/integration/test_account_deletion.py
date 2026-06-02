from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlmodel import func, select

from app.core.security import create_access_token, hash_token
from app.models.auth import PasswordResetToken, RefreshToken
from app.models.group import Group, GroupMembership
from app.models.my_kalba import UserGoal, UserNotification, UserNotificationType
from app.models.notification import PushToken, PushPlatform
from app.models.tag import Tag, WorkshopTag
from app.models.user import TrainerProfile, User, UserRole
from app.models.video import ParticipantRole, WorkshopParticipant, WorkshopRules
from app.models.workshop import Workshop, WorkshopEnrollment


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _count(db_session, model, **where) -> int:
    stmt = select(func.count()).select_from(model)
    for col, val in where.items():
        stmt = stmt.where(getattr(model, col) == val)
    return (await db_session.exec(stmt)).one()


@pytest.mark.asyncio
async def test_delete_account_removes_user_and_personal_data(client, db_session):
    user = User(
        email="deluser@test.com",
        full_name="Del User",
        hashed_password="hashed",
        role=UserRole.USER,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    now = datetime.now(UTC).replace(tzinfo=None)
    db_session.add_all(
        [
            RefreshToken(
                id=uuid4(),
                user_id=user.id,
                token_hash=hash_token("refresh-x"),
                issued_at=now,
                expires_at=now + timedelta(days=30),
            ),
            PasswordResetToken(
                id=uuid4(),
                user_id=user.id,
                token_hash=hash_token("reset-x"),
                created_at=now,
                expires_at=now + timedelta(minutes=60),
            ),
            PushToken(
                user_id=user.id,
                token="ExponentPushToken[deluser]",
                platform=PushPlatform.IOS,
            ),
            UserGoal(user_id=user.id, monthly_target=5),
            UserNotification(
                user_id=user.id,
                type=UserNotificationType.WORKSHOP_REMINDER,
                title="t",
                body="b",
            ),
        ]
    )
    await db_session.commit()

    token = create_access_token(user.id)
    resp = await client.delete("/api/v1/users/me", headers=_auth(token))
    assert resp.status_code == 204

    # The deletion committed in the request's session; drop this session's
    # cached identity map so reads re-query the database.
    db_session.expunge_all()
    assert await db_session.get(User, user.id) is None
    assert await _count(db_session, RefreshToken, user_id=user.id) == 0
    assert await _count(db_session, PasswordResetToken, user_id=user.id) == 0
    assert await _count(db_session, PushToken, user_id=user.id) == 0
    assert await _count(db_session, UserGoal, user_id=user.id) == 0
    assert await _count(db_session, UserNotification, user_id=user.id) == 0

    # Token is still cryptographically valid, but the user no longer exists.
    me = await client.get("/api/v1/users/me", headers=_auth(token))
    assert me.status_code == 404
    # Deleting again is a 404, not a 500.
    again = await client.delete("/api/v1/users/me", headers=_auth(token))
    assert again.status_code == 404


@pytest.mark.asyncio
async def test_delete_account_removes_trainer_owned_content(client, db_session):
    trainer = User(
        email="deltrainer@test.com",
        full_name="Del Trainer",
        google_id="g-deltrainer",
        role=UserRole.TRAINER,
    )
    db_session.add(trainer)
    await db_session.commit()
    await db_session.refresh(trainer)

    db_session.add(TrainerProfile(user_id=trainer.id, bio="hi"))

    group = Group(trainer_id=trainer.id, title="Owned Group")
    db_session.add(group)
    await db_session.commit()
    await db_session.refresh(group)

    workshop = Workshop(
        trainer_id=trainer.id,
        group_id=group.id,
        title="Owned WS",
        start_time=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=1),
        duration_minutes=60,
        price=Decimal("0.00"),
        max_participants=10,
    )
    db_session.add(workshop)
    await db_session.commit()
    await db_session.refresh(workshop)

    tag = Tag(name="calm")
    db_session.add(tag)
    await db_session.commit()
    await db_session.refresh(tag)

    db_session.add_all(
        [
            WorkshopRules(workshop_id=workshop.id),
            WorkshopTag(workshop_id=workshop.id, tag_id=tag.id),
            GroupMembership(group_id=group.id, user_id=trainer.id, role="member"),
            WorkshopParticipant(
                user_id=trainer.id,
                workshop_id=workshop.id,
                role=ParticipantRole.HOST,
            ),
            WorkshopEnrollment(user_id=trainer.id, workshop_id=workshop.id),
        ]
    )
    await db_session.commit()

    token = create_access_token(trainer.id)
    resp = await client.delete("/api/v1/users/me", headers=_auth(token))
    assert resp.status_code == 204

    db_session.expunge_all()
    assert await db_session.get(User, trainer.id) is None
    assert await db_session.get(Group, group.id) is None
    assert await db_session.get(Workshop, workshop.id) is None
    assert await _count(db_session, WorkshopRules, workshop_id=workshop.id) == 0
    assert await _count(db_session, WorkshopTag, workshop_id=workshop.id) == 0
    assert await _count(db_session, WorkshopParticipant, workshop_id=workshop.id) == 0
    assert await _count(db_session, WorkshopEnrollment, workshop_id=workshop.id) == 0
    assert await _count(db_session, GroupMembership, group_id=group.id) == 0
    assert await _count(db_session, TrainerProfile, user_id=trainer.id) == 0


@pytest.mark.asyncio
async def test_delete_account_requires_auth(client):
    resp = await client.delete("/api/v1/users/me")
    assert resp.status_code in (401, 403)
