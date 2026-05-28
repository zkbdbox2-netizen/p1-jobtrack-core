import uuid
from pydantic import BaseModel, EmailStr, Field


# ---------------------------------------------------------------------------
# Request schemas (what the API accepts from the client)
# ---------------------------------------------------------------------------

class UserRegisterRequest(BaseModel):
    """Body for POST /auth/register."""
    email: EmailStr                          # pydantic validates email format automatically
    password: str = Field(min_length=8)     # enforce minimum password length at the schema level

    model_config = {
        "json_schema_extra": {
            "example": {
                "email": "demo@example.com",
                "password": "password123",
            }
        }
    }


class UserLoginRequest(BaseModel):
    """Body for POST /auth/login."""
    email: EmailStr
    password: str

    model_config = {
        "json_schema_extra": {
            "example": {
                "email": "demo@example.com",
                "password": "password123",
            }
        }
    }


class RefreshRequest(BaseModel):
    """Body for POST /auth/refresh."""
    refresh_token: str

    model_config = {
        "json_schema_extra": {
            "example": {
                "refresh_token": "<paste refresh_token from /auth/login response>",
            }
        }
    }


# ---------------------------------------------------------------------------
# Response schemas (what the API sends back — never include hashed_password)
# ---------------------------------------------------------------------------

class TokenResponse(BaseModel):
    """
    Returned by /register and /login.

    Both tokens are returned together so the client can store them immediately.
    The client should keep the access token in memory (not localStorage — XSS risk)
    and the refresh token in an httpOnly cookie (XSS-safe).
    For this portfolio we return both in the JSON body for simplicity.
    """
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    """
    Public representation of a user — safe to return in API responses.

    Note what is NOT here: hashed_password, deleted_at.
    The API surface intentionally exposes less than the DB stores.
    """
    id: uuid.UUID
    email: str
    role: str
    is_active: bool
    tenant_id: uuid.UUID

    model_config = {"from_attributes": True}  # allows creating from SQLAlchemy model instances
