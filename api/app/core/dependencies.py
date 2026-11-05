"""FastAPI Route Dependencies for RBAC and Ingestion Authentication."""

import hmac
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse
from fastapi import Depends, Header, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from api.app.core.security import decode_access_token, hash_api_key
from api.app.models.api_key import ApiKey, KeyStatus
from api.app.models.application import Application, AppStatus
from api.app.models.user import User, UserAppPermission, UserRole
from api.app.services.firestore_repo import FirestoreRepo, get_repo

bearer_scheme = HTTPBearer(auto_error=False)


def get_session_credentials(
    request: Request,
    auth: Optional[HTTPAuthorizationCredentials],
) -> tuple[str, bool]:
    """Use the same credential precedence for authentication and logout."""
    if auth and auth.credentials:
        return auth.credentials, False
    token = request.cookies.get("access_token")
    if token:
        return token, True
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing Authorization bearer token or session cookie",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    request: Request,
    auth: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    repo: FirestoreRepo = Depends(get_repo),
) -> User:
    """Validate JWT token from Authorization header or HttpOnly session cookie, with CSRF defense."""
    token, is_cookie_auth = get_session_credentials(request, auth)
    payload = decode_access_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject identifier",
        )

    # Safe reads use cookies directly. Mutations bind header + cookie to the signed claim.
    if is_cookie_auth and request.method not in ("GET", "HEAD", "OPTIONS"):
        csrf_header = request.headers.get("X-CSRF-Token")
        csrf_cookie = request.cookies.get("csrf_token")
        csrf_claim = payload.get("csrf")
        if (
            not csrf_header
            or not csrf_cookie
            or not isinstance(csrf_claim, str)
            or not hmac.compare_digest(csrf_header.encode("utf-8"), csrf_cookie.encode("utf-8"))
            or not hmac.compare_digest(csrf_header.encode("utf-8"), csrf_claim.encode("utf-8"))
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="CSRF validation failed: missing or mismatched token",
            )

    try:
        revoked = repo.is_session_revoked(user_id, token)
    except Exception:
        raise HTTPException(status_code=503, detail="Session validation temporarily unavailable")
    if revoked:
        raise HTTPException(status_code=401, detail="Session has been logged out")

    user_data = repo.get_user_by_id(user_id)
    if not user_data or user_data.get("status") != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account does not exist or is inactive",
        )

    return User(**user_data)


async def require_superadmin(
    current_user: User = Depends(get_current_user),
) -> User:
    """Enforce SuperAdmin platform permission."""
    if current_user.role != UserRole.SuperAdmin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operation requires SuperAdmin platform privileges",
        )
    return current_user


async def verify_app_access(
    app_id: str,
    current_user: User = Depends(get_current_user),
    repo: FirestoreRepo = Depends(get_repo),
) -> UserAppPermission | None:
    """Verify that the current user has access to a specific application."""
    if current_user.role == UserRole.SuperAdmin:
        return None

    perm_data = repo.get_user_app_permission(current_user.id, app_id)
    if not perm_data:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied to application '{app_id}'",
        )
    return UserAppPermission(**perm_data)


async def verify_app_admin_access(
    app_id: str,
    current_user: User = Depends(get_current_user),
    repo: FirestoreRepo = Depends(get_repo),
) -> None:
    """Enforce that the user has AppAdmin or SuperAdmin role for the application (M2-13)."""
    if current_user.role == UserRole.SuperAdmin:
        return

    perm = await verify_app_access(app_id, current_user, repo)
    if not perm or perm.granted_role not in (UserRole.AppAdmin, UserRole.SuperAdmin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Operation requires AppAdmin privileges for application '{app_id}'",
        )


def validate_origin_allowed(
    allowed_origins_str: Optional[str],
    origin: Optional[str],
    exact: bool = False,
) -> bool:
    """Verify that the request Origin header matches the application's configured allowed_origins.
    
    If origin is None (server-to-server call or direct non-browser request), it passes.
    If allowed_origins is empty or '*', all origins are permitted.
    Strictly enforces host and subdomain boundaries (e.g. .askanna.ai vs evil-askanna.ai).
    """
    if not origin:
        return True

    if exact:
        # Environment-specific browser origins match scheme, hostname and port exactly.
        return origin in (allowed_origins_str or "").split(",")

    if not allowed_origins_str or allowed_origins_str.strip() in ("", "*"):
        return True

    allowed_list = [o.strip().lower() for o in allowed_origins_str.split(",") if o.strip()]
    if not allowed_list:
        return True

    try:
        parsed_origin = urlparse(origin)
        origin_clean = parsed_origin.netloc.lower() or parsed_origin.path.lower()
        if ":" in origin_clean:
            origin_clean = origin_clean.split(":")[0]
    except Exception:
        origin_clean = origin.strip().lower()

    for allowed in allowed_list:
        try:
            parsed_allowed = urlparse(allowed)
            allowed_clean = parsed_allowed.netloc.lower() or allowed.replace("https://", "").replace("http://", "").split("/")[0].lower()
            if ":" in allowed_clean:
                allowed_clean = allowed_clean.split(":")[0]
        except Exception:
            allowed_clean = allowed.lower()

        # Exact host match or exact subdomain match with dot boundary
        if origin_clean == allowed_clean or origin_clean.endswith("." + allowed_clean):
            return True

    return False


async def validate_ingestion_key(
    raw_key: str,
    repo: FirestoreRepo,
) -> ApiKey:
    """Validate a raw write key, verifying its status, expiration, and associated application (M2-13)."""
    if not raw_key or not (raw_key.startswith("apk_live_") or raw_key.startswith("apk_test_")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid write_key format. Expected prefix 'apk_live_' or 'apk_test_'",
        )

    key_hash = hash_api_key(raw_key)
    key_data = repo.get_api_key_by_hash(key_hash)

    if not key_data or key_data.get("status") != KeyStatus.ACTIVE.value:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked write_key",
        )

    app_id = key_data.get("app_id")
    app_data = repo.get_app(app_id)
    if not app_data or app_data.get("status") != AppStatus.ACTIVE.value:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Associated application is inactive or not found",
        )

    key_obj = ApiKey(**key_data)
    key_obj.application = Application(**app_data)
    scoped_origins = app_data.get(f"{key_obj.environment.value}_origins")
    key_obj.application.strict_origins = scoped_origins is not None
    if scoped_origins is not None:
        key_obj.application.allowed_origins = scoped_origins

    if key_obj.expires_at is not None:
        expires_at_utc = key_obj.expires_at if key_obj.expires_at.tzinfo else key_obj.expires_at.replace(tzinfo=timezone.utc)
        if expires_at_utc <= datetime.now(timezone.utc):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API key has expired",
            )

    return key_obj
