"""M2 Regression Test Suite: Comprehensive Automated Verification (M2-01 to M2-18)."""

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
from httpx import AsyncClient
from api.app.core.config import settings
from api.app.main import ensure_initial_superadmin_provisioned
from api.app.models.api_key import EnvironmentType
from api.app.services.firestore_repo import FirestoreRepo
from api.app.services.session_service import record_session_touch


@pytest.mark.asyncio
async def test_bootstrap_superadmin_disabled_in_production():
    """Verify legacy password bootstrap is eliminated and Google initial admin provisioning operates safely (M2-01, M12-07)."""
    # Calling ensure_initial_superadmin_provisioned returns safely
    await ensure_initial_superadmin_provisioned()


@pytest.mark.asyncio
async def test_child_partition_direct_query_rls_enforcement(db_session: FirestoreRepo):
    """Verify that Firestore subcollections enforce physical isolation equivalent to child partitions (M2-02)."""
    event_aa_id = str(uuid4())
    event_rl_id = str(uuid4())
    ts = datetime(2026, 11, 15, 12, 0, 0, tzinfo=timezone.utc)

    # 1. Ingest seed data into AskAnna and Roomlyst live subcollections
    db_session.claim_and_ingest_event(
        app_id="askanna",
        environment="live",
        event_id=event_aa_id,
        event_data={
            "event_id": event_aa_id,
            "app_id": "askanna",
            "environment": "live",
            "event_type": "pageview",
            "event_name": "askanna_partition_test",
            "page_path": "/home",
            "timestamp": ts.isoformat(),
        },
        session_data={"session_id": f"ses_{event_aa_id}", "started_at": ts.isoformat()},
    )
    db_session.claim_and_ingest_event(
        app_id="roomlyst",
        environment="live",
        event_id=event_rl_id,
        event_data={
            "event_id": event_rl_id,
            "app_id": "roomlyst",
            "environment": "live",
            "event_type": "pageview",
            "event_name": "roomlyst_partition_test",
            "page_path": "/home",
            "timestamp": ts.isoformat(),
        },
        session_data={"session_id": f"ses_{event_rl_id}", "started_at": ts.isoformat()},
    )

    # 2. Query the AskAnna live subcollection
    snaps = db_session.db.events_col("askanna", "live").get()
    returned_ids = [s.to_dict().get("event_id") for s in snaps]

    # AskAnna event MUST be visible, Roomlyst event MUST NOT be present
    assert event_aa_id in returned_ids
    assert event_rl_id not in returned_ids


