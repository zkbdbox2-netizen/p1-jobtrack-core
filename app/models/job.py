import enum
import uuid

from sqlalchemy import Date, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin


class JobStage(str, enum.Enum):
    """
    WHERE you are in the hiring pipeline.

    Stages are ordered — wishlist is pre-application, offer is the final
    active stage. A job moves forward through stages as the process progresses.

    Using StrEnum means JobStage.onsite == "onsite" is True, so values
    serialise cleanly to JSON and are readable in raw SQL.
    """
    wishlist     = "wishlist"
    applied      = "applied"
    phone_screen = "phone_screen"
    onsite       = "onsite"       # covers all onsite / virtual onsite rounds
    offer        = "offer"


class JobOutcome(str, enum.Enum):
    """
    WHAT is happening at the current stage.

    Separating outcome from stage lets us express combinations like
    "frozen after onsite" or "rejected after offer" without an enum
    explosion. Any stage can pair with any outcome:

      stage=phone_screen + outcome=frozen  → ghosted after recruiter screen
      stage=onsite       + outcome=frozen  → no response after interviews
      stage=offer        + outcome=accepted → you took the job
      stage=onsite       + outcome=rejected → didn't pass the loop
    """
    active    = "active"      # process is ongoing — waiting or scheduled
    frozen    = "frozen"      # no response / hiring freeze / ghosted
    rejected  = "rejected"    # explicit rejection at this stage
    withdrawn = "withdrawn"   # you pulled out
    accepted  = "accepted"    # offer accepted — you're hired


class Job(TimestampMixin, SoftDeleteMixin, Base):
    """
    Core entity — one row per job application.

    Key design decisions:
    - tenant_id + id are the compound access pattern. Every query filters by
      tenant_id first (uses idx_jobs_tenant index), preventing cross-user
      data leaks without application-level join logic.
    - stage + outcome replace a single status enum. This expresses the full
      matrix (where × what) without a combinatorial enum explosion.
    - applied_date is nullable — a wishlist job hasn't been applied to yet.
      Cursor pagination handles NULLs via NULLS LAST.
    - salary stored as integers (whole dollars — precise enough for a tracker).
    - job_url stored as TEXT — some job board URLs exceed VARCHAR(255).
    """
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Core fields
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    company: Mapped[str] = mapped_column(String(255), nullable=False)

    stage: Mapped[JobStage] = mapped_column(
        Enum(JobStage, name="jobstage", create_type=True),
        nullable=False,
        default=JobStage.wishlist,
        server_default=JobStage.wishlist.value,
    )
    outcome: Mapped[JobOutcome] = mapped_column(
        Enum(JobOutcome, name="joboutcome", create_type=True),
        nullable=False,
        default=JobOutcome.active,
        server_default=JobOutcome.active.value,
    )

    # Optional enrichment fields
    job_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    salary_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    applied_date: Mapped[str | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ---------------------------------------------------------------------------
    # Indexes
    # ---------------------------------------------------------------------------
    __table_args__ = (
        # Primary access pattern: all queries start with tenant_id
        Index("idx_jobs_tenant", "tenant_id"),
        # Stage + outcome filter index — covers common list queries like
        # "show me all active applications" or "all frozen after onsite"
        Index("idx_jobs_tenant_stage_outcome", "tenant_id", "stage", "outcome"),
        # Cursor pagination sort key: (applied_date DESC, id ASC)
        Index("idx_jobs_tenant_cursor", "tenant_id", "applied_date", "id"),
    )
