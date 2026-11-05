"""Authentication and User Schemas (Google Sign-In & RBAC)."""

from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID
from pydantic import BaseModel, EmailStr, Field
from api.app.models.user import UserRole


class GoogleAuthRequest(BaseModel):
    """Payload sent by client when authenticating with a Google ID token."""
    id_token: str = Field(..., description="Google OpenID Connect ID token from Google Identity Services")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_seconds: int
    csrf_token: Optional[str] = None
    user: Optional[Dict[str, Any]] = None


class TokenPayload(BaseModel):
    sub: str  # user_id
    email: str
    role: str
    csrf: Optional[str] = None
    exp: Optional[int] = None


class AuthConfigResponse(BaseModel):
    google_client_id: Optional[str] = None
    auth_mode: str = "google"


class UserCreate(BaseModel):
    email: EmailStr
    role: UserRole = UserRole.AppViewer


class UserResponse(BaseModel):
    id: str
    email: EmailStr
    role: UserRole
    status: str
    google_sub: Optional[str] = None
    created_at: Optional[str] = None
    last_login_at: Optional[str] = None

    class Config:
        from_attributes = True