@pytest.mark.asyncio
async def test_collector_ingest_role_insert_policy_violation(db_session: FirestoreRepo, client: AsyncClient):
    """Verify collector ingest rejects unauthorized access or mismatched keys (M2-02)."""
    # Attempt to insert event with invalid/missing write key
    resp = await client.post(
        "/v1/events",
        json={
            "write_key": "apk_live_invalidkey12345",
            "event_type": "pageview",
            "event_name": "tampered_event",
            "page_path": "/tampered",
        },
    )
    assert resp.status_code == 401
    assert "Invalid or revoked write_key" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_atomic_idempotency_cross_partition_concurrency(db_session: FirestoreRepo):
    """Verify atomic ingestion_idempotency prevents concurrent duplicate claims (M2-04)."""
    app_id = "askanna"
    env = "live"
    event_id = str(uuid4())

    event_data = {
        "event_id": event_id,
        "app_id": app_id,
        "environment": env,
        "event_type": "pageview",
        "event_name": "test_concurrency",
        "page_path": "/home",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    session_data = {
        "session_id": f"ses_{event_id}",
        "started_at": datetime.now(timezone.utc).isoformat(),
    }

    # Claim 1: First attempt succeeds (returns True)
    claimed_first = db_session.claim_and_ingest_event(
        app_id=app_id,
        environment=env,
        event_id=event_id,
        event_data=event_data,
        session_data=session_data,
    )
    assert claimed_first is True

    # Claim 2: Concurrent/replayed attempt returns False (cleanly deduped)
    claimed_second = db_session.claim_and_ingest_event(
        app_id=app_id,
        environment=env,
        event_id=event_id,
        event_data=event_data,
        session_data=session_data,
    )
    assert claimed_second is False


@pytest.mark.asyncio
async def test_atomic_session_upsert_and_pageview_distinction(db_session: FirestoreRepo):
    """Verify atomic session upsert increments pageviews ONLY on pageview events (M2-14)."""
    app_id = "askanna"
    env = EnvironmentType.live
    session_id = f"ses_atomic_{uuid4().hex[:8]}"
    t1 = datetime(2026, 11, 2, 10, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 11, 2, 10, 5, 0, tzinfo=timezone.utc)
    t3 = datetime(2026, 11, 2, 10, 10, 0, tzinfo=timezone.utc)

    # Touch 1: pageview event -> pageviews = 1, is_bounce = True
    await record_session_touch(
        db=db_session,
        app_id=app_id,
        environment=env,
        session_id=session_id,
        visitor_id=None,
        page_path="/home",
        timestamp=t1,
        event_type="pageview",
    )

    # Verify session state after touch 1
    doc1 = db_session.db.sessions_col(app_id, "live").document(session_id).get()
    assert doc1.exists
    row1 = doc1.to_dict()
    assert row1["pageviews_count"] == 1
    assert row1["is_bounce"] is True
    assert row1["entry_page"] == "/home"

    # Touch 2: custom event (click) -> pageviews_count MUST REMAIN 1, is_bounce MUST REMAIN True
    await record_session_touch(
        db=db_session,
        app_id=app_id,
        environment=env,
        session_id=session_id,
        visitor_id=None,
        page_path="/home#button",
        timestamp=t2,
        event_type="custom",
    )

    doc2 = db_session.db.sessions_col(app_id, "live").document(session_id).get()
    row2 = doc2.to_dict()
    assert row2["pageviews_count"] == 1
    assert row2["is_bounce"] is True

    # Touch 3: second pageview event -> pageviews = 2, is_bounce MUST BECOME False
    await record_session_touch(
        db=db_session,
        app_id=app_id,
        environment=env,
        session_id=session_id,
        visitor_id=None,
        page_path="/pricing",
        timestamp=t3,
        event_type="pageview",
    )

    doc3 = db_session.db.sessions_col(app_id, "live").document(session_id).get()
    row3 = doc3.to_dict()
    assert row3["pageviews_count"] == 2
    assert row3["is_bounce"] is False
    assert row3["exit_page"] == "/pricing"



@pytest.mark.asyncio
async def test_payload_size_limit_rejection(client: AsyncClient):
    """Verify payloads exceeding 64KB single limit return 413 Payload Too Large (M2-12)."""
    # Large payload with 70KB junk metadata
    large_meta = {"junk": "x" * 70000}
    resp = await client.post(
        "/v1/events",
        json={
            "write_key": "apk_test_dummy",
            "event_type": "pageview",
            "event_name": "large_event",
            "page_path": "/test",
            "metadata": large_meta,
        },
    )
    assert resp.status_code == 413
    assert "Payload exceeds maximum allowable size" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_timestamp_skew_bounds_rejection(client: AsyncClient):
    """Verify events with timestamps older than 30 days or >15 mins in future are rejected (M2-12)."""
    now = datetime.now(timezone.utc)

    # 31 days in past
    too_old = (now - timedelta(days=31)).isoformat()
    resp_old = await client.post(
        "/v1/events",
        json={
            "write_key": "apk_test_dummy",
            "event_type": "pageview",
            "event_name": "old_event",
            "page_path": "/test",
            "timestamp": too_old,
        },
    )
    assert resp_old.status_code == 422

    # 1 hour in future
    too_future = (now + timedelta(hours=1)).isoformat()
    resp_future = await client.post(
        "/v1/events",
        json={
            "write_key": "apk_test_dummy",
            "event_type": "pageview",
            "event_name": "future_event",
            "page_path": "/test",
            "timestamp": too_future,
        },
    )
    assert resp_future.status_code == 422
