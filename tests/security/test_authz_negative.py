"""Negative Authorization & Authentication Security Tests."""

import uuid
from datetime import timedelta
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.core.security import create_access_token, get_password_hash
from api.app.models.api_key import ApiKey, EnvironmentType, KeyStatus
from api.app.models.user import User, UserAppPermission, UserRole


@pytest.mark.asyncio
async def test_ingestion_rejects_missing_and_invalid_write_key(client: AsyncClient):
    """Verify that unauthenticated ingestion requests are rejected with 401."""
    # Missing write key
    resp_missing = await client.post(
        "/v1/events",
        json={"page_path": "/home", "event_name": "page_view"},
    )
    assert resp_missing.status_code == 401

    # Invalid write key format
    resp_invalid = await client.post(
        "/v1/events",
        json={"page_path": "/home", "event_name": "page_view"},
        headers={"X-Write-Key": "invalid_fake_key_12345"},
    )
    assert resp_invalid.status_code == 401

    # Non-existent valid-formatted key
    resp_nonexistent = await client.post(
        "/v1/events",
        json={"page_path": "/home", "event_name": "page_view"},
        headers={"X-Write-Key": "apk_live_00000000000000000000000000000000"},
    )
    assert resp_nonexistent.status_code == 401


@pytest.mark.asyncio
async def test_dashboard_rejects_missing_and_forged_tokens(client: AsyncClient):
    """Verify that administrative endpoints reject missing or forged bearer tokens."""
    # Missing token
    resp_no_token = await client.get("/api/v1/apps")
    assert resp_no_token.status_code == 401

    # Forged / malformed token
    resp_forged = await client.get(
        "/api/v1/apps",
        headers={"Authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.invalid.payload"},
    )
    assert resp_forged.status_code == 401

    # Expired token
    expired_token = create_access_token(
        {"sub": str(uuid.uuid4()), "email": "test@example.com", "role": "SuperAdmin"},
        expires_delta=timedelta(seconds=-10),
    )
    resp_expired = await client.get(
        "/api/v1/apps",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert resp_expired.status_code == 401


@pytest.mark.asyncio
async def test_rbac_privilege_escalation_prevention(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Verify that an AppViewer cannot perform SuperAdmin operations."""
    viewer = User(
        email=f"viewer_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=get_password_hash("ViewerPass123!"),
        role=UserRole.AppViewer,
        status="ACTIVE",
    )
    db_session.add(viewer)
    await db_session.commit()
    await db_session.refresh(viewer)

    viewer_token = create_access_token({"sub": str(viewer.id), "email": viewer.email, "role": "AppViewer"})
    headers = {"Authorization": f"Bearer {viewer_token}"}

    # Attempt to create application (SuperAdmin only)
    resp = await client.post(
        "/api/v1/apps",
        json={"app_id": f"malicious_app_{uuid.uuid4().hex[:6]}", "name": "Hack Attempt"},
        headers=headers,
    )
    assert resp.status_code == 403
    assert "SuperAdmin" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_tenant_boundary_denial_for_unauthorized_app(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Verify that a user without grant cannot access another application's keys."""
    user = User(
        email=f"limited_user_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=get_password_hash("LimitedPass123!"),
        role=UserRole.AppAdmin,
        status="ACTIVE",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    # Grant access ONLY to 'askanna'
    perm = UserAppPermission(
        user_id=user.id,
        app_id="askanna",
        granted_role=UserRole.AppAdmin,
    )
    db_session.add(perm)
    await db_session.commit()

    user_token = create_access_token({"sub": str(user.id), "email": user.email, "role": "AppAdmin"})
    headers = {"Authorization": f"Bearer {user_token}"}

    # Allowed: list askanna keys
    resp_allowed = await client.get("/api/v1/apps/askanna/keys", headers=headers)
    assert resp_allowed.status_code == 200

    # Denied: attempt to list roomlyst keys
    resp_denied = await client.get("/api/v1/apps/roomlyst/keys", headers=headers)
    assert resp_denied.status_code == 403
    assert "Access denied" in resp_denied.json()["detail"]
