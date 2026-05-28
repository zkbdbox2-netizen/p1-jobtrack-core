import uuid
from datetime import date

from pydantic import BaseModel, Field, HttpUrl, model_validator

from app.models.job import JobOutcome, JobStage


class JobCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    company: str = Field(..., min_length=1, max_length=255)
    stage: JobStage = JobStage.wishlist
    outcome: JobOutcome = JobOutcome.active
    job_url: HttpUrl | None = None
    location: str | None = Field(None, max_length=255)
    salary_min: int | None = Field(None, ge=0)
    salary_max: int | None = Field(None, ge=0)
    applied_date: date | None = None
    notes: str | None = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "title": "Software Engineer",
                "company": "Acme Corp",
                "stage": "applied",
                "outcome": "active",
                "job_url": "https://acme.com/jobs/123",
                "location": "San Francisco, CA",
                "salary_min": 150000,
                "salary_max": 180000,
                "applied_date": "2026-05-27",
                "notes": "Referred by a friend on the team.",
            }
        }
    }

    @model_validator(mode="after")
    def salary_range_valid(self) -> "JobCreateRequest":
        """salary_max must be >= salary_min when both are provided."""
        if self.salary_min is not None and self.salary_max is not None:
            if self.salary_max < self.salary_min:
                raise ValueError("salary_max must be >= salary_min")
        return self


class JobUpdateRequest(BaseModel):
    """
    All fields optional — supports partial updates (PATCH semantics).
    Only fields explicitly sent by the client are changed.
    """
    title: str | None = Field(None, min_length=1, max_length=255)
    company: str | None = Field(None, min_length=1, max_length=255)
    stage: JobStage | None = None
    outcome: JobOutcome | None = None
    job_url: HttpUrl | None = None
    location: str | None = Field(None, max_length=255)
    salary_min: int | None = Field(None, ge=0)
    salary_max: int | None = Field(None, ge=0)
    applied_date: date | None = None
    notes: str | None = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "stage": "phone_screen",
                "outcome": "active",
                "notes": "Recruiter call scheduled for next week.",
            }
        }
    }

    @model_validator(mode="after")
    def salary_range_valid(self) -> "JobUpdateRequest":
        if self.salary_min is not None and self.salary_max is not None:
            if self.salary_max < self.salary_min:
                raise ValueError("salary_max must be >= salary_min")
        return self


class JobResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    title: str
    company: str
    stage: JobStage
    outcome: JobOutcome
    job_url: str | None
    location: str | None
    salary_min: int | None
    salary_max: int | None
    applied_date: date | None
    notes: str | None


class JobListResponse(BaseModel):
    """
    Paginated list response.

    next_cursor is an opaque base64 string — pass it as ?cursor=<value>
    to fetch the next page. null means you've reached the last page.
    """
    items: list[JobResponse]
    next_cursor: str | None
    total_returned: int
