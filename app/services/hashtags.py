"""Hashtag parsing and persistence helpers.

Frontend and backend must agree on the parsing rules — see
`frontend/src/lib/hashtags.ts`. Any change here requires a matching change there.
"""

import re
import unicodedata
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.tag import Tag, WorkshopTag

MAX_TAGS_PER_WORKSHOP = 5
MIN_TAG_LENGTH = 2
MAX_TAG_LENGTH = 30

# `\w` with re.UNICODE matches letters (incl. polish chars), digits and underscore.
# Negative lookbehind: '#' must not follow a word char (so `foo#bar` isn't a tag).
# Negative lookahead: the captured run of word chars must end on a non-word
# boundary, which excludes tags exceeding MAX_TAG_LENGTH.
_HASHTAG_RE = re.compile(
    rf"(?<!\w)#(\w{{{MIN_TAG_LENGTH},{MAX_TAG_LENGTH}}})(?!\w)",
    re.UNICODE,
)


def extract_hashtags(text: str | None) -> list[str]:
    """Return up to MAX_TAGS_PER_WORKSHOP normalized hashtag names from text.

    Normalization: NFC unicode + casefold. Duplicates within the input are
    collapsed; original order is preserved.
    """
    if not text:
        return []

    seen: set[str] = set()
    result: list[str] = []
    for match in _HASHTAG_RE.finditer(text):
        raw = match.group(1)
        normalized = unicodedata.normalize("NFC", raw).casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
        if len(result) >= MAX_TAGS_PER_WORKSHOP:
            break
    return result


async def upsert_tags(session: AsyncSession, names: list[str]) -> list[Tag]:
    """Return Tag rows for each name, creating missing ones.

    Uses INSERT ... ON CONFLICT DO NOTHING to tolerate concurrent inserts.
    Output order matches input order.
    """
    if not names:
        return []

    stmt = (
        pg_insert(Tag)
        .values([{"name": n} for n in names])
        .on_conflict_do_nothing(index_elements=["name"])
    )
    await session.execute(stmt)

    result = await session.exec(select(Tag).where(Tag.name.in_(names)))
    rows = result.all()
    by_name = {tag.name: tag for tag in rows}
    return [by_name[n] for n in names if n in by_name]


async def set_workshop_tags(
    session: AsyncSession,
    workshop_id: UUID,
    description: str | None,
) -> list[str]:
    """Replace the workshop's tag set with hashtags parsed from `description`.

    Always deletes existing `workshop_tag` link rows before inserting, so the
    set on disk matches the description exactly (empty description → no tags).
    Does NOT mutate the ORM `Workshop.tags` collection — callers must reload
    the workshop with `selectinload(Workshop.tags)` before serializing.
    Returns the canonical list of tag names that were persisted, in order.
    """
    await session.execute(
        delete(WorkshopTag).where(WorkshopTag.workshop_id == workshop_id)
    )

    tag_names = extract_hashtags(description)
    if not tag_names:
        return []

    tags = await upsert_tags(session, tag_names)
    for tag in tags:
        session.add(WorkshopTag(workshop_id=workshop_id, tag_id=tag.id))
    return tag_names
