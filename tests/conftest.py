"""
Shared pytest fixtures for the P1-JobTrack-Core test suite.

Architecture
------------
- Real Postgres: we use the same `jobtracker` database but wipe all rows
  between tests using table.delete(). This is simpler and more reliable
  than savepoints with asyncpg, and gives us real query plan coverage.

- Fake Redis: `fakeredis.FakeAsyncRedis` simulates Redis in-process.
  Refresh token rotation tests work identically against it, with no
  network overhead and no state leaking between tests.

- httpx AsyncClient with ASGITransport: hits real FastAPI routing,
  middleware, and dependency injection — the closest thing to a real
  HTTP request without actually binding a port.

- Dependency overrides: `get_db` and `get_redis` are replaced in every
  test client so all code under test uses our controlled fixtures.
"""
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.db.session import get_db
from app.dependencies import get_redis
from app.main import create_app
from app.models.base import Base
from app.models.job import Job   # noqa: F401 — registers Job with Base.metadata
from app.models.user import User  # noqa: F401 — registers User with Base.metadata


# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="session")
async def engine():
    """
    Session-scoped engine — tables are created once before all tests and
    dropped once after all tests complete.

    We use Base.metadata.create_all instead of Alembic here because:
    - Tests should be self-contained (no dependency on migration state)
    - create_all is fast and deterministic for the current model state
    - Alembic is tested implicitly via `make migrate` in CI
    """
    # NullPool: every checkout gets a brand-new connection that is closed
    # immediately on checkin.  This prevents asyncpg's
    # "another operation is in progress" error that occurs when the connection
    # pool hands the same underlying connection to both the test's session and
    # the clean_tables teardown fixture at the same time.
    _engine = create_async_engine(
        settings.database_url,
        echo=False,
        poolclass=NullPool,
    )
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield _engine
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await _engine.dispose()


@pytest_asyncio.fixture
async def db(engine) -> AsyncSession:
    """Function-scoped DB session for direct DB access in tests."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest_asyncio.fixture(autouse=True)
async def clean_tables(engine):
    """
    Wipe all rows after every test automatically (autouse=True).

    Runs teardown (after yield) so the test itself sees its own inserts,
    but the next test starts with a clean slate.

    Delete order matters — jobs references users via FK, so jobs first.
    """
    yield
    async with engine.begin() as conn:
        await conn.execute(Job.__table__.delete())
        await conn.execute(User.__table__.delete())


# ---------------------------------------------------------------------------
# Redis fixture
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def fake_redis():
    """
    In-memory fake Redis, isolated per test.

    fakeredis.FakeAsyncRedis is a drop-in for redis.asyncio.Redis.
    It runs entirely in-process — no network, no external state.
    We flush after each test just in case (though clean_tables handles
    user/job state, Redis holds refresh token JTIs independently).
    """
    import fakeredis
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    yield redis
    await redis.flushall()
    await redis.aclose()


# ---------------------------------------------------------------------------
# HTTP client fixture
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def client(db, fake_redis) -> AsyncClient:
    """
    httpx AsyncClient wired to the FastAPI app with test dependencies.

    Both get_db and get_redis are overridden so all code paths under test
    use the same session/redis as our fixtures — no hidden connections.
    """
    app = create_app()

    async def override_get_db():
        yield db

    async def override_get_redis():
        yield fake_redis

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_redis] = override_get_redis

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def registered_user(client) -> dict:
    """
    Register a test user and return their credentials + tokens.

    Returns: {"email": ..., "password": ..., "access_token": ..., "refresh_token": ...}
    """
    creds = {"email": "user@example.com", "password": "testpassword123"}
    resp = await client.post("/auth/register", json=creds)
    assert resp.status_code == 201, resp.text
    return {**creds, **resp.json()}


@pytest_asyncio.fixture
async def auth_headers(registered_user) -> dict:
    """Authorization header dict ready to pass to client requests."""
    return {"Authorization": f"Bearer {registered_user['access_token']}"}
