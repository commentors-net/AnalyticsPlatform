"""Integration tests for Beacon transmission, proxy headers, and CORS caching (M2-08, M2-10)."""

import json
import pytest
from httpx import AsyncClient
from api.app.core.config import settings
from api.app.models.user import User
from api.app.services.proxy import extract_client_ip
from starlette.requests import Request


@pytest.mark.asyncio
async def test_beacon_query_param_key_strictly_rejected(
    client: AsyncClient,
    superadmin_user: User,
):
    """Verify that passing write keys via query parameters is strictly rejected (M2-08)."""
    login_resp = await client.post(
        "/api/v1/auth/google",
        json={"id_token": f"mock_google_id_token:{superadmin_user.email}:sub_admin_123"},
    )
    auth_headers = {"Authorization": f"Bearer {login_resp.json()['access_token']}"}

    key_resp = await client.post(
        "/api/v1/apps/askanna/keys",
        json={"environment": "live", "name": "Beacon Query Key"},
        headers=auth_headers,
    )
    raw_key = key_resp.json()["raw_key"]

    # Passing key in query parameter must return 401 Unauthorized
    resp = await client.post(
        f"/v1/events?key={raw_key}",
        json={
            "event_type": "pageview",
            "event_name": "page_view",
            "page_path": "/exit-survey",
        },
    )
    assert resp.status_code == 401
    assert "Missing write_key" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_beacon_body_key_and_text_plain_ingestion(
    client: AsyncClient,
    superadmin_user: User,
):
    """Verify sendBeacon using text/plain body with write_key is parsed and accepted (M2-08)."""
    login_resp = await client.post(
        "/api/v1/auth/google",
        json={"id_token": f"mock_google_id_token:{superadmin_user.email}:sub_admin_123"},
    )
    auth_headers = {"Authorization": f"Bearer {login_resp.json()['access_token']}"}

    key_resp = await client.post(
        "/api/v1/apps/askanna/keys",
        json={"environment": "live", "name": "Beacon Body Key"},
        headers=auth_headers,
    )
    raw_key = key_resp.json()["raw_key"]

    # Beacon sends text/plain blob containing JSON with write_key
    payload = json.dumps({
        "write_key": raw_key,
        "event_type": "pageview",
        "event_name": "beacon_unload_view",
        "page_path": "/exit-survey",
    })

    resp = await client.post(
        "/v1/events",
        content=payload,
        headers={"Content-Type": "text/plain"},
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "success"


@pytest.mark.asyncio
async def test_cors_preflight_returns_caching_headers(
    client: AsyncClient,
):
    """Verify CORS preflight returns 24-hour cache max age and reflects Origin (M2-08)."""
    resp = await client.options(
        "/v1/events",
        headers={
            "Origin": "https://askanna.ai",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert resp.status_code in (200, 204)
    assert resp.headers.get("access-control-max-age") == "86400"
    assert "POST" in resp.headers.get("access-control-allow-methods", "")
    assert resp.headers.get("access-control-allow-origin") == "https://askanna.ai"


def test_proxy_trust_boundary_discards_spoofed_headers(monkeypatch):
    """Verify proxy extraction discards XFF if direct peer is untrusted (M2-10)."""
    monkeypatch.setattr(settings, "BEHIND_PROXY", True)
    monkeypatch.setattr(settings, "TRUSTED_PROXIES", "127.0.0.1,::1,10.0.0.0/8")

    # 1. Untrusted client attempting to spoof Google Cloud / client IP
    scope_untrusted = {
        "type": "http",
        "client": ("198.51.100.25", 54321),  # Untrusted external IP
        "headers": [
            (b"x-forwarded-for", b"203.0.113.50, 10.0.0.1"),
        ],
    }
    req_untrusted = Request(scope_untrusted)
    ip = extract_client_ip(req_untrusted)
    # Untrusted direct peer: XFF must be completely ignored
    assert ip == "198.51.100.25"

    # 2. Trusted proxy peer (e.g. 127.0.0.1 or 169.254.8.1)
    scope_trusted = {
        "type": "http",
        "client": ("127.0.0.1", 54321),  # Trusted proxy
        "headers": [
            (b"x-forwarded-for", b"203.0.113.99, 10.0.0.1"),
        ],
    }
    req_trusted = Request(scope_trusted)
    ip_trusted = extract_client_ip(req_trusted)
    # Walks right-to-left stripping trusted hops (10.0.0.1 is in 10.0.0.0/8 trusted proxy list)
    assert ip_trusted == "203.0.113.99"
