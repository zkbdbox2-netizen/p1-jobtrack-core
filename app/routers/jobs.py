import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rbac import CurrentUser, get_current_user
from app.db.session import get_db
from app.models.job import JobOutcome, JobStage
from app.schemas.job import JobCreateRequest, JobListResponse, JobResponse, JobUpdateRequest
from app.services.job import create_job, delete_job, get_job, list_jobs, update_job

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=JobListResponse)
async def list_jobs_route(
    cursor: str | None = Query(None, description="Pagination cursor from previous response"),
    limit: int = Query(20, ge=1, le=100, description="Results per page (max 100)"),
    stage: JobStage | None = Query(None, description="Filter by pipeline stage"),
    outcome: JobOutcome | None = Query(None, description="Filter by outcome"),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JobListResponse:
    """
    List job applications for the authenticated user.

    Results sorted by applied_date (newest first, nulls last), then by id.
    Combine stage + outcome filters for precise queries, e.g.:
      ?stage=onsite&outcome=frozen  →  all jobs ghosted after onsite
      ?stage=offer&outcome=active   →  offers currently in negotiation
    """
    jobs, next_cursor = await list_jobs(
        db,
        tenant_id=current_user.tenant_id,
        limit=limit,
        cursor=cursor,
        stage=stage,
        outcome=outcome,
    )
    return JobListResponse(
        items=[JobResponse.model_validate(j) for j in jobs],
        next_cursor=next_cursor,
        total_returned=len(jobs),
    )


@router.post("", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def create_job_route(
    body: JobCreateRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JobResponse:
    """Create a new job application. Defaults to stage=wishlist, outcome=active."""
    job = await create_job(db, tenant_id=current_user.tenant_id, data=body)
    return JobResponse.model_validate(job)


@router.get("/{job_id}", response_model=JobResponse)
async def get_job_route(
    job_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JobResponse:
    """Get a single job application by ID."""
    job = await get_job(db, tenant_id=current_user.tenant_id, job_id=job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return JobResponse.model_validate(job)


@router.patch("/{job_id}", response_model=JobResponse)
async def update_job_route(
    job_id: uuid.UUID,
    body: JobUpdateRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JobResponse:
    """
    Partially update a job application.

    Only fields present in the request body are modified.
    Example — move to next stage after passing onsite:
      PATCH /jobs/{id}  {"stage": "offer", "outcome": "active"}
    Example — mark as frozen after phone screen:
      PATCH /jobs/{id}  {"stage": "phone_screen", "outcome": "frozen"}
    """
    job = await update_job(db, tenant_id=current_user.tenant_id, job_id=job_id, data=body)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return JobResponse.model_validate(job)


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job_route(
    job_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Soft-delete a job application. Sets deleted_at — row is never removed."""
    deleted = await delete_job(db, tenant_id=current_user.tenant_id, job_id=job_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
