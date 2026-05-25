import enum
import uuid

from sqlalchemy import Boolean, Enum as SAEnum, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin


class UserRole(str, enum.Enum):
    """
    User roles for RBAC (Role-Based Access Control).

    Using str, enum.Enum means the values serialize to plain strings
    ("admin", "user") in JSON responses — no extra conversion needed.

    admin: can manage other users, view all jobs within their tenant
    user:  standard role, manages their own job applications
    """
    admin = "admin"
    user = "user"


class User(Base, TimestampMixin, SoftDeleteMixin):
    """
    The User model represents an authenticated identity.

    Note: User intentionally does NOT inherit TenantMixin.
    That mixin adds a tenant_id column pointing to a *separate* tenants table.
    Here, the user IS the tenant — their tenant_id is their own id.

    This design means:
    - Today: every user is a single-person tenant (personal job tracker)
    - Future: swap tenant_id to point to a shared Tenant record to support teams
    - No schema migration needed for that change — just a data migration

    Columns inherited from mixins:
    - created_at, updated_at  (TimestampMixin)
    - deleted_at              (SoftDeleteMixin)
    """
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,   # auto-generate UUID on insert
    )

    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,           # fast lookup by email (used on every login)
    )

    hashed_password: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        # We store the bcrypt hash, never the plaintext password.
        # passlib handles hashing and verification.
    )

    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, name="userrole"),   # creates a PostgreSQL ENUM type
        default=UserRole.user,
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        # Inactive users can't log in but their data is preserved.
        # This is different from soft delete — soft delete is for "removed from the system",
        # is_active=False is for "temporarily suspended".
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
        # Set to self.id on creation (see user service).
        # In the future this would point to a Tenant.id instead.
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email} role={self.role}>"
