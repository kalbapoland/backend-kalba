import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from sqlmodel import func, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.v1.workshops import _serialize_workshops
from app.core.errors import ErrorCode
from app.core.security import get_current_user_id, get_optional_user_id
from app.db import get_db_session
from app.models.group import (
    Group,
    GroupCreate,
    GroupMemberRead,
    GroupMembership,
    GroupRead,
    GroupUpdate,
)
from app.models.user import User, UserRole
from app.models.workshop import Workshop, WorkshopRead
from app.services.daily import DailyService, DailyServiceError, get_daily_service
from app.services.my_kalba_notifications import (
    create_group_deleted_notifications,
    create_workshop_cancelled_notifications,
)
from app.services.notifications import PushMessage, send_push_to_users

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/groups", tags=["groups"])


async def _serialize_groups(
    session: AsyncSession,
    groups: list[Group],
    caller_id: UUID | None,
) -> list[GroupRead]:
    """Build GroupRead instances with caller-aware fields populated.

    Batches the membership lookups so a list endpoint stays O(1) queries:
    one COUNT-grouped query for `member_count`, one for the caller's own
    memberships.
    """
    if not groups:
        return []

    group_ids = [g.id for g in groups]

    count_stmt = (
        select(GroupMembership.group_id, func.count(GroupMembership.id))
        .where(GroupMembership.group_id.in_(group_ids))
        .group_by(GroupMembership.group_id)
    )
    counts: dict[UUID, int] = {row[0]: row[1] for row in (await session.exec(count_stmt)).all()}

    member_ids: set[UUID] = set()
    if caller_id is not None:
        member_stmt = select(GroupMembership.group_id).where(
            GroupMembership.user_id == caller_id,
            GroupMembership.group_id.in_(group_ids),
        )
        member_ids = set((await session.exec(member_stmt)).all())

    result: list[GroupRead] = []
    for g in groups:
        read = GroupRead.model_validate(g, from_attributes=True)
        read.member_count = counts.get(g.id, 0)
        read.is_owner = caller_id is not None and g.trainer_id == caller_id
        read.is_member = g.id in member_ids
        result.append(read)
    return result


async def _get_group_or_404(session: AsyncSession, group_id: UUID) -> Group:
    group = await session.get(Group, group_id)
    if group is None or group.deleted_at is not None:
        raise HTTPException(status_code=404, detail=ErrorCode.GROUP_NOT_FOUND)
    return group


@router.get("/", response_model=list[GroupRead])
async def list_groups(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    caller_id: UUID | None = Depends(get_optional_user_id),
    session: AsyncSession = Depends(get_db_session),
):
    """List all groups. Caller-context flags drive the dashboard split."""
    statement = (
        select(Group)
        .where(Group.deleted_at.is_(None))
        .order_by(Group.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    rows = (await session.exec(statement)).all()
    return await _serialize_groups(session, list(rows), caller_id)


@router.get("/mine", response_model=list[GroupRead])
async def list_my_groups(
    caller_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
):
    """Groups the caller owns or is subscribed to (the 'My Groups' section)."""
    statement = (
        select(Group)
        .where(
            Group.deleted_at.is_(None),
            or_(
                Group.trainer_id == caller_id,
                Group.id.in_(
                    select(GroupMembership.group_id).where(
                        GroupMembership.user_id == caller_id
                    )
                ),
            ),
        )
        .order_by(Group.created_at.desc())
    )
    rows = (await session.exec(statement)).all()
    return await _serialize_groups(session, list(rows), caller_id)


@router.get("/{group_id}", response_model=GroupRead)
async def get_group(
    group_id: UUID,
    caller_id: UUID | None = Depends(get_optional_user_id),
    session: AsyncSession = Depends(get_db_session),
):
    """Get a single group by ID."""
    group = await _get_group_or_404(session, group_id)
    return (await _serialize_groups(session, [group], caller_id))[0]


@router.post("/", response_model=GroupRead, status_code=status.HTTP_201_CREATED)
async def create_group(
    body: GroupCreate,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
):
    """Create a new group. Only trainers may create groups."""
    user = await session.get(User, user_id)
    if user is None or user.role != UserRole.TRAINER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ErrorCode.TRAINER_REQUIRED,
        )

    group = Group(
        trainer_id=user_id,
        title=body.title,
        description=body.description,
    )
    session.add(group)
    await session.commit()
    await session.refresh(group)
    logger.info("Group created: id=%s title=%r trainer=%s", group.id, group.title, user_id)
    return (await _serialize_groups(session, [group], user_id))[0]


@router.patch("/{group_id}", response_model=GroupRead)
async def update_group(
    group_id: UUID,
    body: GroupUpdate,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
):
    """Update a group's title/description. Only the owner may edit."""
    group = await _get_group_or_404(session, group_id)
    if group.trainer_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ErrorCode.GROUP_NOT_OWNER,
        )

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(group, field, value)
    if update_data:
        group.updated_at = datetime.now(UTC).replace(tzinfo=None)

    session.add(group)
    await session.commit()
    await session.refresh(group)
    logger.info("Group %s updated; fields: %s", group_id, ",".join(update_data) or "none")
    return (await _serialize_groups(session, [group], user_id))[0]


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(
    group_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
    daily: DailyService = Depends(get_daily_service),
):
    """Soft-delete a group and cascade to its workshops. Only the owner may delete."""
    group = await _get_group_or_404(session, group_id)
    if group.trainer_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ErrorCode.GROUP_NOT_OWNER,
        )

    now = datetime.now(UTC).replace(tzinfo=None)

    # Cascade: soft-delete every non-deleted workshop in this group and notify
    # enrolled users. Daily.co room cleanup is best-effort — failures are logged
    # but do not abort the group deletion.
    workshops = list(
        (
            await session.exec(
                select(Workshop).where(
                    Workshop.group_id == group_id,
                    Workshop.deleted_at.is_(None),
                )
            )
        ).all()
    )

    live = [
        w for w in workshops
        if w.start_time <= now < w.start_time + timedelta(minutes=w.duration_minutes)
    ]
    if live:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ErrorCode.GROUP_HAS_LIVE_WORKSHOP,
        )

    for workshop in workshops:
        workshop.deleted_at = now
        await create_workshop_cancelled_notifications(session, workshop=workshop)
        if workshop.video_room_id:
            try:
                await daily.delete_room(workshop.video_room_id)
            except DailyServiceError as exc:
                logger.warning(
                    "Daily room cleanup failed for workshop %s during group %s deletion: %s",
                    workshop.id,
                    group_id,
                    exc.detail,
                )

    group.deleted_at = now
    member_ids = await create_group_deleted_notifications(session, group=group)
    session.add_all(workshops)
    session.add(group)
    await session.commit()
    logger.info(
        "Group %s soft-deleted by %s; %d workshops cascaded, %d member notifications created",
        group_id,
        user_id,
        len(workshops),
        len(member_ids),
    )

    if member_ids:
        try:
            await send_push_to_users(
                session,
                user_ids=member_ids,
                message=PushMessage(
                    title="Group deleted",
                    body=f'"{group.title}" has been deleted.',
                    data={"group_id": str(group_id), "type": "deleted"},
                ),
            )
        except Exception:
            logger.exception("Push dispatch failed for deleted group %s", group_id)


