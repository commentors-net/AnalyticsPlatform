"""Adversarial Security Probes for Multi-Tenant Data Isolation (COND-02) in Firestore."""

import uuid
from datetime import datetime, timezone
import pytest
from api.app.services.firestore_repo import FirestoreRepo


@pytest.mark.asyncio
async def test_postgresql_row_level_security_tenant_isolation(db_session: FirestoreRepo):
    """Adversarial probe: verify that Firestore subcollection namespaces physically prevent cross-tenant data leaks."""
    now_ts = datetime.now(timezone.utc)

    # 1. Insert seed telemetry across different tenants and environments
    event_aa_live_id = str(uuid.uuid4())
    event_rl_live_id = str(uuid.uuid4())
    event_aa_test_id = str(uuid.uuid4())

    db_session.claim_and_ingest_event(
        app_id="askanna",
        environment="live",
        event_id=event_aa_live_id,
        event_data={
            "event_id": event_aa_live_id,
            "app_id": "askanna",
            "environment": "live",
            "event_type": "pageview",
            "event_name": "askanna_live_view",
            "page_path": "/chat",
            "timestamp": now_ts.isoformat(),
        },
        session_data={
            "session_id": "ses_aa_live",
            "started_at": now_ts.isoformat(),
            "pageviews_count": 1,
            "entry_page": "/chat",
        },
    )

    db_session.claim_and_ingest_event(
        app_id="roomlyst",
        environment="live",
        event_id=event_rl_live_id,
        event_data={
            "event_id": event_rl_live_id,
            "app_id": "roomlyst",
            "environment": "live",
            "event_type": "pageview",
            "event_name": "roomlyst_live_view",
            "page_path": "/rooms/design",
            "timestamp": now_ts.isoformat(),
        },
        session_data={
            "session_id": "ses_rl_live",
            "started_at": now_ts.isoformat(),
            "pageviews_count": 1,
            "entry_page": "/rooms/design",
        },
    )

    db_session.claim_and_ingest_event(
        app_id="askanna",
        environment="test",
        event_id=event_aa_test_id,
        event_data={
            "event_id": event_aa_test_id,
            "app_id": "askanna",
            "environment": "test",
            "event_type": "pageview",
            "event_name": "askanna_test_view",
            "page_path": "/staging",
            "timestamp": now_ts.isoformat(),
        },
        session_data={
            "session_id": "ses_aa_test",
            "started_at": now_ts.isoformat(),
            "pageviews_count": 1,
            "entry_page": "/staging",
        },
    )

    # 2. Probe 1: AskAnna LIVE context
    events_aa = db_session.get_live_events("askanna", "live")
    event_ids = [e["event_id"] for e in events_aa]

    # Must contain ONLY askanna live event
    assert event_aa_live_id in event_ids
    # CRITICAL: Roomlyst and test events MUST NOT appear
    assert event_rl_live_id not in event_ids
    assert event_aa_test_id not in event_ids

    # 3. Probe 2: Roomlyst LIVE context
    events_rl = db_session.get_live_events("roomlyst", "live")
    event_ids = [e["event_id"] for e in events_rl]

    assert event_rl_live_id in event_ids
    assert event_aa_live_id not in event_ids

    # 4. Probe 3: AskAnna TEST context
    events_test = db_session.get_live_events("askanna", "test")
    event_ids = [e["event_id"] for e in events_test]

    assert event_aa_test_id in event_ids
    assert event_aa_live_id not in event_ids
    assert event_rl_live_id not in event_ids

    # 5. Probe 4: Missing / Unset context
    events_empty = db_session.get_live_events("nonexistent_app", "live")
    assert len(events_empty) == 0


@pytest.mark.asyncio
async def test_sessions_table_row_level_security(db_session: FirestoreRepo):
    """Verify that sessions collection is strictly governed by subcollection tenant isolation."""
    session_aa_id = f"ses_aa_{uuid.uuid4().hex[:8]}"
    session_rl_id = f"ses_rl_{uuid.uuid4().hex[:8]}"
    now_ts = datetime.now(timezone.utc)

    db_session.touch_session(
        app_id="askanna",
        environment="live",
        session_data={
            "session_id": session_aa_id,
            "started_at": now_ts.isoformat(),
            "pageviews_count": 1,
            "entry_page": "/home",
        },
    )

    db_session.touch_session(
        app_id="roomlyst",
        environment="live",
        session_data={
            "session_id": session_rl_id,
            "started_at": now_ts.isoformat(),
            "pageviews_count": 1,
            "entry_page": "/studio",
        },
    )

    # Query under AskAnna context
    snaps_aa = db_session.db.sessions_col("askanna", "live").get()
    session_ids_aa = [s.to_dict()["session_id"] for s in snaps_aa]

    assert session_aa_id in session_ids_aa
    assert session_rl_id not in session_ids_aa

    # Query under Roomlyst context
    snaps_rl = db_session.db.sessions_col("roomlyst", "live").get()
    session_ids_rl = [s.to_dict()["session_id"] for s in snaps_rl]

    assert session_rl_id in session_ids_rl
    assert session_aa_id not in session_ids_rl

