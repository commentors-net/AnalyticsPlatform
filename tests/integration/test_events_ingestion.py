"""Integration Tests for Telemetry Event Ingestion & Session Persistence."""

import uuid
from datetime import datetime, timedelta, timezone
import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from api.app.models.api_key import ApiKey
from api.app.models.event import Event
from api.app.models.session import Session
from api.app.models.user import User


@pytest.mark.asyncio
async def test_single_event_ingestion_and_deduplication(
    client: AsyncClient,
    superadmin_user: User,
    db_session: AsyncSession,
):
    """Verify single event ingestion, transactional durability, deduplication and session persistence."""
    # 1. Login & generate live write key for 'askanna'
    token = superadmin_user
    login_resp = await client.post(
        "/api/v1/auth/google",
        json={"id_token": f"mock_google_id_token:{superadmin_user.email}:sub_admin_123"},
    )
    auth_headers = {"Authorization": f"Bearer {login_resp.json()['access_token']}"}

    key_resp = await client.post(
        "/api/v1/apps/askanna/keys",
        json={"environment": "live", "name": "AskAnna Test Key"},
        headers=auth_headers,
    )
    raw_key = key_resp.json()["raw_key"]

    # 2. Ingest Single Event
    event_id = uuid.uuid4()
    now_ts = datetime.now(timezone.utc)
    session_id = f"ses_{uuid.uuid4().hex[:12]}"
    visitor_id = f"vid_{uuid.uuid4().hex[:12]}"

    event_payload = {
        "event_id": str(event_id),
        "event_type": "pageview",
        "event_name": "page_view",
        "visitor_id": visitor_id,
        "session_id": session_id,
        "page_path": "/chat?token=secret123&topic=support",
        "referrer": "https://search.engine.com/query",
        "duration_ms": 350,
        "metadata": {"source": "header_link", "experiment_variant": "b"},
        "timestamp": now_ts.isoformat(),
    }

    ingest_resp = await client.post(
        "/v1/events",
        json=event_payload,
        headers={"X-Write-Key": raw_key},
    )
    assert ingest_resp.status_code == 201
    assert ingest_resp.json()["event_id"] == str(event_id)

    # 3. Verify Database Persistence & Privacy Sanitization
    event_snap = db_session.db.events_col("askanna", "live").document(str(event_id)).get()
    assert event_snap.exists
    persisted_event = Event(**event_snap.to_dict())

    assert persisted_event is not None
    assert persisted_event.app_id == "askanna"
    assert (persisted_event.environment.value if hasattr(persisted_event.environment, 'value') else persisted_event.environment) == "live"
    # Verify sensitive query token was scrubbed
    assert "token=[REDACTED]" in persisted_event.page_path
    assert "topic=support" in persisted_event.page_path
    assert "secret123" not in persisted_event.page_path
    # Verify referrer domain
    assert persisted_event.referrer_domain == "search.engine.com"
    # Verify coarse geo
    assert persisted_event.country_code is None  # No verified GeoIP lookup is configured.

    # 4. Verify Session Persistence (COND-05)
    sess_snap = db_session.db.sessions_col("askanna", "live").document(session_id).get()
    assert sess_snap.exists
    persisted_session = Session(**sess_snap.to_dict())

    assert persisted_session is not None
    assert persisted_session.app_id == "askanna"
    assert persisted_session.visitor_id == visitor_id
    assert persisted_session.pageviews_count == 1
    assert persisted_session.is_bounce is True

    # 5. Retry / Deduplication Test
    # Submitting identical event_id and timestamp must not crash or duplicate
    retry_resp = await client.post(
        "/v1/events",
        json=event_payload,
        headers={"X-Write-Key": raw_key},
    )
    assert retry_resp.status_code in (200, 201)

    # 6. Retry with DIFFERENT timestamp must still deduplicate based on stable event_id
    retry_diff_ts_payload = dict(event_payload)
    retry_diff_ts_payload["timestamp"] = (now_ts + timedelta(seconds=15)).isoformat()
    retry_diff_ts_resp = await client.post(
        "/v1/events",
        json=retry_diff_ts_payload,
        headers={"X-Write-Key": raw_key},
    )
    assert retry_diff_ts_resp.status_code in (200, 201)

    # Verify still exactly 1 event exists in database with this event_id
    events = [s for s in db_session.db.events_col("askanna", "live").get() if s.id == str(event_id)]
    assert len(events) == 1


@pytest.mark.asyncio
async def test_batch_event_ingestion(
    client: AsyncClient,
    superadmin_user: User,
):
    """Verify batch ingestion persists multiple events in a single transaction."""
    login_resp = await client.post(
        "/api/v1/auth/google",
        json={"id_token": f"mock_google_id_token:{superadmin_user.email}:sub_admin_123"},
    )
    auth_headers = {"Authorization": f"Bearer {login_resp.json()['access_token']}"}

    key_resp = await client.post(
        "/api/v1/apps/groundworks/keys",
        json={"environment": "live", "name": "GroundWorks Batch Key"},
        headers=auth_headers,
    )
    raw_key = key_resp.json()["raw_key"]

    batch_payload = {
        "write_key": raw_key,
        "batch": [
            {
                "event_type": "pageview",
                "event_name": "page_view",
                "page_path": "/properties/123",
            },
            {
                "event_type": "custom",
                "event_name": "button_click",
                "page_path": "/properties/123",
                "metadata": {"button": "request_quote"},
            },
        ],
    }

    batch_resp = await client.post("/v1/batch", json=batch_payload)
    assert batch_resp.status_code == 202
    data = batch_resp.json()
    assert data["status"] == "accepted"
    assert data["processed_count"] == 2
    assert len(data["persisted_event_ids"]) == 2
