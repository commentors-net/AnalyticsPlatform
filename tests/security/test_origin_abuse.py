"""Security tests for Origin validation and CORS abuse protection."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from api.app.models.user import User


@pytest.mark.asyncio
async def test_origin_validation_allows_authorized_origin(
    client: AsyncClient,
    superadmin_user: User,
):
    """Verify that events sent with authorized Origin header succeed."""
    login_resp = await client.post(
        "/api/v1/auth/google",
        json={"id_token": f"mock_google_id_token:{superadmin_user.email}:sub_admin_123"},
    )
    auth_headers = {"Authorization": f"Bearer {login_resp.json()['access_token']}"}

    key_resp = await client.post(
        "/api/v1/apps/askanna/keys",
        json={"environment": "live", "name": "AskAnna Origin Test Key"},
        headers=auth_headers,
    )
    raw_key = key_resp.json()["raw_key"]

    resp = await client.post(
        "/v1/events",
        json={
            "event_type": "pageview",
            "event_name": "page_view",
            "page_path": "/home",
        },
        headers={
            "X-Write-Key": raw_key,
            "Origin": "https://askanna.ai",
        },
    )
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_origin_validation_blocks_unauthorized_origin(
    client: AsyncClient,
    superadmin_user: User,
):
    """Verify that events sent with unauthorized Origin header are rejected with 403."""
    login_resp = await client.post(
        "/api/v1/auth/google",
        json={"id_token": f"mock_google_id_token:{superadmin_user.email}:sub_admin_123"},
    )
    auth_headers = {"Authorization": f"Bearer {login_resp.json()['access_token']}"}

    key_resp = await client.post(
        "/api/v1/apps/askanna/keys",
        json={"environment": "live", "name": "AskAnna Origin Test Key 2"},
        headers=auth_headers,
    )
    raw_key = key_resp.json()["raw_key"]

    resp = await client.post(
        "/v1/events",
        json={
            "event_type": "pageview",
            "event_name": "page_view",
            "page_path": "/home",
        },
        headers={
            "X-Write-Key": raw_key,
            "Origin": "https://malicious-tracker-abuser.xyz",
        },
    )
    assert resp.status_code == 403
    assert "origin not authorized" in resp.json()["detail"].lower()