@router.post("/{group_id}/subscribe", response_model=GroupRead)
async def subscribe_group(
    group_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
):
    """Subscribe the caller to a group. Idempotent — re-subscribing is a no-op."""
    group = await _get_group_or_404(session, group_id)
    if group.trainer_id == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorCode.GROUP_SUBSCRIBE_OWN,
        )

    user = await session.get(User, user_id)
    membership_role = (
        "trainer_subscriber" if user and user.role == UserRole.TRAINER else "member"
    )

    existing = (
        await session.exec(
            select(GroupMembership).where(
                GroupMembership.user_id == user_id,
                GroupMembership.group_id == group_id,
            )
        )
    ).first()
    if existing is None:
        session.add(
            GroupMembership(group_id=group_id, user_id=user_id, role=membership_role)
        )
        try:
            await session.commit()
        except IntegrityError:
            # Race with a concurrent subscribe — UNIQUE constraint serializes us.
            await session.rollback()
        else:
            logger.info("User %s subscribed to group %s", user_id, group_id)

    return (await _serialize_groups(session, [group], user_id))[0]


@router.post("/{group_id}/unsubscribe", status_code=status.HTTP_204_NO_CONTENT)
async def unsubscribe_group(
    group_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
):
    """Unsubscribe the caller. Idempotent — no-op when not subscribed."""
    membership = (
        await session.exec(
            select(GroupMembership).where(
                GroupMembership.user_id == user_id,
                GroupMembership.group_id == group_id,
            )
        )
    ).first()
    if membership is not None:
        await session.delete(membership)
        await session.commit()
        logger.info("User %s unsubscribed from group %s", user_id, group_id)


@router.get("/{group_id}/members", response_model=list[GroupMemberRead])
async def list_group_members(
    group_id: UUID,
    session: AsyncSession = Depends(get_db_session),
):
    """List a group's subscribers."""
    await _get_group_or_404(session, group_id)
    statement = (
        select(GroupMembership, User)
        .join(User, GroupMembership.user_id == User.id)
        .where(GroupMembership.group_id == group_id)
        .order_by(GroupMembership.joined_at)
    )
    rows = (await session.exec(statement)).all()
    return [
        GroupMemberRead(
            id=m.id, user_id=m.user_id, full_name=u.full_name, role=m.role
        )
        for m, u in rows
    ]


@router.delete(
    "/{group_id}/members/{member_user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_group_member(
    group_id: UUID,
    member_user_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
):
    """Remove a member from a group. Only the owner may remove members."""
    group = await _get_group_or_404(session, group_id)
    if group.trainer_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ErrorCode.GROUP_NOT_OWNER,
        )
    membership = (
        await session.exec(
            select(GroupMembership).where(
                GroupMembership.user_id == member_user_id,
                GroupMembership.group_id == group_id,
            )
        )
    ).first()
    if membership is not None:
        await session.delete(membership)
        await session.commit()
        logger.info("Member %s removed from group %s by %s", member_user_id, group_id, user_id)


@router.get("/{group_id}/workshops", response_model=list[WorkshopRead])
async def list_group_workshops(
    group_id: UUID,
    caller_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
):
    """List the workshops attached to a group. Members and the owner only."""
    group = await _get_group_or_404(session, group_id)
    if group.trainer_id != caller_id:
        membership = (
            await session.exec(
                select(GroupMembership.id).where(
                    GroupMembership.user_id == caller_id,
                    GroupMembership.group_id == group_id,
                )
            )
        ).first()
        if membership is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=ErrorCode.GROUP_NOT_MEMBER,
            )
    statement = (
        select(Workshop)
        .where(Workshop.group_id == group_id, Workshop.deleted_at.is_(None))
        .options(selectinload(Workshop.tags))
        .order_by(Workshop.start_time)
    )
    rows = (await session.exec(statement)).all()
    return await _serialize_workshops(session, list(rows), caller_id)
