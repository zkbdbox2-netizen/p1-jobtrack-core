import uuid

import bcrypt as _bcrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserRole
from app.schemas.user import UserRegisterRequest

# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------
# Using bcrypt directly — no passlib wrapper.
# passlib 1.7.4 has known compatibility issues with bcrypt 4.x.
#
# bcrypt is intentionally slow (configurable work factor via rounds).
# This makes brute-force attacks expensive even if the DB is leaked.
# Never use MD5 or plain SHA for passwords — they hash millions of times
# per second, making brute-force trivial.


def hash_password(plain: str) -> str:
    """Hash a plaintext password with bcrypt. Returns a UTF-8 string for DB storage."""
    return _bcrypt.hashpw(plain.encode("utf-8"), _bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plaintext password against a stored bcrypt hash."""
    return _bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


# ---------------------------------------------------------------------------
# User service functions
# ---------------------------------------------------------------------------

async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    """Look up a user by email. Returns None if not found."""
    result = await db.execute(
        select(User)
        .where(User.email == email)
        .where(User.deleted_at.is_(None))   # soft delete filter — never return deleted users
    )
    return result.scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    """Look up a user by ID. Returns None if not found."""
    result = await db.execute(
        select(User)
        .where(User.id == user_id)
        .where(User.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def create_user(db: AsyncSession, data: UserRegisterRequest) -> User:
    """
    Create a new user account.

    Key decisions made here:
    1. Password is hashed before the User object is created — plaintext never touches the DB
    2. tenant_id is set to the user's own ID — each user is their own tenant for now.
       When team support is added, this becomes a FK to a separate Tenant table.
    3. Role defaults to UserRole.user — admins are promoted manually or via a seeder
    """
    existing = await get_user_by_email(db, data.email)
    if existing:
        raise ValueError("Email already registered")

    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        email=data.email,
        hashed_password=hash_password(data.password),
        role=UserRole.user,
        is_active=True,
        tenant_id=user_id,     # user is their own tenant — see comment above
    )
    db.add(user)
    await db.flush()           # write to DB within the transaction, but don't commit yet
                               # the route's get_db() dependency commits after yield
    return user
