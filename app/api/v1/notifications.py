import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.errors import ErrorCode
from app.core.rate_limit import enforce_push_token_rate_limit
from app.core.security import get_current_user_id
from app.db import get_db_session
from app.models.notification import PushTokenRegister, PushTokenUnregister
from app.services.notifications import register_push_token, unregister_push_token

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/users/me/push-tokens",
    tags=["notifications"],
    dependencies=[Depends(enforce_push_token_rate_limit)],
)


@router.put("", status_code=status.HTTP_204_NO_CONTENT)
async def register(
    body: PushTokenRegister,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    """Register or refresh a push token for the current user.

    Idempotent: same payload may be sent on every app launch. On conflict
    the token is reassigned to the current user (device-keyed ownership).

    Returns: 204 on success, 422 on invalid Expo token format, 401 if
    unauthenticated, 429 if the per-user rate limit is exceeded, 503 if
    push token persistence is temporarily unavailable.
    """
    try:
        await register_push_token(
            session, user_id=user_id, token=body.token, platform=body.platform
        )
    except SQLAlchemyError as exc:
        logger.exception("Push token register failed for user %s", user_id, exc_info=exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=ErrorCode.PUSH_TOKEN_SERVICE_UNAVAILABLE,
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/unregister", status_code=status.HTTP_204_NO_CONTENT)
async def unregister(
    body: PushTokenUnregister,
    user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    """Unregister a push token (e.g. on explicit logout).

    Token is passed in the request body, not the URL path, to keep it out
    of access logs. Scoped to the current user — knowing another user's
    token does not let you remove their row. Idempotent: 204 even when
    the token does not exist.

    Returns: 204 always (no info leakage about token existence), 422 on
    invalid Expo token format, 401 if unauthenticated, 429 if the
    per-user rate limit is exceeded, 503 if token persistence is
    temporarily unavailable.
    """
    try:
        await unregister_push_token(session, user_id=user_id, token=body.token)
    except SQLAlchemyError as exc:
        logger.exception("Push token unregister failed for user %s", user_id, exc_info=exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=ErrorCode.PUSH_TOKEN_SERVICE_UNAVAILABLE,
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
