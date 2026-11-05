"""Visitor Session Lifecycle & Retention Service (Firestore-backed)."""

import logging
from datetime import datetime, timezone
from typing import Any, Optional
from api.app.models.api_key import EnvironmentType
from api.app.services.firestore_repo import firestore_repo

logger = logging.getLogger(__name__)


async def record_session_touch(
    db: Any = None,
    app_id: str = "",
    environment: EnvironmentType | str = "live",
    session_id: str = "",
    visitor_id: Optional[str] = None,
    page_path: str = "/",
    timestamp: Optional[datetime] = None,
    event_type: str = "pageview",
    referrer_domain: Optional[str] = None,
    country_code: Optional[str] = None,
    device_family: Optional[str] = None,
) -> None:
    """Atomically record session touch or initialize a new session in Firestore."""
    is_pageview = 1 if (isinstance(event_type, str) and event_type.lower() == "pageview") else 0
    env_str = environment.value if hasattr(environment, "value") else str(environment)
    event_ts = timestamp or datetime.now(timezone.utc)

    session_data = {
        "session_id": session_id,
        "visitor_id": visitor_id,
        "started_at": event_ts.isoformat(),
        "pageviews_count": is_pageview,
        "entry_page": page_path,
        "referrer_domain": referrer_domain,
        "country_code": country_code,
        "device_family": device_family,
    }

    firestore_repo.touch_session(
        app_id=app_id,
        environment=env_str,
        session_data=session_data,
    )


async def cleanup_expired_sessions(
    db: Any = None,
    retention_days: int = 90,
    app_id: str = "askanna",
    environment: str = "live",
) -> int:
    """Automated retention pruning for sessions collection."""
    return firestore_repo.cleanup_expired_sessions(
        app_id=app_id,
        environment=environment,
        retention_days=retention_days,
    )
