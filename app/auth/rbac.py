import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError

from app.auth.jwt import decode_access_token

# HTTPBearer extracts the token from the Authorization: Bearer <token> header.
# auto_error=False means it returns None instead of raising 403 when the header
# is missing — we handle that ourselves with a clearer error message.
bearer_scheme = HTTPBearer(auto_error=False)


class CurrentUser:
    """
    Represents the authenticated user extracted from the JWT.
    Passed into route handlers as a dependency — no DB lookup required.

    All the information needed for auth decisions (role, tenant_id) is
    embedded in the token itself. This is the stateless benefit of JWTs:
    we validate the signature once and trust the claims.
    """
    def __init__(self, user_id: uuid.UUID, role: str, tenant_id: uuid.UUID):
        self.user_id = user_id
        self.role = role
        self.tenant_id = tenant_id


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> CurrentUser:
    """
    FastAPI dependency — validates the access token and returns the current user.

    Usage in a route:
        @router.get("/jobs")
        async def list_jobs(user: CurrentUser = Depends(get_current_user)):
            # user.tenant_id, user.role, user.user_id are available here

    Raises 401 if:
    - Authorization header is missing
    - Token is invalid or expired
    - Token type is not "access"
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_access_token(credentials.credentials)
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {e}",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return CurrentUser(
        user_id=uuid.UUID(payload["sub"]),
        role=payload["role"],
        tenant_id=uuid.UUID(payload["tenant_id"]),
    )


async def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """
    FastAPI dependency — same as get_current_user but also requires admin role.

    Usage:
        @router.delete("/users/{id}")
        async def delete_user(user: CurrentUser = Depends(require_admin)):
            ...

    Raises 403 if the user is authenticated but not an admin.
    """
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )
    return user
