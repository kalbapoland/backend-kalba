import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import Settings, get_settings
from app.core.security import get_current_user_id
from app.db import get_db_session
from app.models.user import User
from app.models.video import (
    HostAction,
    HostActionResponse,
    HostActionType,
    JoinResponse,
    ParticipantRole,
    RulesRead,
    WorkshopParticipant,
    WorkshopRules,
)
from app.models.workshop import Workshop
from app.services.daily import DailyService, DailyServiceError, get_daily_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/video", tags=["video"])


@router.post("/workshops/{workshop_id}/join", response_model=JoinResponse)
async def join_workshop(
    workshop_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    daily: DailyService = Depends(get_daily_service),
):
    """Request a meeting token to join a workshop video call."""

    # 1. Load workshop
    workshop = await session.get(Workshop, workshop_id)
    if workshop is None:
        raise HTTPException(status_code=404, detail="Workshop not found")

    # 2. Time window check (5 min early, up to 10 min after end)
    now = datetime.now(UTC).replace(tzinfo=None)
    earliest_join = workshop.start_time - timedelta(minutes=5)
    latest_join = workshop.start_time + timedelta(
        minutes=workshop.duration_minutes + 10
    )
    if now < earliest_join:
        raise HTTPException(status_code=403, detail="Workshop has not started yet")
    if now > latest_join:
        raise HTTPException(status_code=403, detail="Workshop has ended")

    # 3. Determine role
    is_host = user_id == workshop.trainer_id
    role = ParticipantRole.HOST if is_host else ParticipantRole.PARTICIPANT

    # 4. Capacity check (skip for host)
    if not is_host:
        count_stmt = (
            select(func.count())
            .select_from(WorkshopParticipant)
            .where(
                WorkshopParticipant.workshop_id == workshop_id,
                WorkshopParticipant.role == ParticipantRole.PARTICIPANT,
            )
        )
        count = (await session.exec(count_stmt)).one()
        if count >= workshop.max_participants:
            raise HTTPException(status_code=403, detail="Workshop is full")

    # 5. Upsert participant record
    existing_stmt = select(WorkshopParticipant).where(
        WorkshopParticipant.user_id == user_id,
        WorkshopParticipant.workshop_id == workshop_id,
    )
    existing = (await session.exec(existing_stmt)).first()
    if existing is None:
        participant = WorkshopParticipant(
            user_id=user_id,
            workshop_id=workshop_id,
            role=role,
            joined_at=now,
        )
        session.add(participant)
    else:
        existing.joined_at = now
        session.add(existing)
    await session.commit()

    # 6. Ensure Daily room exists (created on first join)
    room_name = workshop.video_room_id or f"kalba-{workshop.id}"
    try:
        await daily.create_room(
            name=room_name,
            max_participants=workshop.max_participants,
            start_time=workshop.start_time,
            duration_minutes=workshop.duration_minutes,
        )
    except DailyServiceError as exc:
        # 409 / "already-exists" is fine — room was created by a previous join
        if "already exists" not in exc.detail:
            logger.error("Failed to create Daily room on join: %s", exc.detail)
            raise HTTPException(status_code=502, detail="Video service unavailable")
    if not workshop.video_room_id:
        workshop.video_room_id = room_name
        session.add(workshop)
        await session.commit()
        await session.refresh(workshop)

    # 7. Load rules (default values if none stored)
    rules_stmt = select(WorkshopRules).where(WorkshopRules.workshop_id == workshop_id)
    rules_row = (await session.exec(rules_stmt)).first()
    force_camera_on = rules_row.force_camera_on if rules_row else True
    force_mic_muted = rules_row.force_mic_muted_on_join if rules_row else True
    allow_unmute_after = rules_row.allow_unmute_after if rules_row else 0
    allow_camera_toggle = rules_row.allow_camera_toggle if rules_row else True
    all_muted = rules_row.all_muted if rules_row else False
    all_cameras_off = rules_row.all_cameras_off if rules_row else False

    # 8. Load user for display name
    user = await session.get(User, user_id)

    # 9. Generate Daily.co meeting token
    try:
        token = await daily.create_meeting_token(
            room_name=workshop.video_room_id,
            user_name=user.full_name or user.email,
            user_id=str(user_id),
            is_owner=is_host,
            exp_minutes=10,
            start_video_off=(not force_camera_on) or all_cameras_off,
            start_audio_off=force_mic_muted or all_muted,
        )
    except DailyServiceError as exc:
        logger.error("Failed to create meeting token: %s", exc.detail)
        raise HTTPException(status_code=502, detail="Video service unavailable")

    room_url = f"https://{settings.daily_domain}/{workshop.video_room_id}"

    return JoinResponse(
        token=token,
        room_url=room_url,
        role=role.value,
        rules=RulesRead(
            force_camera_on=force_camera_on,
            force_mic_muted_on_join=force_mic_muted,
            allow_unmute_after=allow_unmute_after,
            allow_camera_toggle=allow_camera_toggle,
            all_muted=all_muted,
            all_cameras_off=all_cameras_off,
        ),
    )


