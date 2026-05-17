"""Hashtag parsing and persistence helpers.

Frontend and backend must agree on the parsing rules — see
`frontend/src/lib/hashtags.ts`. Any change here requires a matching change there.
"""

import re
import unicodedata
from uuid import UUID

from sqlalchemy import delete, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.tag import Tag, WorkshopTag
from app.models.workshop import Workshop

MAX_TAGS_PER_WORKSHOP = 5
MIN_TAG_LENGTH = 2
MAX_TAG_LENGTH = 30
MAX_SUGGEST_LIMIT = 20

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


_LEADING_WORD_RUN_RE = re.compile(r"^\w*", re.UNICODE)


def normalize_tag_input(value: str) -> str:
    """Apply the same normalization as `extract_hashtags` to a single string.

    Strips a leading '#', NFC-normalizes, casefolds, then truncates at the
    first non-word character. Truncation enforces the `\\w`-only invariant of
    a tag name and incidentally drops LIKE wildcards (`%`, `_`) so a malicious
    or curious caller cannot smuggle them into the prefix search.
    """
    stripped = value.lstrip("#")
    normalized = unicodedata.normalize("NFC", stripped).casefold()
    match = _LEADING_WORD_RUN_RE.match(normalized)
    return match.group(0) if match else ""


async def suggest_tags(
    session: AsyncSession,
    prefix: str,
    limit: int,
) -> list[str]:
    """Return tag names starting with `prefix`, sorted by popularity desc.

    Popularity is the number of non-soft-deleted workshops referencing the tag.
    Ties break alphabetically. Orphan tags (no `workshop_tag` rows) and tags
    whose only referencing workshops were soft-deleted both still appear
    matching the prefix, with `usage=0` so they sort last. Prefix is normalized
    server-side; an empty prefix returns an empty list — we only autocomplete
    what the user is actively typing, never a "most-popular overall" list.
    """
    normalized = normalize_tag_input(prefix)
    if not normalized:
        return []

    bounded_limit = max(1, min(limit, MAX_SUGGEST_LIMIT))

    # LEFT JOIN through workshop_tag → workshop with a soft-delete filter so
    # tags whose only referencing workshops were deleted drop in popularity.
    usage = func.count(Workshop.id).label("usage")
    stmt = (
        select(Tag.name, usage)
        .join(WorkshopTag, WorkshopTag.tag_id == Tag.id, isouter=True)
        .join(
            Workshop,
            (Workshop.id == WorkshopTag.workshop_id) & (Workshop.deleted_at.is_(None)),
            isouter=True,
        )
        .where(Tag.name.like(f"{normalized}%"))
        .group_by(Tag.id, Tag.name)
        .order_by(usage.desc(), Tag.name.asc())
        .limit(bounded_limit)
    )
    result = await session.exec(stmt)
    return [row[0] for row in result.all()]


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
