"""User Management & Access Provisioning Routes (SuperAdmin only)."""

from typing import Any, Dict, List
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr

from api.app.core.dependencies import get_current_user, require_superadmin
from api.app.models.user import User, UserRole
from api.app.schemas.auth import UserCreate, UserResponse
from api.app.services.firestore_repo import FirestoreRepo, get_repo

router = APIRouter(prefix="/api/v1/users", tags=["User Management"])


class UpdateRoleRequest(BaseModel):
    role: UserRole


@router.get("", response_model=List[Dict[str, Any]])
async def list_users(
    current_user: User = Depends(require_superadmin),
    repo: FirestoreRepo = Depends(get_repo),
) -> List[Dict[str, Any]]:
    """List all provisioned users in the system (SuperAdmin only)."""
    users = repo.list_users()
    # Strip any legacy password hashes from output
    for u in users:
        u.pop("password_hash", None)
    return users


@router.post("", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def provision_user(
    payload: UserCreate,
    current_user: User = Depends(require_superadmin),
    repo: FirestoreRepo = Depends(get_repo),
) -> Dict[str, Any]:
    """Provision a new approved Google account for dashboard access (SuperAdmin only)."""
    existing = repo.get_user_by_email(payload.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"User with email '{payload.email}' already exists",
        )

    user = repo.create_user(
        email=payload.email,
        role=payload.role.value if hasattr(payload.role, "value") else str(payload.role),
        status="ACTIVE",
    )
    user.pop("password_hash", None)
    return user


@router.delete("/{user_id}", status_code=status.HTTP_200_OK)
async def delete_user(
    user_id: str,
    current_user: User = Depends(require_superadmin),
    repo: FirestoreRepo = Depends(get_repo),
) -> Dict[str, str]:
    """Revoke and delete user access (SuperAdmin only)."""
    if str(current_user.id) == str(user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SuperAdmin cannot delete their own account",
        )

    deleted = repo.delete_user(user_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{user_id}' not found",
        )
    return {"status": "deleted", "user_id": user_id}


@router.patch("/{user_id}", response_model=Dict[str, Any])
async def update_user_role(
    user_id: str,
    payload: UpdateRoleRequest,
    current_user: User = Depends(require_superadmin),
    repo: FirestoreRepo = Depends(get_repo),
) -> Dict[str, Any]:
    """Update role for a provisioned user (SuperAdmin only)."""
    role_str = payload.role.value if hasattr(payload.role, "value") else str(payload.role)
    updated = repo.update_user_role(user_id, role_str)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{user_id}' not found",
        )

    user = repo.get_user_by_id(user_id)
    user.pop("password_hash", None)
    return user
