from fastapi import APIRouter, Depends, HTTPException, status
from jose import JWTError
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
)
from app.db.session import get_db
from app.dependencies import get_redis
from app.schemas.user import (
    RefreshRequest,
    TokenResponse,
    UserLoginRequest,
    UserRegisterRequest,
    UserResponse,
)
from app.services.user import create_user, get_user_by_email, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])

# Redis key pattern for refresh tokens: "refresh:<jti>"
# Using a prefix makes it easy to scan/debug all refresh tokens in Redis.
REFRESH_KEY = "refresh:{jti}"

# TTL matches the token's own expiry — Redis auto-expires the key so we
# don't need a cleanup job.
REFRESH_TTL_SECONDS = 60 * 60 * 24 * 7   # 7 days


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    body: UserRegisterRequest,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> TokenResponse:
    """
    Create a new user account and return tokens immediately.

    The user is logged in right after registration — no separate login step needed.
    This is the expected UX for most apps.
    """
    try:
        user = await create_user(db, body)
    except ValueError as e:
        # create_user raises ValueError for duplicate emails
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))

    access_token = create_access_token(user.id, user.role.value, user.tenant_id)
    refresh_token, jti = create_refresh_token(user.id)

    # Store the refresh token's jti in Redis.
    # Value is the user ID — useful if we ever need to invalidate all tokens for a user.
    await redis.setex(REFRESH_KEY.format(jti=jti), REFRESH_TTL_SECONDS, str(user.id))

    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/login", response_model=TokenResponse)
async def login(
    body: UserLoginRequest,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> TokenResponse:
    """
    Exchange email + password for an access token and refresh token.

    Security note: we return the same 401 error whether the email doesn't exist
    OR the password is wrong. This prevents user enumeration — an attacker
    can't tell which accounts exist by trying emails.
    """
    invalid_credentials = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid email or password",    # intentionally vague
    )

    user = await get_user_by_email(db, body.email)
    if user is None:
        raise invalid_credentials
    if not verify_password(body.password, user.hashed_password):
        raise invalid_credentials
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")

    access_token = create_access_token(user.id, user.role.value, user.tenant_id)
    refresh_token, jti = create_refresh_token(user.id)
    await redis.setex(REFRESH_KEY.format(jti=jti), REFRESH_TTL_SECONDS, str(user.id))

    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    body: RefreshRequest,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> TokenResponse:
    """
    Exchange a refresh token for a new access + refresh token pair.

    This is token rotation:
    1. Validate the incoming refresh token (signature + expiry)
    2. Check its jti exists in Redis (confirms it hasn't been used/revoked)
    3. Delete the old jti from Redis (one-time use)
    4. Issue a new access token + new refresh token
    5. Store the new jti in Redis

    If someone tries to reuse a refresh token that was already rotated,
    step 2 fails — the old jti is gone. This limits the damage from a stolen
    refresh token: once the legitimate user rotates it, the stolen copy is dead.
    """
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired refresh token",
    )

    try:
        payload = decode_refresh_token(body.refresh_token)
    except JWTError:
        raise credentials_error

    jti = payload.get("jti")
    user_id = payload.get("sub")
    if not jti or not user_id:
        raise credentials_error

    # Check the jti exists in Redis — if not, the token was already rotated or revoked
    stored = await redis.get(REFRESH_KEY.format(jti=jti))
    if stored is None:
        raise credentials_error

    # Rotate: delete old jti atomically, then issue new tokens
    await redis.delete(REFRESH_KEY.format(jti=jti))

    # Fetch the user from DB to get their current role and tenant_id.
    # WHY fetch from DB instead of embedding in the refresh token?
    # If an admin demotes a user mid-session, the next refresh picks up the
    # new role immediately. Embedding role in the refresh token would mean
    # the old role persists for the full 7-day token lifetime.
    import uuid as _uuid
    from app.services.user import get_user_by_id

    user = await get_user_by_id(db, _uuid.UUID(user_id))
    if user is None or not user.is_active:
        raise credentials_error

    new_access = create_access_token(user.id, user.role.value, user.tenant_id)
    new_refresh, new_jti = create_refresh_token(user.id)
    await redis.setex(REFRESH_KEY.format(jti=new_jti), REFRESH_TTL_SECONDS, str(user.id))

    return TokenResponse(access_token=new_access, refresh_token=new_refresh)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    body: RefreshRequest,
    redis: Redis = Depends(get_redis),
) -> None:
    """
    Revoke the refresh token by deleting its jti from Redis.

    The access token cannot be revoked (it's stateless) — it will expire naturally
    within 15 minutes. This is the accepted tradeoff of stateless JWTs.

    If you need immediate access token revocation, the pattern is a Redis
    "blocklist" — store revoked access token jtis until they expire.
    We document this in DESIGN.md but don't implement it here (adds complexity
    that isn't warranted for a personal job tracker).
    """
    try:
        payload = decode_refresh_token(body.refresh_token)
        jti = payload.get("jti")
        if jti:
            await redis.delete(REFRESH_KEY.format(jti=jti))
    except JWTError:
        pass   # if the token is already invalid, logout is effectively a no-op

    # Always return 204 — don't reveal whether the token was valid
