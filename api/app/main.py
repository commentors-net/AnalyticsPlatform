"""FastAPI Application Entry Point & Lifespan Management (Firestore-backed)."""

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from api.app.core.config import settings
from api.app.routes import analytics, apps, auth, events, health, keys, users
from api.app.services.firestore_repo import firestore_repo

logging.basicConfig(level=settings.LOG_LEVEL)
logger = logging.getLogger("analytics_platform")


async def ensure_initial_superadmin_provisioned() -> None:
    """Ensure initial approved Google account is provisioned with SuperAdmin access (no password)."""
    if not settings.GOOGLE_INITIAL_ADMIN_EMAIL:
        return

    try:
        user = firestore_repo.get_user_by_email(settings.GOOGLE_INITIAL_ADMIN_EMAIL)
        if not user:
            firestore_repo.provision_approved_user(
                email=settings.GOOGLE_INITIAL_ADMIN_EMAIL,
                role="SuperAdmin",
                status="ACTIVE",
            )
            logger.info(f"Provisioned approved initial SuperAdmin Google account: {settings.GOOGLE_INITIAL_ADMIN_EMAIL}")
    except Exception as exc:
        logger.warning(f"Initial superadmin check skipped: {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager initializing Firestore connection and handling shutdown."""
    logger.info(f"Starting Analytics Platform API [Env: {settings.ENVIRONMENT}] [DB: Google Cloud Firestore] [Auth: Google Sign-In OIDC]")
    await ensure_initial_superadmin_provisioned()
    yield
    logger.info("Shutting down Analytics Platform API")


app = FastAPI(
    title="Self-Hosted Multi-Application Analytics Platform",
    description="Independent telemetry collection, session persistence and reporting API on Cloud Firestore.",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS Middleware (M2-08: origin reflection and credential support)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://.*",
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS", "DELETE", "PUT", "PATCH"],
    allow_headers=["*"],
    expose_headers=["Retry-After"],
    max_age=86400,
)

# Include Routers
app.include_router(health.router)
app.include_router(events.router)
app.include_router(analytics.router)
app.include_router(auth.router)
app.include_router(apps.router)
app.include_router(keys.router)
app.include_router(users.router)

# Mount Dashboard Static SPA
dashboard_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "dashboard"))
if os.path.isdir(dashboard_path):
    app.mount("/dashboard", StaticFiles(directory=dashboard_path, html=True), name="dashboard")


@app.get("/", include_in_schema=False)
async def root_redirect():
    """Redirect root path to interactive dashboard."""
    return RedirectResponse(url="/dashboard/")
