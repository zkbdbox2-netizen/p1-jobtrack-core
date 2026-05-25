from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

# --- Engine ---
# The engine manages the connection pool to PostgreSQL.
# pool_pre_ping=True: before handing a connection to your code, SQLAlchemy
# runs a cheap "SELECT 1" to verify it's still alive. This handles the case
# where Postgres restarted or a network hiccup dropped idle connections.
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,      # when DEBUG=true, prints every SQL query — very useful for development
    pool_pre_ping=True,
    pool_size=10,             # max 10 simultaneous connections in the pool
    max_overflow=20,          # allow 20 more connections beyond pool_size under burst load
)

# --- Session factory ---
# async_sessionmaker creates AsyncSession instances.
# expire_on_commit=False: by default, SQLAlchemy expires all object attributes
# after a commit (to force a fresh DB read on next access). In async code,
# that "fresh read" would need to be awaited — which is annoying and easy to forget.
# Setting this to False means objects remain readable after commit.
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# --- FastAPI dependency ---
# Inject this into any route that needs a database session:
#   async def my_endpoint(db: AsyncSession = Depends(get_db)):
#
# The `async with` block ensures the session is always closed after the request,
# even if an exception is raised. The try/except handles rollback on errors.
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
