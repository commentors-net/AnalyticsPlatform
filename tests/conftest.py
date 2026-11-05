"""Pytest Test Configuration & Asynchronous Fixtures (Firestore-backed)."""

import os
import sys
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Force testing environment and mock Firestore before importing app modules
os.environ["ENVIRONMENT"] = "testing"
os.environ["USE_MOCK_FIRESTORE"] = "1"
os.environ["ANALYTICS_JWT_SECRET"] = "testing-jwt-secret-key-for-unit-and-integration-tests-32chars"

from typing import AsyncGenerator
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from api.app.core.config import settings
from api.app.core.database import get_db
from api.app.core.security import get_password_hash
from api.app.main import app
from api.app.models.user import User, UserRole
from api.app.services.firestore_repo import firestore_repo, FirestoreRepo


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    """Verify or initialize database schema for testing."""
    pass


@pytest.fixture(autouse=True)
def reset_mock_firestore():
    """Clear and re-seed mock Firestore for each test."""
    if hasattr(firestore_repo.db.client, "clear"):
        firestore_repo.db.client.clear()

    # Pre-seed standard test apps
    firestore_repo.create_app(
        app_id="askanna",
        name="AskAnna AI",
        allowed_origins="https://askanna.ai,https://test.askanna.ai,https://portal.askanna.ai",
    )
    firestore_repo.create_app(
        app_id="groundworks",
        name="GroundWorks Application",
        allowed_origins="https://groundworks.example.com",
    )
    firestore_repo.create_app(
        app_id="roomlyst",
        name="Roomlyst Application",
        allowed_origins="https://roomlyst.example.com",
    )


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[FirestoreRepo, None]:
    """Provide repository instance for test functions."""
    yield firestore_repo


@pytest_asyncio.fixture
async def client(db_session: FirestoreRepo) -> AsyncGenerator[AsyncClient, None]:
    """Provide an async test client connected to the FastAPI application."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def superadmin_user(db_session: FirestoreRepo) -> User:
    """Ensure a SuperAdmin test user exists and return it."""
    email = "test_admin@analytics.internal"
    user_data = db_session.get_user_by_email(email)
    if not user_data:
        user_data = db_session.create_user(
            email=email,
            role="SuperAdmin",
            status="ACTIVE",
            google_sub="google_sub_superadmin_test",
        )
    return User(**user_data)


@pytest_asyncio.fixture
async def superadmin_token(client: AsyncClient, superadmin_user: User) -> str:
    """Provide a valid SuperAdmin access token via Google auth."""
    resp = await client.post(
        "/api/v1/auth/google",
        json={"id_token": f"mock_google_id_token:{superadmin_user.email}:sub_admin_fixture"},
    )
    return resp.json()["access_token"]
