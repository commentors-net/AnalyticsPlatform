"""Administrative Authentication Routes (Google Sign-In & OpenID Connect)."""

import secrets
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Response, Security, status
from fastapi.security import HTTPAuthorizationCredentials

from api.app.core.config import settings
from api.app.core.dependencies import bearer_scheme, get_current_user, get_session_credentials
from api.app.core.google_auth import verify_google_id_token
from api.app.core.security import create_access_token, decode_access_token
from api.app.models.user import User
from api.app.schemas.auth import (
    AuthConfigResponse,
    GoogleAuthRequest,
    TokenResponse,
    UserResponse,
)
from api.app.services.firestore_repo import FirestoreRepo, get_repo

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


@router.get("/config", response_model=AuthConfigResponse)
async def get_auth_config() -> AuthConfigResponse:
    """Return public client-side authentication configuration for the dashboard."""
    client_id = settings.GOOGLE_CLIENT_ID
    if client_id and "," in client_id:
        client_id = client_id.split(",")[0].strip()
    return AuthConfigResponse(
        google_client_id=client_id,
        auth_mode="google",
    )


@router.post("/google", response_model=TokenResponse)
async def google_sign_in(
    payload: GoogleAuthRequest,
    response: Response,
    repo: FirestoreRepo = Depends(get_repo),
) -> TokenResponse:
    """Authenticate administrator using Google ID token and issue secure session cookies."""
    # 1. Cryptographically verify Google ID token
    google_user = verify_google_id_token(payload.id_token)

    # 2. Check if the Google account has been explicitly provisioned
    user = repo.get_user_by_email(google_user.email)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Google account '{google_user.email}' is not authorized for dashboard access. An administrator must provision your account.",
        )

    if user.get("status") != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is suspended or inactive",
        )

    # 3. Link Google Subject ID and update last login
    repo.link_google_identity(user["id"], google_user.sub)

    # 4. Generate CSRF defense token and application JWT
    csrf_token = secrets.token_urlsafe(32)
    token_data = {
        "sub": str(user["id"]),
        "email": user["email"],
        "role": str(user["role"]),
        "csrf": csrf_token,
    }
    access_token = create_access_token(token_data)
    expires_in = settings.ANALYTICS_ACCESS_TOKEN_EXPIRE_MINUTES * 60

    # 5. Set HttpOnly, SameSite, Secure session cookie (Requirement 6)
    is_secure = settings.ENVIRONMENT in ("production", "staging") or settings.COOKIE_SECURE
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=is_secure,
        samesite=settings.COOKIE_SAMESITE,
        max_age=expires_in,
        path="/",
    )
    # Set double-submit CSRF cookie accessible to dashboard JavaScript
    response.set_cookie(
        key="csrf_token",
        value=csrf_token,
        httponly=False,
        secure=is_secure,
        samesite=settings.COOKIE_SAMESITE,
        max_age=expires_in,
        path="/",
    )

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in_seconds=expires_in,
        csrf_token=csrf_token,
        user={
            "id": str(user["id"]),
            "email": user["email"],
            "role": str(user["role"]),
        },
    )


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    auth: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    repo: FirestoreRepo = Depends(get_repo),
) -> Dict[str, str]:
    """Authenticate/CSRF-check logout, persist revocation, then clear cookies."""
    token, _ = get_session_credentials(request, auth)
    payload = decode_access_token(token)
    try:
        repo.revoke_session(str(current_user.id), token, datetime.fromtimestamp(payload["exp"], timezone.utc))
    except Exception:
        raise HTTPException(status_code=503, detail="Logout temporarily unavailable; please retry")
    is_secure = settings.ENVIRONMENT in ("production", "staging") or settings.COOKIE_SECURE
    response.delete_cookie(key="access_token", path="/", secure=is_secure, httponly=True, samesite=settings.COOKIE_SAMESITE)
    response.delete_cookie(key="csrf_token", path="/", secure=is_secure, samesite=settings.COOKIE_SAMESITE)
    return {"status": "logged_out"}


@router.get("/me")
async def get_current_user_profile(
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Retrieve currently authenticated administrator profile and role."""
    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "role": current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role),
        "status": current_user.status,
    }


# Retired endpoints - return 410 Gone per Requirement 7
@router.post("/login", include_in_schema=False)
@router.post("/token", include_in_schema=False)
async def retired_password_login():
    """Password-based login has been permanently retired."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="Password-based authentication has been retired. Please authenticate via Google Sign-In at /api/v1/auth/google.",
    )
