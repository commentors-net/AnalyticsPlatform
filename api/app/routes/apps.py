"""Tenant Application Management Routes (Firestore-backed)."""

from typing import List
from fastapi import APIRouter, Depends, HTTPException, Response, status

from api.app.core.dependencies import get_current_user, require_superadmin, verify_app_access, verify_app_admin_access
from api.app.models.application import Application, AppStatus
from api.app.models.user import User, UserRole
from api.app.schemas.application import ApplicationCreate, ApplicationUpdate, ApplicationResponse, ApplicationDelete
from api.app.services import app_deletion
from api.app.services.firestore_repo import FirestoreRepo, get_repo

router = APIRouter(prefix="/api/v1/apps", tags=["Applications"])


def app_response(data, user, repo):
    result = ApplicationResponse.model_validate(Application(**data))
    permission = None if user.role == UserRole.SuperAdmin else repo.get_user_app_permission(user.id, data["app_id"])
    result.can_manage = user.role == UserRole.SuperAdmin or bool(permission and permission.get("granted_role") in ("AppAdmin", "SuperAdmin"))
    result.can_delete = user.role == UserRole.SuperAdmin
    return result


@router.get("", response_model=List[ApplicationResponse])
async def list_applications(
    current_user: User = Depends(get_current_user),
    repo: FirestoreRepo = Depends(get_repo),
) -> List[ApplicationResponse]:
    """List applications accessible to the current user."""
    is_sa = (current_user.role == UserRole.SuperAdmin)
    raw_apps = repo.list_apps_for_user(current_user.id, is_superadmin=is_sa)
    return [app_response(a, current_user, repo) for a in raw_apps]


@router.post("", response_model=ApplicationResponse, status_code=status.HTTP_201_CREATED)
async def create_application(
    payload: ApplicationCreate,
    current_user: User = Depends(require_superadmin),
    repo: FirestoreRepo = Depends(get_repo),
) -> ApplicationResponse:
    """Register a new tenant application (SuperAdmin only)."""
    try:
        app_data = repo.create_app(
            app_id=payload.app_id,
            name=payload.name,
            allowed_origins=payload.allowed_origins,
            live_origins=payload.live_origins,
            test_origins=payload.test_origins,
            classification=payload.classification,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )

    return app_response(app_data, current_user, repo)


@router.patch("/{app_id}", response_model=ApplicationResponse)
async def update_application(
    app_id: str, payload: ApplicationUpdate,
    current_user: User = Depends(get_current_user),
    repo: FirestoreRepo = Depends(get_repo),
) -> ApplicationResponse:
    await verify_app_admin_access(app_id, current_user, repo)
    try:
        data = repo.update_app(app_id, payload.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if not data:
        raise HTTPException(status_code=404, detail="Application not found")
    return app_response(data, current_user, repo)


@router.get("/{app_id}/deletion-preview")
async def deletion_preview(app_id: str, response: Response,
                           current_user: User = Depends(require_superadmin), repo: FirestoreRepo = Depends(get_repo)):
    response.headers["Cache-Control"] = "no-store"
    try:
        return app_deletion.preview(repo, app_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception:
        raise HTTPException(status_code=503, detail="Deletion preview unavailable; no deletion was started")


@router.delete("/{app_id}")
async def delete_application(app_id: str, payload: ApplicationDelete, response: Response,
                             current_user: User = Depends(require_superadmin), repo: FirestoreRepo = Depends(get_repo)):
    response.headers["Cache-Control"] = "no-store"
    try:
        result = app_deletion.delete_step(repo, app_id, payload.confirmation, payload.preview_token, str(current_user.id))
        response.status_code = 200 if result["status"] == "deleted" else 202
        return result
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception:
        raise HTTPException(status_code=503, detail="Cleanup interrupted. The app may be paused for deletion; load a fresh preview and resume.")


@router.get("/{app_id}", response_model=ApplicationResponse)
async def get_application(
    app_id: str,
    current_user: User = Depends(get_current_user),
    repo: FirestoreRepo = Depends(get_repo),
) -> ApplicationResponse:
    """Get single application details."""
    await verify_app_access(app_id, current_user, repo)

    app_data = repo.get_app(app_id)
    if not app_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Application '{app_id}' not found",
        )
    return app_response(app_data, current_user, repo)
