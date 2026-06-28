import logging
import math
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
    VideoBudgetStatus,
    WorkshopParticipant,
    WorkshopRules,
)
from app.models.workshop import Workshop
from app.services.daily import DailyService, DailyServiceError, get_daily_service
from app.services.video_budget import (
    budget_status,
    release_reservation,
    reserve_seat,
    settle_session,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/video", tags=["video"])


async def _get_active_workshop_or_404(
    session: AsyncSession,
    workshop_id: UUID,
) -> Workshop:
    workshop = await session.get(Workshop, workshop_id)
    if workshop is None or workshop.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Workshop not found")
    return workshop


@router.post("/workshops/{workshop_id}/join", response_model=JoinResponse)
async def join_workshop(
    workshop_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    daily: DailyService = Depends(get_daily_service),
):
    """Request a meeting token to join a workshop video call."""
    logger.info(
        "Join workshop request received (workshop=%s, user=%s)", workshop_id, user_id
    )

    # 1. Load workshop
    workshop = await _get_active_workshop_or_404(session, workshop_id)

    # 2. Determine role (needed before time check so host can join early)
    is_host = user_id == workshop.trainer_id
    role = ParticipantRole.HOST if is_host else ParticipantRole.PARTICIPANT

    # 3. Time window check (host can join anytime; participants 5 min early, up to 10 min after end)
    now = datetime.now(UTC).replace(tzinfo=None)
    if not is_host:
        earliest_join = workshop.start_time - timedelta(minutes=5)
        latest_join = workshop.start_time + timedelta(
            minutes=workshop.duration_minutes + 10
        )
        if now < earliest_join:
            raise HTTPException(status_code=403, detail="Workshop has not started yet")
        if now > latest_join:
            raise HTTPException(status_code=403, detail="Workshop has ended")

        # 3.1. Re-join cooldown: a participant removed by the host cannot rejoin
        # for a short window (gives the trainer time to act). Checked before the
        # budget reservation so a blocked join never consumes participant-minutes.
        cooldown = settings.workshop_kick_cooldown_seconds
        if cooldown > 0:
            kicked_stmt = select(WorkshopParticipant.kicked_at).where(
                WorkshopParticipant.workshop_id == workshop_id,
                WorkshopParticipant.user_id == user_id,
            )
            kicked_at = (await session.exec(kicked_stmt)).first()
            if kicked_at is not None:
                elapsed = (now - kicked_at).total_seconds()
                if elapsed < cooldown:
                    retry_after = int(cooldown - elapsed) + 1
                    logger.info(
                        "Join blocked by kick cooldown (workshop=%s, user=%s, retry_after=%ss)",
                        workshop_id,
                        user_id,
                        retry_after,
                    )
                    raise HTTPException(
                        status_code=403,
                        detail="You were removed from this call. Please wait a moment before rejoining.",
                        headers={"Retry-After": str(retry_after)},
                    )

    # 3.5. Daily.co budget gate — never cross from the free tier into paid
    # usage. Reserve this join's worst-case participant-minutes up front; if it
    # would exceed the cap, refuse the token (applies to host and participants).
    reservation = await reserve_seat(session, settings, workshop, user_id, now=now)
    if not reservation.allowed:
        logger.warning(
            "Join blocked by video budget (workshop=%s, user=%s, used=%s, est=%s, cap=%s)",
            workshop_id,
            user_id,
            reservation.used_minutes,
            reservation.estimate_minutes,
            reservation.cap_minutes,
        )
        raise HTTPException(
            status_code=503,
            detail="Video is temporarily unavailable due to monthly usage limits. Please try again later.",
        )

    # 4/5. Capacity check + participant upsert.
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
        # Cooldown has passed (we got here), so clear the kick marker.
        existing.kicked_at = None
        session.add(existing)

    await session.commit()

    # 6. Ensure Daily room exists (create only on first join)
    if not workshop.video_room_id:
        room_name = f"kalba-{workshop.id}"
        try:
            await daily.create_room(
                name=room_name,
                max_participants=workshop.max_participants,
                start_time=workshop.start_time,
                duration_minutes=workshop.duration_minutes,
            )
        except DailyServiceError as exc:
            logger.error("Failed to create Daily room on join: %s", exc.detail)
            if reservation.created_new and reservation.reservation_id:
                await release_reservation(session, reservation.reservation_id)
            raise HTTPException(status_code=502, detail="Video service unavailable")

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
        if reservation.created_new and reservation.reservation_id:
            await release_reservation(session, reservation.reservation_id)
        raise HTTPException(status_code=502, detail="Video service unavailable")

    room_url = f"https://{settings.daily_domain}/{workshop.video_room_id}"

    logger.info(
        "Join token issued for workshop %s (user=%s, role=%s)",
        workshop_id,
        user_id,
        role.value,
    )

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
async def daily_webhook(
    request: Request,
    settings: Settings = Depends(get_settings),
    daily: DailyService = Depends(get_daily_service),
    session: AsyncSession = Depends(get_db_session),
):
    """Receive Daily.co webhook events.

    MVP: log and acknowledge. Full enforcement (kick on camera-off
    violations) is a future enhancement.
    """
    payload_body = await request.body()
    payload = await request.json()

    # Daily sends an unsigned probe payload during webhook creation/update.
    if payload == {"test": "test"}:
        logger.info("Daily webhook probe acknowledged")
        return {"status": "ok"}

    if not settings.daily_webhook_secret:
        logger.error("Daily webhook secret is not configured")
        raise HTTPException(status_code=503, detail="Webhook not configured")

    signature = request.headers.get("x-webhook-signature", "")
    timestamp = request.headers.get("x-webhook-timestamp", "")
    is_valid_signature = bool(
        signature and timestamp
    ) and daily.verify_webhook_signature(
        payload_body=payload_body,
        signature=signature,
        timestamp=timestamp,
        webhook_secret=settings.daily_webhook_secret,
    )

    if not is_valid_signature:
        logger.warning("Rejected Daily webhook due to invalid signature")
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    logger.info("Daily webhook signature verified")

    event = payload.get("event") or payload.get("type") or "unknown"
    logger.info("Daily webhook event: %s", event)

    # Reconcile real usage: when a participant leaves, replace their worst-case
    # reservation with the minutes actually spent, freeing the unused budget.
    if event == "participant.left":
        await _reconcile_participant_left(payload, session)

    logger.info("Daily webhook processed successfully")
    return {"status": "ok"}


async def _reconcile_participant_left(
    payload: dict, session: AsyncSession
) -> None:
    """Settle a usage reservation from a Daily `participant.left` event."""
    data = payload.get("payload", payload)
    room = data.get("room") or data.get("room_name")
    user_id_raw = data.get("user_id")
    duration = data.get("duration")  # seconds spent in the call

    if not room or user_id_raw is None or duration is None:
        logger.info("participant.left missing room/user_id/duration; skipping settle")
        return

    # Room names are "kalba-{workshop_id}".
    if not room.startswith("kalba-"):
        return
    try:
        workshop_id = UUID(room[len("kalba-"):])
        user_id = UUID(str(user_id_raw))
    except (ValueError, AttributeError):
        logger.info("participant.left could not parse ids (room=%s, user=%s)", room, user_id_raw)
        return

    actual_minutes = max(1, math.ceil(float(duration) / 60))
    settled = await settle_session(session, workshop_id, user_id, actual_minutes)
    logger.info(
        "participant.left settle (workshop=%s, user=%s, minutes=%s, matched=%s)",
        workshop_id,
        user_id,
        actual_minutes,
        settled,
    )


@router.get("/budget", response_model=VideoBudgetStatus)
async def get_video_budget(
    _user_id: UUID = Depends(get_current_user_id),  # auth gate only
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
):
    """Current participant-minute usage vs the cap (for monitoring)."""
    return await budget_status(session, settings)


@router.get("/workshops/{workshop_id}/rules", response_model=RulesRead)
async def get_workshop_rules(
    workshop_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
):
    """Get current workshop rules including live host-enforced state."""
    logger.info(
        "Fetching workshop rules (workshop=%s, user=%s)",
        workshop_id,
        user_id,
    )
    workshop = await session.get(Workshop, workshop_id)
    if workshop is None or workshop.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Workshop not found")

    rules_stmt = select(WorkshopRules).where(WorkshopRules.workshop_id == workshop_id)
    rules_row = (await session.exec(rules_stmt)).first()

    logger.info("Workshop rules returned for workshop %s", workshop_id)

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
    logger.info(
        "Host action request received (workshop=%s, user=%s, action=%s)",
        workshop_id,
        user_id,
        body.action.value,
    )
    workshop = await _get_active_workshop_or_404(session, workshop_id)
    if user_id != workshop.trainer_id:
        raise HTTPException(
            status_code=403, detail="Only the host can perform this action"
        )

    # Targeted removal: authorize, record the kick, and audit. The actual
    # ejection is performed by the host's owner client (Daily updateParticipant
    # eject) — Daily has no server-side eject — so we don't broadcast here. We do
    # stamp kicked_at so join_workshop can enforce a short re-join cooldown.
    if body.action == HostActionType.REMOVE_PARTICIPANT:
        if body.target_user_id is None:
            raise HTTPException(
                status_code=422, detail="target_user_id is required to remove a participant"
            )
        if body.target_user_id == workshop.trainer_id:
            raise HTTPException(
                status_code=400, detail="Host cannot remove themselves"
            )

        now = datetime.now(UTC).replace(tzinfo=None)
        target_stmt = select(WorkshopParticipant).where(
            WorkshopParticipant.workshop_id == workshop_id,
            WorkshopParticipant.user_id == body.target_user_id,
        )
        target = (await session.exec(target_stmt)).first()
        if target is None:
            target = WorkshopParticipant(
                user_id=body.target_user_id,
                workshop_id=workshop_id,
                role=ParticipantRole.PARTICIPANT,
            )
        target.kicked_at = now
        session.add(target)
        await session.commit()

        logger.info(
            "Host removed participant (workshop=%s, host=%s, target=%s)",
            workshop_id,
            user_id,
            body.target_user_id,
        )
        return HostActionResponse(
            status="accepted",
            action=body.action,
            broadcast_sent=False,
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
