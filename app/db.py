from collections.abc import AsyncGenerator
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import get_settings


def _prepare_async_url(url: str) -> tuple[str, dict]:
    """Convert a postgresql:// URL to postgresql+asyncpg://.

    Translates ``sslmode`` from the query string into asyncpg's ``ssl``
    connect arg (asyncpg does not accept ``sslmode``).

    Returns (url, connect_args) for ``create_async_engine``.
    """
    url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    parsed = urlparse(url)
    params = parse_qs(parsed.query)

    connect_args: dict = {}
    sslmode_values = params.pop("sslmode", None)
    if sslmode_values:
        sslmode = sslmode_values[0]
        if sslmode == "disable":
            connect_args["ssl"] = False

    cleaned_query = urlencode(params, doseq=True)
    clean_url = urlunparse(parsed._replace(query=cleaned_query))
    return clean_url, connect_args


_url, _connect_args = _prepare_async_url(get_settings().pg_url)

engine = create_async_engine(
    _url,
    echo=get_settings().debug,
    connect_args=_connect_args,
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db_session() -> AsyncGenerator[AsyncSession]:
    async with async_session() as session:
        yield session