@router.post("/webhooks/daily", status_code=200)
async def daily_webhook(request: Request):
    """Receive Daily.co webhook events.

    MVP: log and acknowledge. Full enforcement (kick on camera-off
    violations) is a future enhancement.
    """
    payload = await request.json()
    event = payload.get("event", "unknown")
    logger.info("Daily webhook event: %s", event)
    return {"status": "ok"}


@router.get("/workshops/{workshop_id}/rules", response_model=RulesRead)
async def get_workshop_rules(
    workshop_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
):
    """Get current workshop rules including live host-enforced state."""
    workshop = await session.get(Workshop, workshop_id)
    if workshop is None:
        raise HTTPException(status_code=404, detail="Workshop not found")

    rules_stmt = select(WorkshopRules).where(WorkshopRules.workshop_id == workshop_id)
    rules_row = (await session.exec(rules_stmt)).first()

    return RulesRead(
        force_camera_on=rules_row.force_camera_on if rules_row else True,
        force_mic_muted_on_join=rules_row.force_mic_muted_on_join
        if rules_row
        else True,
        allow_unmute_after=rules_row.allow_unmute_after if rules_row else 0,
        allow_camera_toggle=rules_row.allow_camera_toggle if rules_row else True,
        all_muted=rules_row.all_muted if rules_row else False,
        all_cameras_off=rules_row.all_cameras_off if rules_row else False,
    )


@router.post(
    "/workshops/{workshop_id}/host-action",
    response_model=HostActionResponse,
)
async def host_action(
    workshop_id: UUID,
    body: HostAction,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
    daily: DailyService = Depends(get_daily_service),
):
    """Host-only actions: mute/unmute all, cameras on/off all."""
    workshop = await session.get(Workshop, workshop_id)
    if workshop is None:
        raise HTTPException(status_code=404, detail="Workshop not found")
    if user_id != workshop.trainer_id:
        raise HTTPException(
            status_code=403, detail="Only the host can perform this action"
        )

    # Load or create rules
    rules_stmt = select(WorkshopRules).where(WorkshopRules.workshop_id == workshop_id)
    rules = (await session.exec(rules_stmt)).first()
    if rules is None:
        rules = WorkshopRules(workshop_id=workshop_id)
        session.add(rules)

    # Update live state
    action = body.action
    if action == HostActionType.MUTE_ALL:
        rules.all_muted = True
    elif action == HostActionType.UNMUTE_ALL:
        rules.all_muted = False
    elif action == HostActionType.CAMERAS_OFF_ALL:
        rules.all_cameras_off = True
    elif action == HostActionType.CAMERAS_ON_ALL:
        rules.all_cameras_off = False

    session.add(rules)
    await session.commit()

    # Broadcast app-message to the Daily room
    broadcast_sent = False
    if workshop.video_room_id:
        message_data = {
            "type": "host_control",
            "action": action.value,
            "timestamp": datetime.now(UTC).isoformat(),
            "from": "server",
        }
        try:
            await daily.send_app_message(
                room_name=workshop.video_room_id,
                data=message_data,
            )
            broadcast_sent = True
        except DailyServiceError as exc:
            logger.warning(
                "Failed to broadcast host action to room %s: %s",
                workshop.video_room_id,
                exc.detail,
            )

    logger.info(
        "Host action '%s' on workshop %s (broadcast_sent=%s)",
        action.value,
        workshop_id,
        broadcast_sent,
    )

    return HostActionResponse(
        status="accepted",
        action=action,
        broadcast_sent=broadcast_sent,
    )
