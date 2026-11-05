"""API Key Management Routes (Firestore-backed)."""

import uuid
from datetime import datetime, timezone
from typing import Any, List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from api.app.core.dependencies import get_current_user, verify_app_access, verify_app_admin_access
from api.app.core.security import generate_api_key
from api.app.models.api_key import ApiKey, EnvironmentType, KeyStatus
from api.app.models.user import User
from api.app.schemas.api_key import ApiKeyCreate, ApiKeyListItem, ApiKeyResponse
from api.app.services.firestore_repo import FirestoreRepo, get_repo

router = APIRouter(prefix="/api/v1/apps/{app_id}/keys", tags=["API Keys"])


def _write(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("", response_model=ApiKeyResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    app_id: str,
    payload: ApiKeyCreate,
    response: Response,
    current_user: Any = Depends(get_current_user),
    repo: FirestoreRepo = Depends(get_repo),
) -> ApiKeyResponse:
    """Generate and issue a write-only API key."""
    await verify_app_admin_access(app_id, current_user, repo)

    # Verify application exists
    app = repo.get_app(app_id)
    if not app:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    if app.get("status") != "ACTIVE":
        raise HTTPException(status_code=409, detail="Activate the application before generating collection keys")

    env_val = payload.environment.value if hasattr(payload.environment, "value") else str(payload.environment)
    raw_key, prefix, key_hash = generate_api_key(env_val)
    key_id = str(uuid.uuid4())

    key_data = _write(repo.create_api_key,
        key_id=key_id,
        app_id=app_id,
        environment=env_val,
        key_hash=key_hash,
        prefix=prefix,
        name=payload.name,
        expires_at=payload.expires_at,
    )

    api_key_obj = ApiKey(**key_data)
    response_data = ApiKeyResponse.model_validate(api_key_obj)
    response_data.raw_key = raw_key
    response.headers["Cache-Control"] = "no-store"
    return response_data


@router.get("", response_model=List[ApiKeyListItem])
async def list_api_keys(
    app_id: str,
    env: EnvironmentType | None = Query(default=None, description="Optional environment filter"),
    current_user: Any = Depends(get_current_user),
    repo: FirestoreRepo = Depends(get_repo),
) -> List[ApiKeyListItem]:
    """List API keys for an application (non-secret prefixes only)."""
    await verify_app_access(app_id, current_user, repo)

    env_val = env.value if hasattr(env, "value") else (str(env) if env else None)
    raw_keys = repo.list_api_keys(app_id, environment=env_val)
    return [ApiKeyListItem.model_validate(ApiKey(**k)) for k in raw_keys]


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    app_id: str,
    key_id: UUID,
    current_user: Any = Depends(get_current_user),
    repo: FirestoreRepo = Depends(get_repo),
) -> None:
    """Immediately revoke an active API key."""
    await verify_app_admin_access(app_id, current_user, repo)

    ok = _write(repo.revoke_api_key, app_id, str(key_id))
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
