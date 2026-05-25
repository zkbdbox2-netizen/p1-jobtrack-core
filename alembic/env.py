"""
Alembic environment configuration — async version.

Standard Alembic uses synchronous SQLAlchemy. Since we're using async SQLAlchemy,
we need to wrap the migration runner in asyncio.run(). This is boilerplate that
Alembic's async template generates, adapted for our settings pattern.

Two modes:
- "offline" mode: generates SQL scripts without connecting to the DB (useful for review)
- "online" mode:  connects to the DB and applies migrations directly (what we use)
"""
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings
from app.models.base import Base

# Import all models here so Alembic can detect them for --autogenerate.
# If a model isn't imported, Alembic won't know it exists and won't generate
# a migration for it. This is the most common "why didn't Alembic detect my model" gotcha.
from app.models.user import User  # noqa: F401
# Add future models here as you create them:
# from app.models.job import Job  # noqa: F401
# from app.models.company import Company  # noqa: F401

# Alembic Config object — provides access to alembic.ini values
config = context.config

# Set up Python logging from alembic.ini configuration
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadata from our Base — Alembic compares this against the live DB to detect changes
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    Offline mode: emit SQL to stdout instead of running it.
    Useful for reviewing what a migration will do before running it.
    Run with: alembic upgrade head --sql
    """
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """
    Online mode: connect to the DB and apply migrations.
    This is what `alembic upgrade head` runs.
    """
    connectable = create_async_engine(settings.database_url)

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
