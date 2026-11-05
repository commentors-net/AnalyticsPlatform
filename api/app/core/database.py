"""Database Compatibility Layer for AnalyticsPlatform (Firestore-backed)."""

import logging
from typing import AsyncGenerator
from api.app.services.firestore_repo import FirestoreRepo, get_repo

logger = logging.getLogger(__name__)


async def get_db() -> AsyncGenerator[FirestoreRepo, None]:
    """Provide repository instance as dependency for FastAPI routes."""
    yield get_repo()


async def get_tenant_db(
    app_id: str,
    environment: str,
    is_superadmin: bool = False,
) -> AsyncGenerator[FirestoreRepo, None]:
    """Provide repository instance scoped for tenant analytics queries."""
    yield get_repo()


async def close_db_engine() -> None:
    """Shutdown cleanup (no-op for Firestore)."""
    logger.info("Firestore database session shutdown.")
