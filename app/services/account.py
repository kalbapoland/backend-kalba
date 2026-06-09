"""Account lifecycle operations — currently irreversible account deletion.

Apple App Store Guideline 5.1.1(v) requires apps with account creation to let
users delete their account (and associated data) from within the app. This
module implements that cascade. FKs in this schema have no ``ON DELETE CASCADE``,
so every row referencing ``user.id`` must be removed before the user row, all in
one transaction.
"""

import logging
from uuid import UUID

from sqlalchemy import delete as sa_delete
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.auth import PasswordResetToken, RefreshToken
from app.models.group import Group, GroupMembership
from app.models.my_kalba import UserGoal, UserNotification
from app.models.notification import PushToken
from app.models.tag import WorkshopTag
from app.models.user import TrainerProfile, User
from app.models.video import VideoUsageSession, WorkshopParticipant, WorkshopRules
from app.models.workshop import Workshop, WorkshopEnrollment

logger = logging.getLogger(__name__)


async def delete_user_account(user_id: UUID, session: AsyncSession) -> None:
    """Irreversibly delete a user and everything that references them.

    Trainer-owned groups and workshops are hard-deleted along with the account
    (workshops in a group always belong to that group's owner, so deleting the
    owner's groups never orphans another trainer's workshops). Commits on
    success; the caller's request session rolls back if this raises.
    """
    # --- Trainer-owned workshops and their dependents ---
    owned_workshop_ids = (
        await session.exec(select(Workshop.id).where(Workshop.trainer_id == user_id))
    ).all()
    if owned_workshop_ids:
        await session.execute(
            sa_delete(WorkshopTag).where(WorkshopTag.workshop_id.in_(owned_workshop_ids))
        )
        await session.execute(
            sa_delete(WorkshopParticipant).where(
                WorkshopParticipant.workshop_id.in_(owned_workshop_ids)
            )
        )
        await session.execute(
            sa_delete(WorkshopEnrollment).where(
                WorkshopEnrollment.workshop_id.in_(owned_workshop_ids)
            )
        )
        await session.execute(
            sa_delete(WorkshopRules).where(
                WorkshopRules.workshop_id.in_(owned_workshop_ids)
            )
        )
        await session.execute(
            sa_delete(VideoUsageSession).where(
                VideoUsageSession.workshop_id.in_(owned_workshop_ids)
            )
        )
        await session.execute(
            sa_delete(Workshop).where(Workshop.id.in_(owned_workshop_ids))
        )

    # --- Trainer-owned groups and their memberships ---
    owned_group_ids = (
        await session.exec(select(Group.id).where(Group.trainer_id == user_id))
    ).all()
    if owned_group_ids:
        await session.execute(
            sa_delete(GroupMembership).where(
                GroupMembership.group_id.in_(owned_group_ids)
            )
        )
        await session.execute(sa_delete(Group).where(Group.id.in_(owned_group_ids)))

    # --- The user's own personal rows ---
    await session.execute(
        sa_delete(RefreshToken).where(RefreshToken.user_id == user_id)
    )
    await session.execute(
        sa_delete(PasswordResetToken).where(PasswordResetToken.user_id == user_id)
    )
    await session.execute(sa_delete(PushToken).where(PushToken.user_id == user_id))
    await session.execute(
        sa_delete(WorkshopEnrollment).where(WorkshopEnrollment.user_id == user_id)
    )
    await session.execute(
        sa_delete(WorkshopParticipant).where(WorkshopParticipant.user_id == user_id)
    )
    await session.execute(
        sa_delete(VideoUsageSession).where(VideoUsageSession.user_id == user_id)
    )
    await session.execute(
        sa_delete(GroupMembership).where(GroupMembership.user_id == user_id)
    )
    await session.execute(sa_delete(UserGoal).where(UserGoal.user_id == user_id))
    await session.execute(
        sa_delete(UserNotification).where(UserNotification.user_id == user_id)
    )
    await session.execute(
        sa_delete(TrainerProfile).where(TrainerProfile.user_id == user_id)
    )

    # --- Finally, the user ---
    await session.execute(sa_delete(User).where(User.id == user_id))

    await session.commit()
    logger.info("Deleted user account %s and all associated data", user_id)
