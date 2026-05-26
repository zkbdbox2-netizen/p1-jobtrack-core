"""
Job CRUD endpoint tests — GET/POST /jobs, GET/PATCH/DELETE /jobs/{id}.

Key behaviours covered:
- Authentication required on all endpoints
- Tenant isolation (user A cannot see user B's jobs)
- Partial update (only sent fields change)
- Soft delete (row survives, GET returns 404)
- Stage + outcome filtering
- Cursor-based pagination
"""
import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BASE_JOB = {
    "title": "Backend Engineer",
    "company": "Acme Corp",
    "stage": "applied",
    "outcome": "active",
    "applied_date": "2026-05-20",
    "salary_min": 150000,
    "salary_max": 200000,
}


async def create_job(client: AsyncClient, headers: dict, **overrides) -> dict:
    """Helper — POST a job and return the response body."""
    payload = {**BASE_JOB, **overrides}
    resp = await client.post("/jobs", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Authentication guard
# ---------------------------------------------------------------------------

async def test_list_jobs_requires_auth(client: AsyncClient):
    """All job endpoints reject unauthenticated requests with 401."""
    resp = await client.get("/jobs")
    assert resp.status_code == 401


async def test_create_job_requires_auth(client: AsyncClient):
    resp = await client.post("/jobs", json=BASE_JOB)
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

async def test_create_job_returns_201(client: AsyncClient, auth_headers: dict):
    """Creating a job returns 201 with all fields populated."""
    resp = await client.post("/jobs", json=BASE_JOB, headers=auth_headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["title"] == "Backend Engineer"
    assert body["company"] == "Acme Corp"
    assert body["stage"] == "applied"
    assert body["outcome"] == "active"
    assert body["salary_min"] == 150000
    assert "id" in body


async def test_create_job_defaults_to_wishlist_active(client: AsyncClient, auth_headers: dict):
    """Omitting stage/outcome defaults to wishlist + active."""
    resp = await client.post("/jobs", json={
        "title": "Data Engineer",
        "company": "Beta Inc",
    }, headers=auth_headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["stage"] == "wishlist"
    assert body["outcome"] == "active"


async def test_create_job_rejects_invalid_salary_range(client: AsyncClient, auth_headers: dict):
    """salary_max < salary_min should return 422."""
    resp = await client.post("/jobs", json={
        **BASE_JOB,
        "salary_min": 200000,
        "salary_max": 100000,
    }, headers=auth_headers)
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Get
# ---------------------------------------------------------------------------

async def test_get_job_by_id(client: AsyncClient, auth_headers: dict):
    """GET /jobs/{id} returns the correct job."""
    job = await create_job(client, auth_headers)
    resp = await client.get(f"/jobs/{job['id']}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == job["id"]


async def test_get_job_returns_404_for_unknown(client: AsyncClient, auth_headers: dict):
    """Non-existent job ID returns 404."""
    resp = await client.get(
        "/jobs/00000000-0000-0000-0000-000000000000",
        headers=auth_headers,
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------

async def test_user_cannot_see_another_users_job(client: AsyncClient):
    """
    Tenant isolation: user A's jobs are invisible to user B.

    This is the most critical security test — every query must filter by
    tenant_id. Without it, any authenticated user could enumerate all jobs.
    """
    # Register two separate users
    resp_a = await client.post("/auth/register", json={
        "email": "alice@example.com", "password": "alicepass123"
    })
    resp_b = await client.post("/auth/register", json={
        "email": "bob@example.com", "password": "bobpass123"
    })
    headers_a = {"Authorization": f"Bearer {resp_a.json()['access_token']}"}
    headers_b = {"Authorization": f"Bearer {resp_b.json()['access_token']}"}

    # Alice creates a job
    job = await create_job(client, headers_a)

    # Bob tries to read Alice's job — must get 404, not the job
    resp = await client.get(f"/jobs/{job['id']}", headers=headers_b)
    assert resp.status_code == 404

    # Bob's list must be empty
    list_resp = await client.get("/jobs", headers=headers_b)
    assert list_resp.json()["total_returned"] == 0


# ---------------------------------------------------------------------------
# Update (PATCH)
# ---------------------------------------------------------------------------

async def test_patch_updates_only_sent_fields(client: AsyncClient, auth_headers: dict):
    """
    PATCH with a single field only changes that field — other fields untouched.

    This verifies model_dump(exclude_unset=True) is working correctly.
    Sending {"outcome": "frozen"} must not wipe salary_min or notes.
    """
    job = await create_job(client, auth_headers)
    job_id = job["id"]

    # Only update outcome
    resp = await client.patch(
        f"/jobs/{job_id}",
        json={"outcome": "frozen"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["outcome"] == "frozen"
    assert body["stage"] == "applied"          # unchanged
    assert body["salary_min"] == 150000        # unchanged
    assert body["title"] == "Backend Engineer" # unchanged


async def test_patch_stage_and_outcome_together(client: AsyncClient, auth_headers: dict):
    """Move a job to onsite + frozen in one PATCH."""
    job = await create_job(client, auth_headers)
    resp = await client.patch(
        f"/jobs/{job['id']}",
        json={"stage": "onsite", "outcome": "frozen"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["stage"] == "onsite"
    assert body["outcome"] == "frozen"


# ---------------------------------------------------------------------------
# Delete (soft)
# ---------------------------------------------------------------------------

async def test_delete_soft_deletes_job(client: AsyncClient, auth_headers: dict):
    """
    DELETE returns 204. Subsequent GET returns 404 — row is gone from the
    API's perspective even though deleted_at is set in the DB.
    """
    job = await create_job(client, auth_headers)
    job_id = job["id"]

    delete_resp = await client.delete(f"/jobs/{job_id}", headers=auth_headers)
    assert delete_resp.status_code == 204

    get_resp = await client.get(f"/jobs/{job_id}", headers=auth_headers)
    assert get_resp.status_code == 404


async def test_deleted_job_absent_from_list(client: AsyncClient, auth_headers: dict):
    """Soft-deleted jobs do not appear in the list endpoint."""
    job = await create_job(client, auth_headers)
    await client.delete(f"/jobs/{job['id']}", headers=auth_headers)

    resp = await client.get("/jobs", headers=auth_headers)
    assert resp.json()["total_returned"] == 0


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

async def test_stage_outcome_filter(client: AsyncClient, auth_headers: dict):
    """
    ?stage=onsite&outcome=frozen returns only matching jobs.
    The two-field model means we can pinpoint exact pipeline states.
    """
    await create_job(client, auth_headers, stage="applied",  outcome="active")
    await create_job(client, auth_headers, stage="onsite",   outcome="frozen")
    await create_job(client, auth_headers, stage="onsite",   outcome="rejected")

    resp = await client.get(
        "/jobs?stage=onsite&outcome=frozen",
        headers=auth_headers,
    )
    body = resp.json()
    assert body["total_returned"] == 1
    assert body["items"][0]["stage"] == "onsite"
    assert body["items"][0]["outcome"] == "frozen"


# ---------------------------------------------------------------------------
# Cursor pagination
# ---------------------------------------------------------------------------

async def test_cursor_pagination(client: AsyncClient, auth_headers: dict):
    """
    With limit=2 and 3 jobs, the first page returns 2 items + a next_cursor.
    The second page (using that cursor) returns the remaining 1 item + no cursor.
    """
    # Create 3 jobs with distinct applied_dates so sort order is deterministic
    await create_job(client, auth_headers, applied_date="2026-05-01")
    await create_job(client, auth_headers, applied_date="2026-05-02")
    await create_job(client, auth_headers, applied_date="2026-05-03")

    # Page 1
    resp1 = await client.get("/jobs?limit=2", headers=auth_headers)
    body1 = resp1.json()
    assert body1["total_returned"] == 2
    assert body1["next_cursor"] is not None

    # Page 2
    cursor = body1["next_cursor"]
    resp2 = await client.get(f"/jobs?limit=2&cursor={cursor}", headers=auth_headers)
    body2 = resp2.json()
    assert body2["total_returned"] == 1
    assert body2["next_cursor"] is None   # last page

    # No overlap between pages
    ids1 = {item["id"] for item in body1["items"]}
    ids2 = {item["id"] for item in body2["items"]}
    assert ids1.isdisjoint(ids2)
