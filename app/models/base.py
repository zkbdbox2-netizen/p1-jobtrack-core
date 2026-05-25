import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """
    Base class for all SQLAlchemy models.
    Every model must inherit from this (directly or indirectly).
    It registers the model with SQLAlchemy's metadata, which Alembic
    reads to generate migrations.
    """
    pass


class TimestampMixin:
    """
    Adds created_at and updated_at columns to any model.

    These are standard on virtually every production table — they tell you
    when a row was created and when it was last changed without needing
    to look at application logs.

    SQLAlchemy handles setting these automatically:
    - created_at: set on INSERT, never changed again
    - updated_at: set on INSERT and updated on every UPDATE
    """
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class SoftDeleteMixin:
    """
    Adds soft delete support to any model via a deleted_at column.

    WHY soft delete instead of hard delete?
    - Recoverability: if a user deletes a job application by accident, it can be restored
    - Audit trail: you can see when something was deleted, not just that it's gone
    - No cascade ordering: hard deleting a Job means carefully deleting Notes,
      Contacts, Stages first (or setting up ON DELETE CASCADE correctly).
      Soft delete sidesteps all of that.

    HOW it works:
    - "Deleted" rows have deleted_at = some timestamp
    - "Live" rows have deleted_at = NULL
    - All queries in the service layer add WHERE deleted_at IS NULL
    - The deleted_at column is indexed because we filter on it in every query

    TRADEOFF: Tables grow over time with "deleted" rows.
    Mitigation: a periodic cleanup job (run nightly) can hard-delete rows
    where deleted_at is older than 90 days. Document this in DESIGN.md.
    """
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        index=True,
    )

    @property
    def is_deleted(self) -> bool:
        """Convenience property — use this instead of checking deleted_at directly."""
        return self.deleted_at is not None

    def soft_delete(self) -> None:
        """Mark this row as deleted. Call session.commit() after to persist."""
        self.deleted_at = datetime.now(timezone.utc)

    def restore(self) -> None:
        """Un-delete this row. Call session.commit() after to persist."""
        self.deleted_at = None


class TenantMixin:
    """
    Adds tenant_id to any model for row-level multi-tenancy.

    WHY row-level isolation?
    All tenants share the same tables. Every row has a tenant_id column
    that identifies which tenant owns it. Every query in the service layer
    includes WHERE tenant_id = <current_tenant_id>.

    This is enforced at the service layer via FastAPI dependency injection:
    the current user's tenant_id is injected into every service call,
    and service functions always filter by it. No route can accidentally
    return another tenant's data as long as the service layer is correct.

    WHEN would you change this?
    - A customer requires contractual data separation (enterprise deals)
    - HIPAA / SOC2 data residency requirements for healthcare or finance
    - Extreme per-tenant row counts causing query performance issues

    In those cases you'd migrate to schema-per-tenant. The column design
    here doesn't change — you'd add a migration to move rows into separate schemas.
    Document this upgrade path in DESIGN.md.
    """
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,   # indexed because we filter by tenant_id on every query
    )
