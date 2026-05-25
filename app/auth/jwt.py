import uuid
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from app.config import settings

# ---------------------------------------------------------------------------
# Token creation
# ---------------------------------------------------------------------------

def _make_token(payload: dict, expires_delta: timedelta) -> str:
    """Internal helper — builds and signs a JWT."""
    expire = datetime.now(timezone.utc) + expires_delta
    payload = {**payload, "exp": expire, "iat": datetime.now(timezone.utc)}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def create_access_token(user_id: uuid.UUID, role: str, tenant_id: uuid.UUID) -> str:
    """
    Create a short-lived access token (15 minutes by default).

    Stateless: validated by signature alone — no DB or Redis lookup needed.
    This is what makes JWTs fast for high-traffic APIs. The tradeoff is that
    a stolen access token can't be revoked until it expires — hence keeping
    it short-lived.

    Payload claims:
    - sub: subject (the user ID) — standard JWT claim
    - role: used by RBAC dependencies to gate admin routes
    - tenant_id: injected into every service call to enforce row-level isolation
    - type: "access" — so we can reject refresh tokens used as access tokens
    """
    return _make_token(
        payload={
            "sub": str(user_id),
            "role": role,
            "tenant_id": str(tenant_id),
            "type": "access",
        },
        expires_delta=timedelta(minutes=settings.access_token_expire_minutes),
    )


def create_refresh_token(user_id: uuid.UUID) -> tuple[str, str]:
    """
    Create a long-lived refresh token (7 days by default).

    Stateful: stored in Redis so it can be revoked on logout or rotation.
    Returns (token, jti) where jti is the unique token ID used as the Redis key.

    jti (JWT ID) is a standard claim that gives each token a unique identity.
    This is what we store in Redis — not the full token string.
    """
    jti = str(uuid.uuid4())    # unique ID for this specific token instance
    token = _make_token(
        payload={
            "sub": str(user_id),
            "type": "refresh",
            "jti": jti,
        },
        expires_delta=timedelta(days=settings.refresh_token_expire_days),
    )
    return token, jti


# ---------------------------------------------------------------------------
# Token validation
# ---------------------------------------------------------------------------

def decode_access_token(token: str) -> dict:
    """
    Decode and validate an access token.

    Raises JWTError if:
    - signature is invalid (tampered token)
    - token has expired
    - token type is not "access" (catches refresh tokens used as access tokens)
    """
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError:
        raise

    if payload.get("type") != "access":
        raise JWTError("Invalid token type")

    return payload


def decode_refresh_token(token: str) -> dict:
    """
    Decode and validate a refresh token.
    The caller is responsible for checking Redis to confirm the jti is still valid.
    """
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError:
        raise

    if payload.get("type") != "refresh":
        raise JWTError("Invalid token type")

    return payload
