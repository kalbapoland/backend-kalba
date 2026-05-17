from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.security import get_current_user_id
from app.db import get_db_session
from app.services.hashtags import suggest_tags

router = APIRouter(prefix="/tags", tags=["tags"])


@router.get("/suggest", response_model=list[str])
async def suggest_tag_names(
    q: str = Query(min_length=1, max_length=30, description="Prefix to match"),
    limit: int = Query(default=10, ge=1, le=20),
    _user_id: UUID = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
):
    """Autocomplete tag names by prefix, sorted by popularity (most-used first).

    Used by the workshop description editor when the user is typing a hashtag.
    Names are returned in their canonical (lowercased, NFC) form.
    """
    return await suggest_tags(session, q, limit)
