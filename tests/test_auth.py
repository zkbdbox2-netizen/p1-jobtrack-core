"""
Auth endpoint tests — POST /auth/register, /login, /refresh, /logout.

Each test is independent: the `clean_tables` fixture (autouse) wipes the
DB after every test, and `fake_redis` is a fresh in-memory instance.
"""
import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------

async def test_register_returns_tokens(client: AsyncClient):
    """Happy path: new user gets back access + refresh tokens."""
    resp = await client.post("/auth/register", json={
        "email": "new@example.com",
        "password": "strongpass123",
    })
    assert resp.status_code == 201
    body = resp.json()
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["token_type"] == "bearer"


async def test_register_duplicate_email_returns_409(client: AsyncClient):
    """Registering the same email twice returns 409 Conflict."""
    payload = {"email": "dupe@example.com", "password": "strongpass123"}
    await client.post("/auth/register", json=payload)
    resp = await client.post("/auth/register", json=payload)
    assert resp.status_code == 409


async def test_register_short_password_returns_422(client: AsyncClient):
    """Pydantic rejects passwords shorter than 8 characters."""
    resp = await client.post("/auth/register", json={
        "email": "short@example.com",
        "password": "abc",
    })
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

async def test_login_success(client: AsyncClient, registered_user: dict):
    """Correct credentials return a fresh token pair."""
    resp = await client.post("/auth/login", json={
        "email": registered_user["email"],
        "password": registered_user["password"],
    })
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert "refresh_token" in body


async def test_login_wrong_password_returns_401(client: AsyncClient, registered_user: dict):
    """Wrong password returns 401 — same error as unknown email to prevent enumeration."""
    resp = await client.post("/auth/login", json={
        "email": registered_user["email"],
        "password": "wrongpassword",
    })
    assert resp.status_code == 401
    # Error message must not reveal whether the email exists
    assert "Invalid email or password" in resp.json()["detail"]


async def test_login_unknown_email_returns_401(client: AsyncClient):
    """
    Unknown email returns the same 401 as wrong password.

    This is deliberate — returning 404 for unknown emails would let an
    attacker enumerate which email addresses have accounts.
    """
    resp = await client.post("/auth/login", json={
        "email": "ghost@example.com",
        "password": "doesntmatter",
    })
    assert resp.status_code == 401
    assert "Invalid email or password" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Refresh (token rotation)
# ---------------------------------------------------------------------------

async def test_refresh_returns_new_token_pair(client: AsyncClient, registered_user: dict):
    """
    Refresh endpoint issues a new access + refresh token pair.

    The new access token is different from the original (it has a new iat/exp).
    """
    resp = await client.post("/auth/refresh", json={
        "refresh_token": registered_user["refresh_token"],
    })
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert "refresh_token" in body
    # New tokens should differ from the originals
    assert body["refresh_token"] != registered_user["refresh_token"]


async def test_refresh_token_rotation_rejects_reuse(client: AsyncClient, registered_user: dict):
    """
    After a refresh token is used, it cannot be used again.

    This is token rotation: once rotated, the old JTI is deleted from Redis.
    A stolen token that arrives after the legitimate user has already rotated it
    will be rejected.
    """
    original_refresh = registered_user["refresh_token"]

    # First use — succeeds
    resp1 = await client.post("/auth/refresh", json={"refresh_token": original_refresh})
    assert resp1.status_code == 200

    # Second use of the SAME token — must fail
    resp2 = await client.post("/auth/refresh", json={"refresh_token": original_refresh})
    assert resp2.status_code == 401


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------

async def test_logout_revokes_refresh_token(client: AsyncClient, registered_user: dict):
    """
    After logout, the refresh token is revoked and can no longer be used.
    Logout itself always returns 204 (even if the token is already invalid).
    """
    refresh_token = registered_user["refresh_token"]

    # Logout
    resp = await client.post("/auth/logout", json={"refresh_token": refresh_token})
    assert resp.status_code == 204

    # Attempt to use the revoked token
    resp2 = await client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert resp2.status_code == 401
