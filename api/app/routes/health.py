"""Health Check and Liveness / Readiness Probes."""

from fastapi import APIRouter, Depends, HTTPException, status
from api.app.core.firestore_db import firestore_db, get_firestore, FirestoreDB
from api.app.schemas.health import HealthLiveResponse, HealthReadyResponse

router = APIRouter(tags=["Health"])


@router.get("/health/live", response_model=HealthLiveResponse, summary="Liveness Probe")
async def health_live() -> HealthLiveResponse:
    """Liveness probe for Cloud Run container orchestration."""
    return HealthLiveResponse(status="ok")


@router.get(
    "/health/ready",
    response_model=HealthReadyResponse,
    summary="Readiness Probe",
    responses={503: {"description": "Database connection unhealthy"}},
)
async def health_ready(db: FirestoreDB = Depends(get_firestore)) -> HealthReadyResponse:
    """Readiness probe verifying Google Cloud Firestore reachability."""
    try:
        ok = db.ping()
        if not ok:
            raise ValueError("Firestore ping returned False")
        return HealthReadyResponse(status="ready", database="connected")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database connection unhealthy: {str(exc)}",
        )
