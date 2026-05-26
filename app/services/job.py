"""
Job CRUD service — all DB logic lives here, routes stay thin.

Cursor pagination design
------------------------
Sort order: applied_date DESC NULLS LAST, id ASC

The cursor encodes (applied_date, id) as a base64 JSON string.
Each page query asks:
  "give me rows where (applied_date, id) comes AFTER the cursor position"

For DESC applied_date this translates to:
  WHERE (applied_date < cursor_date)
     OR (applied_date = cursor_date AND id > cursor_id)
     OR (applied_date IS NULL AND cursor_date IS NULL AND id > cursor_id)

Why not offset pagination?
  Offset (LIMIT x OFFSET y) shifts under concurrent inserts — if a new job is
  added before your next page load, you see a duplicate or skip a row.
  Cursors are stable: you always resume from the exact last-seen position.
"""
import base64
import json
import uuid
from datetime import date

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job, JobOutcome, JobStage
from app.schemas.job import JobCreateRequest, JobUpdateRequest


# ---------------------------------------------------------------------------
# Cursor helpers
# ---------------------------------------------------------------------------

def _encode_cursor(applied_date: date | None, job_id: uuid.UUID) -> str:
    """Encode (applied_date, id) into a URL-safe base64 string."""
    payload = {
        "d": applied_date.isoformat() if applied_date else None,
        "i": str(job_id),
    }
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


def _decode_cursor(cursor: str) -> tuple[date | None, uuid.UUID]:
    """Decode a cursor string back to (applied_date, id). Raises ValueError on bad input."""
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        raw_date = payload["d"]
        applied_date = date.fromisoformat(raw_date) if raw_date else None
        job_id = uuid.UUID(payload["i"])
        return applied_date, job_id
    except Exception as exc:
        raise ValueError("Invalid cursor") from exc


# ---------------------------------------------------------------------------
# CRUD operations
# ---------------------------------------------------------------------------

async def list_jobs(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    limit: int = 20,
    cursor: str | None = None,
    stage: JobStage | None = None,
    outcome: JobOutcome | None = None,
) -> tuple[list[Job], str | None]:
    """
    Return a page of jobs for the tenant, plus a next_cursor (or None if last page).

    Filters:
    - tenant_id: always applied — row-level isolation
    - deleted_at IS NULL: soft delete filter
    - stage: optional filter (e.g. show only 'onsite' jobs)
    - outcome: optional filter (e.g. show only 'frozen' jobs)
    Both filters can be combined: stage=onsite&outcome=frozen = "frozen after onsite"

    Returns (jobs, next_cursor).
    """
    stmt = (
        select(Job)
        .where(Job.tenant_id == tenant_id)
        .where(Job.deleted_at.is_(None))
    )

    if stage is not None:
        stmt = stmt.where(Job.stage == stage)
    if outcome is not None:
        stmt = stmt.where(Job.outcome == outcome)

    # Apply cursor filter if provided
    if cursor:
        cursor_date, cursor_id = _decode_cursor(cursor)

        if cursor_date is not None:
            # Rows after this cursor in (applied_date DESC, id ASC) order:
            # earlier date, OR same date with later id, OR null-date rows (come last)
            stmt = stmt.where(
                or_(
                    Job.applied_date < cursor_date,
                    and_(Job.applied_date == cursor_date, Job.id > cursor_id),
                    Job.applied_date.is_(None),
                )
            )
        else:
            # Already in the NULL section — only rows with null date and later id
            stmt = stmt.where(
                and_(Job.applied_date.is_(None), Job.id > cursor_id)
            )

    # Sort: newest applied_date first, NULLs last, then id for stability
    stmt = stmt.order_by(
        Job.applied_date.desc().nulls_last(),
        Job.id.asc(),
    ).limit(limit + 1)   # fetch one extra to detect next page

    result = await db.execute(stmt)
    rows = list(result.scalars().all())

    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_cursor = _encode_cursor(last.applied_date, last.id)
    else:
        next_cursor = None

    return rows, next_cursor


async def get_job(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    job_id: uuid.UUID,
) -> Job | None:
    """Fetch a single job by ID, scoped to tenant. Returns None if not found or deleted."""
    result = await db.execute(
        select(Job)
        .where(Job.id == job_id)
        .where(Job.tenant_id == tenant_id)
        .where(Job.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def create_job(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: JobCreateRequest,
) -> Job:
    """Create a new job application record."""
    job = Job(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        title=data.title,
        company=data.company,
        stage=data.stage,
        outcome=data.outcome,
        job_url=str(data.job_url) if data.job_url else None,
        location=data.location,
        salary_min=data.salary_min,
        salary_max=data.salary_max,
        applied_date=data.applied_date,
        notes=data.notes,
    )
    db.add(job)
    await db.flush()
    return job


async def update_job(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    job_id: uuid.UUID,
    data: JobUpdateRequest,
) -> Job | None:
    """
    Partial update (PATCH) — only fields explicitly set in the request are changed.

    model_dump(exclude_unset=True) returns only the fields the client actually sent,
    not all fields with their defaults. A client sending {"outcome": "frozen"} won't
    accidentally null out the notes or salary fields.
    """
    job = await get_job(db, tenant_id, job_id)
    if job is None:
        return None

    updates = data.model_dump(exclude_unset=True)
    if "job_url" in updates and updates["job_url"] is not None:
        updates["job_url"] = str(updates["job_url"])

    for field, value in updates.items():
        setattr(job, field, value)

    await db.flush()
    return job


async def delete_job(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    job_id: uuid.UUID,
) -> bool:
    """
    Soft delete — sets deleted_at, never removes the row.
    Returns True if found and deleted, False if not found.
    """
    job = await get_job(db, tenant_id, job_id)
    if job is None:
        return False

    job.soft_delete()
    await db.flush()
    return True
