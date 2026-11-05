"""Integration Tests for Analytics Dashboard Endpoints & Audit Logging (Milestone M3)."""

import uuid
from datetime import datetime, timezone
import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.core.security import create_access_token
from api.app.models.api_key import EnvironmentType
from api.app.models.user import AuditLog, User, UserRole


@pytest.mark.asyncio
async def test_dashboard_analytics_lifecycle_and_tenant_isolation(
    client: AsyncClient,
    db_session: AsyncSession,
    superadmin_user: User,
):
    """Verify overview, timeseries, top pages, geo, export and strict tenant isolation."""
    # 1. Create two separate applications
    app1_id = f"app-dash-{uuid.uuid4().hex[:8]}"
    app2_id = f"app-dash-{uuid.uuid4().hex[:8]}"

    db_session.create_app(app1_id, "Dashboard App 1", "https://app1.test")
    db_session.create_app(app2_id, "Dashboard App 2", "https://app2.test")

    # 2. Ingest telemetry events into App 1 (live & test) and App 2
    now = datetime.now(timezone.utc)
    ev_app1_live = str(uuid.uuid4())
    ev_app1_test = str(uuid.uuid4())
    ev_app2_live = str(uuid.uuid4())

    e1 = {
        "event_id": ev_app1_live, "app_id": app1_id, "environment": "live", "event_type": "pageview",
        "event_name": "pageview", "visitor_id": "v1", "session_id": "s1", "page_path": "/pricing",
        "referrer_domain": "google.com", "device_family": "desktop", "browser_family": "Chrome",
        "os_family": "Windows", "country_code": "US", "city_name": "Austin", "ip_masked": "192.168.1.0",
        "duration_ms": 4500, "metadata": {}, "timestamp": now.isoformat()
    }
    s1 = {
        "session_id": "s1", "visitor_id": "v1", "started_at": now.isoformat(), "duration_seconds": 45,
        "pageviews_count": 1, "entry_page": "/pricing", "is_bounce": True, "referrer_domain": "google.com",
        "country_code": "US", "device_family": "desktop"
    }
    db_session.claim_and_ingest_event(app1_id, "live", ev_app1_live, e1, s1)

    e2 = {
        "event_id": ev_app1_test, "app_id": app1_id, "environment": "test", "event_type": "pageview",
        "event_name": "pageview", "visitor_id": "v1", "session_id": "s1_test", "page_path": "/secret-beta",
        "referrer_domain": "direct", "device_family": "mobile", "browser_family": "Safari",
        "os_family": "iOS", "country_code": "CA", "city_name": "Toronto", "ip_masked": "10.0.0.0",
        "duration_ms": 1200, "metadata": {}, "timestamp": now.isoformat()
    }
    s2 = {
        "session_id": "s1_test", "visitor_id": "v1", "started_at": now.isoformat(), "duration_seconds": 12,
        "pageviews_count": 1, "entry_page": "/secret-beta", "is_bounce": False, "referrer_domain": "direct",
        "country_code": "CA", "device_family": "mobile"
    }
    db_session.claim_and_ingest_event(app1_id, "test", ev_app1_test, e2, s2)

    e3 = {
        "event_id": ev_app2_live, "app_id": app2_id, "environment": "live", "event_type": "pageview",
        "event_name": "pageview", "visitor_id": "v2", "session_id": "s2", "page_path": "/app2-private",
        "referrer_domain": "bing.com", "device_family": "desktop", "browser_family": "Firefox",
        "os_family": "Linux", "country_code": "DE", "city_name": "Berlin", "ip_masked": "172.16.0.0",
        "duration_ms": 3000, "metadata": {}, "timestamp": now.isoformat()
    }
    s3 = {
        "session_id": "s2", "visitor_id": "v2", "started_at": now.isoformat(), "duration_seconds": 30,
        "pageviews_count": 2, "entry_page": "/app2-private", "is_bounce": False, "referrer_domain": "bing.com",
        "country_code": "DE", "device_family": "desktop"
    }
    db_session.claim_and_ingest_event(app2_id, "live", ev_app2_live, e3, s3)

    # Create admin auth token
    token = create_access_token({"sub": str(superadmin_user.id), "role": superadmin_user.role.value})
    auth_headers = {"Authorization": f"Bearer {token}"}

    # 3. Test Overview Metrics for App 1 (LIVE)
    res_overview = await client.get(
        f"/api/v1/analytics/overview?app_id={app1_id}&environment=live",
        headers=auth_headers,
    )
    assert res_overview.status_code == 200, res_overview.text
    data_overview = res_overview.json()
    assert data_overview["app_id"] == app1_id
    assert data_overview["environment"] == "live"
    assert data_overview["pageviews"]["value"] == 1.0
    assert data_overview["sessions"]["value"] == 1.0

    # 3b. Test Timeseries Trends
    res_ts = await client.get(
        f"/api/v1/analytics/timeseries?app_id={app1_id}&environment=live&interval=day",
        headers=auth_headers,
    )
    assert res_ts.status_code == 200
    ts_data = res_ts.json()
    assert len(ts_data) >= 1
    assert ts_data[0]["pageviews"] == 1

    # 4. Verify Environment Isolation (LIVE vs TEST)
    # LIVE query should NOT see /secret-beta or test metrics
    res_pages_live = await client.get(
        f"/api/v1/analytics/pages?app_id={app1_id}&environment=live",
        headers=auth_headers,
    )
    assert res_pages_live.status_code == 200
    pages_live = res_pages_live.json()
    assert len(pages_live) == 1
    assert pages_live[0]["page_path"] == "/pricing"

    # TEST query should see /secret-beta
    res_pages_test = await client.get(
        f"/api/v1/analytics/pages?app_id={app1_id}&environment=test",
        headers=auth_headers,
    )
    assert res_pages_test.status_code == 200
    pages_test = res_pages_test.json()
    assert len(pages_test) == 1
    assert pages_test[0]["page_path"] == "/secret-beta"

    # 5. Verify Cross-Tenant Isolation (App 1 cannot see App 2)
    res_pages_app2 = await client.get(
        f"/api/v1/analytics/pages?app_id={app2_id}&environment=live",
        headers=auth_headers,
    )
    assert res_pages_app2.status_code == 200
    assert res_pages_app2.json()[0]["page_path"] == "/app2-private"

    # 6. Test Devices Breakdown
    res_devices = await client.get(
        f"/api/v1/analytics/devices?app_id={app1_id}&environment=live",
        headers=auth_headers,
    )
    assert res_devices.status_code == 200
    dev_data = res_devices.json()
    assert any(d["name"] == "desktop" for d in dev_data["devices"])
    assert any(b["name"] == "Chrome" for b in dev_data["browsers"])

    # 7. Test Geo Breakdown
    res_geo = await client.get(
        f"/api/v1/analytics/geo?app_id={app1_id}&environment=live",
        headers=auth_headers,
    )
    assert res_geo.status_code == 200
    geo_data = res_geo.json()
    # Legacy seeded geography without verified provenance must not claim a location.
    assert geo_data[0]["country_code"] == "Unknown"
    assert geo_data[0]["city_name"] is None

    # 8. Test Recent Events Feed
    res_recent = await client.get(
        f"/api/v1/analytics/recent?app_id={app1_id}&environment=live",
        headers=auth_headers,
    )
    assert res_recent.status_code == 200
    recent_items = res_recent.json()
    assert len(recent_items) == 1
    assert recent_items[0]["event_name"] == "pageview"
    assert recent_items[0]["page_path"] == "/pricing"

    # 9. Test CSV Export and Audit Logging
    res_export = await client.post(
        f"/api/v1/analytics/export?app_id={app1_id}&environment=live&export_format=csv",
        headers=auth_headers,
    )
    assert res_export.status_code == 200
    assert "text/csv" in res_export.headers["content-type"]
    csv_text = res_export.text
    assert "page_path" in csv_text
    assert "/pricing" in csv_text

    # Verify immutable AuditLog created in database
    audit_logs = db_session.db.audit_logs_col.where("user_id", "==", str(superadmin_user.id)).get()
    assert len(audit_logs) >= 1
    audit_row = audit_logs[0].to_dict()
    assert audit_row["action"] == "EXPORT_ANALYTICS"
    assert audit_row["resource_id"] == app1_id
    assert audit_row["details"]["environment"] == "live"


@pytest.mark.asyncio
async def test_dashboard_unauthorized_access_rejected(client: AsyncClient):
    """Verify that unauthenticated requests to analytics endpoints are strictly denied."""
    res = await client.get("/api/v1/analytics/overview?app_id=any-app")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_dashboard_static_assets_serving(client: AsyncClient):
    """Verify that static dashboard SPA files are properly served."""
    res = await client.get("/dashboard/")
    assert res.status_code == 200
    assert "Analytics Platform Dashboard" in res.text
    assert "/dashboard/app.js" in res.text
