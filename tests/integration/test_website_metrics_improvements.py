"""Focused Integration Tests for Website Analytics Metrics and Event Contract (Prompt 20).

Validates:
1. Unique visitors and sessions when approved anonymous identifiers are supplied vs absent identifiers.
2. Single-page website engagement duration and bounce-rate definitions (>= 10s engagement = not a bounce).
3. Traffic trends contiguous bucketing for sparse data (including days with zero events).
4. Recent events source mapping (eliminating 'Not reported' for valid events).
5. Reviewed device/browser categories, referrer categories, and trustworthy country information.
6. Distinction between unavailable metrics (available=False), genuine zero values, and synthetic test data.
"""

import uuid
from datetime import datetime, timedelta, timezone
import pytest
from httpx import AsyncClient

from api.app.core.security import create_access_token
from api.app.services.sanitizer import classify_referrer


@pytest.mark.asyncio
async def test_unique_visitors_and_absent_identifiers(client: AsyncClient, db_session, superadmin_user):
    """Verify that visitors and sessions are accurately tracked when IDs are provided vs absent."""
    app_id = f"app-ids-{uuid.uuid4().hex[:8]}"
    db_session.create_app(app_id, "ID Test App", classification="REAL")
    token = create_access_token({"sub": str(superadmin_user.id), "role": superadmin_user.role.value})
    auth_headers = {"Authorization": f"Bearer {token}"}

    now = datetime.now(timezone.utc)
    # Scenario A: Events WITH approved anonymous identifiers
    ev1 = str(uuid.uuid4())
    ev2 = str(uuid.uuid4())
    e1 = {
        "event_id": ev1, "app_id": app_id, "environment": "live", "event_type": "pageview",
        "event_name": "pageview", "visitor_id": "v_anon_1", "session_id": "s_anon_1",
        "page_path": "/", "timestamp": now.isoformat(), "metadata": {"source": "python"},
    }
    s1 = {
        "session_id": "s_anon_1", "visitor_id": "v_anon_1", "started_at": now.isoformat(),
        "pageviews_count": 1, "duration_seconds": 15, "entry_page": "/",
    }
    e2 = {
        "event_id": ev2, "app_id": app_id, "environment": "live", "event_type": "pageview",
        "event_name": "pageview", "visitor_id": "v_anon_2", "session_id": "s_anon_2",
        "page_path": "/features", "timestamp": now.isoformat(), "metadata": {"source": "python"},
    }
    s2 = {
        "session_id": "s_anon_2", "visitor_id": "v_anon_2", "started_at": now.isoformat(),
        "pageviews_count": 1, "duration_seconds": 5, "entry_page": "/features",
    }
    db_session.claim_and_ingest_event(app_id, "live", ev1, e1, s1)
    db_session.claim_and_ingest_event(app_id, "live", ev2, e2, s2)

    res = await client.get(f"/api/v1/analytics/overview?app_id={app_id}&environment=live", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["data_status"] == "live"
    assert data["visitors"]["value"] == 2.0
    assert data["visitors"]["available"] is True
    assert data["sessions"]["value"] == 2.0
    assert data["sessions"]["available"] is True

    # Scenario B: Second app where events have NO visitor_id and NO session_id (NO_STORAGE / absent identifiers)
    app2_id = f"app-noids-{uuid.uuid4().hex[:8]}"
    db_session.create_app(app2_id, "No IDs App", classification="REAL")
    ev3 = str(uuid.uuid4())
    e3 = {
        "event_id": ev3, "app_id": app2_id, "environment": "live", "event_type": "pageview",
        "event_name": "pageview", "visitor_id": None, "session_id": None,
        "page_path": "/", "timestamp": now.isoformat(), "metadata": {"source": "server"},
    }
    s3 = {
        "session_id": f"sess_{uuid.uuid4().hex[:12]}", "visitor_id": None, "started_at": now.isoformat(),
        "pageviews_count": 1, "duration_seconds": 0, "entry_page": "/",
    }
    db_session.claim_and_ingest_event(app2_id, "live", ev3, e3, s3)

    res2 = await client.get(f"/api/v1/analytics/overview?app_id={app2_id}&environment=live", headers=auth_headers)
    assert res2.status_code == 200
    data2 = res2.json()
    # When identifiers are absent, visitors and sessions are marked as unavailable (not tracked), distinct from 0
    assert data2["visitors"]["available"] is False
    assert data2["sessions"]["available"] is False
    assert data2["pageviews"]["available"] is True
    assert data2["pageviews"]["value"] == 1.0


@pytest.mark.asyncio
async def test_single_page_website_duration_and_bounce_rate(client: AsyncClient, db_session, superadmin_user):
    """Verify single-page website bounce rate definition: >= 10s engagement is NOT a bounce."""
    app_id = f"app-spa-{uuid.uuid4().hex[:8]}"
    db_session.create_app(app_id, "SPA Test App", classification="REAL")
    token = create_access_token({"sub": str(superadmin_user.id), "role": superadmin_user.role.value})
    auth_headers = {"Authorization": f"Bearer {token}"}

    now = datetime.now(timezone.utc)

    # Session 1: Engaged single-page visitor (stayed 30 seconds on homepage)
    s1_id = f"ses_spa_1_{uuid.uuid4().hex[:8]}"
    ev1 = str(uuid.uuid4())
    e1 = {
        "event_id": ev1, "app_id": app_id, "environment": "live", "event_type": "pageview",
        "event_name": "pageview", "visitor_id": "v1", "session_id": s1_id,
        "page_path": "/", "duration_ms": 30000, "timestamp": now.isoformat(),
    }
    s1 = {
        "session_id": s1_id, "visitor_id": "v1", "started_at": now.isoformat(),
        "pageviews_count": 1, "duration_seconds": 30, "entry_page": "/", "is_bounce": True,
    }
    db_session.claim_and_ingest_event(app_id, "live", ev1, e1, s1)

    # Session 2: Bounced visitor (stayed only 3 seconds and left)
    s2_id = f"ses_spa_2_{uuid.uuid4().hex[:8]}"
    ev2 = str(uuid.uuid4())
    e2 = {
        "event_id": ev2, "app_id": app_id, "environment": "live", "event_type": "pageview",
        "event_name": "pageview", "visitor_id": "v2", "session_id": s2_id,
        "page_path": "/", "duration_ms": 3000, "timestamp": now.isoformat(),
    }
    s2 = {
        "session_id": s2_id, "visitor_id": "v2", "started_at": now.isoformat(),
        "pageviews_count": 1, "duration_seconds": 3, "entry_page": "/", "is_bounce": True,
    }
    db_session.claim_and_ingest_event(app_id, "live", ev2, e2, s2)

    res = await client.get(f"/api/v1/analytics/overview?app_id={app_id}&environment=live", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["sessions"]["value"] == 2.0
    # Exactly 1 bounce out of 2 sessions -> 50.0% bounce rate (NOT 100%)
    assert data["bounce_rate"]["value"] == 50.0
    # Average engagement duration: (30 + 3) / 2 = 16.5 seconds
    assert data["avg_duration_sec"]["value"] == 16.5


@pytest.mark.asyncio
async def test_timeseries_sparse_data_zero_event_days(client: AsyncClient, db_session, superadmin_user):
    """Verify that Traffic Trends returns contiguous intervals for all days, even with zero events."""
    app_id = f"app-sparse-{uuid.uuid4().hex[:8]}"
    db_session.create_app(app_id, "Sparse App")
    token = create_access_token({"sub": str(superadmin_user.id), "role": superadmin_user.role.value})
    auth_headers = {"Authorization": f"Bearer {token}"}

    # Ingest exactly 1 event on day 3 of a 7-day window
    end_dt = datetime(2026, 11, 5, 12, 0, 0, tzinfo=timezone.utc)
    start_dt = end_dt - timedelta(days=6)
    event_ts = start_dt + timedelta(days=2)  # Event on day 3

    ev = str(uuid.uuid4())
    e = {
        "event_id": ev, "app_id": app_id, "environment": "live", "event_type": "pageview",
        "event_name": "pageview", "visitor_id": "v1", "session_id": "s1",
        "page_path": "/", "timestamp": event_ts.isoformat(),
    }
    s = {
        "session_id": "s1", "visitor_id": "v1", "started_at": event_ts.isoformat(),
        "pageviews_count": 1, "duration_seconds": 10, "entry_page": "/",
    }
    db_session.claim_and_ingest_event(app_id, "live", ev, e, s)

    # Query with explicit date range (as the dashboard does)
    start_str = start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    end_str = end_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    res = await client.get(
        f"/api/v1/analytics/timeseries?app_id={app_id}&environment=live&interval=day&start_date={start_str}&end_date={end_str}",
        headers=auth_headers,
    )
    assert res.status_code == 200
    points = res.json()

    # Must contain 7 contiguous day points
    assert len(points) == 7
    # Exactly one point has pageviews=1, and the other 6 days have pageviews=0
    ones = [p for p in points if p["pageviews"] == 1]
    zeros = [p for p in points if p["pageviews"] == 0]
    assert len(ones) == 1
    assert len(zeros) == 6


@pytest.mark.asyncio
async def test_recent_events_source_mapping_and_trustworthy_country(client: AsyncClient, db_session, superadmin_user):
    """Verify source mapping resolves accurately and trustworthy country information is accepted."""
    app_id = f"app-src-{uuid.uuid4().hex[:8]}"
    db_session.create_app(app_id, "Source App")
    token = create_access_token({"sub": str(superadmin_user.id), "role": superadmin_user.role.value})
    auth_headers = {"Authorization": f"Bearer {token}"}

    now = datetime.now(timezone.utc)

    # Ingest event with forwarded Python source and trustworthy country
    ev1 = str(uuid.uuid4())
    e1 = {
        "event_id": ev1, "app_id": app_id, "environment": "live", "event_type": "pageview",
        "event_name": "pageview", "visitor_id": "v1", "session_id": "s1", "page_path": "/home",
        "source": "python", "country_code": "US", "geo_source": "trusted_edge_or_client",
        "browser_family": "Chrome", "device_family": "desktop", "os_family": "macOS",
        "duration_ms": 15000, "timestamp": now.isoformat(), "metadata": {"source": "python"},
    }
    s1 = {"session_id": "s1", "visitor_id": "v1", "started_at": now.isoformat(), "pageviews_count": 1}
    db_session.claim_and_ingest_event(app_id, "live", ev1, e1, s1)

    # Ingest browser event where source is inferred from browser family
    ev2 = str(uuid.uuid4())
    e2 = {
        "event_id": ev2, "app_id": app_id, "environment": "live", "event_type": "pageview",
        "event_name": "pageview", "visitor_id": "v2", "session_id": "s2", "page_path": "/docs",
        "browser_family": "Safari", "device_family": "mobile", "os_family": "iOS",
        "timestamp": now.isoformat(), "metadata": {},
    }
    s2 = {"session_id": "s2", "visitor_id": "v2", "started_at": now.isoformat(), "pageviews_count": 1}
    db_session.claim_and_ingest_event(app_id, "live", ev2, e2, s2)

    res = await client.get(f"/api/v1/analytics/recent?app_id={app_id}&environment=live", headers=auth_headers)
    assert res.status_code == 200
    recent = res.json()
    assert len(recent) == 2

    e1_item = next(r for r in recent if r["event_id"] == ev1)
    e2_item = next(r for r in recent if r["event_id"] == ev2)

    assert e1_item["source"] == "python"
    assert e1_item["country_code"] == "US"
    assert e1_item["os_family"] in ("macOS", "Mac OS X")

    assert e2_item["source"] == "browser"
    assert e2_item["browser_family"] == "Safari"
    assert e2_item["device_family"] == "mobile"


def test_referrer_categorization():
    """Verify that coarse referrer domains are accurately categorized into Search, Social, Direct, Internal, and Referral."""
    assert classify_referrer(None) == "Direct / None"
    assert classify_referrer("direct") == "Direct / None"
    assert classify_referrer("google.com") == "Search"
    assert classify_referrer("www.bing.com") == "Search"
    assert classify_referrer("duckduckgo.com") == "Search"
    assert classify_referrer("t.co") == "Social"
    assert classify_referrer("www.linkedin.com") == "Social"
    assert classify_referrer("facebook.com") == "Social"
    assert classify_referrer("reddit.com") == "Social"
    assert classify_referrer("askanna.online", allowed_origins="https://askanna.online") == "Internal"
    assert classify_referrer("techcrunch.com") == "Referral"
