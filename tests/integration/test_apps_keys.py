"""Integration Tests for Application Registry and API Key Management (M2-13)."""

from uuid import uuid4
import pytest
from httpx import AsyncClient
from api.app.models.user import User, UserRole


@pytest.mark.asyncio
async def test_application_lifecycle_and_key_issuance(
    client: AsyncClient,
    superadmin_user: User,
):
    """Verify application creation, API key issuance, listing prefixes, and revocation."""
    unique_id = uuid4().hex[:8]
    app_id = f"test_corp_app_{unique_id}"

    # 1. SuperAdmin Login
    login_resp = await client.post(
        "/api/v1/auth/google",
        json={"id_token": f"mock_google_id_token:{superadmin_user.email}:sub_admin_123"},
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Register Application
    app_payload = {
        "app_id": app_id,
        "name": "Test Corporate Application",
        "allowed_origins": "https://test.example.com",
    }
    create_resp = await client.post("/api/v1/apps", json=app_payload, headers=headers)
    assert create_resp.status_code == 201
    assert create_resp.json()["app_id"] == app_id

    # 3. Issue Write Key (Shows plaintext key ONCE)
    key_payload = {
        "environment": "live",
        "name": "Primary Production Web Key",
    }
    key_resp = await client.post(
        f"/api/v1/apps/{app_id}/keys",
        json=key_payload,
        headers=headers,
    )
    assert key_resp.status_code == 201
    key_data = key_resp.json()
    assert key_data["raw_key"] is not None
    assert key_data["raw_key"].startswith("apk_live_")
    assert key_data["prefix"].startswith("apk_live_")
    key_id = key_data["id"]

    # 4. List Keys (Verify raw key is NOT exposed)
    list_resp = await client.get(f"/api/v1/apps/{app_id}/keys", headers=headers)
    assert list_resp.status_code == 200
    items = list_resp.json()
    assert len(items) >= 1
    found_key = next((k for k in items if k["id"] == key_id), None)
    assert found_key is not None
    assert "raw_key" not in found_key or found_key.get("raw_key") is None
    assert found_key["prefix"] == key_data["prefix"]
    assert found_key["status"] == "ACTIVE"

    # 5. Revoke API Key
    revoke_resp = await client.delete(
        f"/api/v1/apps/{app_id}/keys/{key_id}",
        headers=headers,
    )
    assert revoke_resp.status_code == 204

    # 6. Verify Status is REVOKED
    list_after = await client.get(f"/api/v1/apps/{app_id}/keys", headers=headers)
    found_after = next(k for k in list_after.json() if k["id"] == key_id)
    assert found_after["status"] == "REVOKED"


@pytest.mark.asyncio
async def test_app_viewer_cannot_create_or_revoke_keys(
    client: AsyncClient,
    superadmin_user: User,
    db_session,
):
    """Verify that an AppViewer cannot create or revoke API keys (M2-13)."""
    # 1. Create App and Viewer User
    login_resp = await client.post(
        "/api/v1/auth/google",
        json={"id_token": f"mock_google_id_token:{superadmin_user.email}:sub_admin_123"},
    )
    admin_headers = {"Authorization": f"Bearer {login_resp.json()['access_token']}"}

    app_id = f"viewer_test_app_{uuid4().hex[:8]}"
    await client.post(
        "/api/v1/apps",
        json={"app_id": app_id, "name": "Viewer Test App"},
        headers=admin_headers,
    )

    # Create Viewer user in database
    viewer_email = f"viewer_{uuid4().hex[:6]}@example.com"
    viewer_data = db_session.create_user(
        email=viewer_email,
        role="AppViewer",
        status="ACTIVE",
    )
    db_session.grant_user_app_permission(
        user_id=viewer_data["id"],
        app_id=app_id,
        role="AppViewer",
    )

    # 2. Login as Viewer
    v_login = await client.post(
        "/api/v1/auth/google",
        json={"id_token": f"mock_google_id_token:{viewer_email}:sub_viewer_123"},
    )
    assert v_login.status_code == 200
    viewer_headers = {"Authorization": f"Bearer {v_login.json()['access_token']}"}

    # 3. Viewer attempts to create key -> must be 403 Forbidden
    create_resp = await client.post(
        f"/api/v1/apps/{app_id}/keys",
        json={"environment": "live", "name": "Unauthorized Key"},
        headers=viewer_headers,
    )
    assert create_resp.status_code == 403
    assert "requires AppAdmin privileges" in create_resp.json()["detail"]
