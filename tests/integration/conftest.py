import os

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.security import create_access_token
from app.db import _prepare_async_url, get_db_session
from app.main import app
from app.models.user import User, UserRole
import app.db as _app_db
import app.services.scheduler as _scheduler_module

_RAW_DB_URL = os.environ.get(
    "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/kalba_test"
)


@pytest.fixture
async def engine():
    url, connect_args = _prepare_async_url(_RAW_DB_URL)
    e = create_async_engine(url, connect_args=connect_args)
    try:
        async with e.begin() as conn:
            await conn.run_sync(SQLModel.metadata.drop_all)
            await conn.run_sync(SQLModel.metadata.create_all)
    except (OSError, SQLAlchemyError) as exc:
        await e.dispose()
        pytest.skip(f"PostgreSQL test database unavailable: {exc}")
    yield e
    await e.dispose()


@pytest.fixture
async def db_session(engine):
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest.fixture(autouse=True)
async def patch_app_async_session(engine):
    """Route module-level async_session calls to the test engine.

    scheduler.tick() and _claim_workshop() call app.db.async_session directly,
    bypassing FastAPI dependency injection. Without this patch they use a
    module-level engine whose asyncpg connections are bound to a different
    (already-closed) event loop when pytest-asyncio uses function-scoped loops,
    causing: InterfaceError: cannot perform operation: another operation is in progress
    """
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    original_db = _app_db.async_session
    original_scheduler = _scheduler_module.async_session

    _app_db.async_session = factory
    _scheduler_module.async_session = factory

    yield

    _app_db.async_session = original_db
    _scheduler_module.async_session = original_scheduler


@pytest.fixture
async def client(engine):
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _override():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = _override
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
async def trainer(db_session):
    user = User(
        email="trainer@test.com",
        full_name="Test Trainer",
        google_id="google-trainer-123",
        role=UserRole.TRAINER,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def regular_user(db_session):
    user = User(
        email="user@test.com",
        full_name="Test User",
        google_id="google-user-456",
        role=UserRole.USER,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
def trainer_token(trainer):
    return create_access_token(trainer.id)


@pytest.fixture
def user_token(regular_user):
    return create_access_token(regular_user.id)
