"""Telemetry Event Model."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from api.app.models.api_key import EnvironmentType


class EventCategory(str, enum.Enum):
    pageview = "pageview"
    custom = "custom"
    click = "click"
    timing = "timing"


class Event:
    def __init__(
        self,
        event_id: Optional[uuid.UUID | str] = None,
        app_id: str = "",
        environment: EnvironmentType | str = EnvironmentType.live,
        event_type: EventCategory | str = EventCategory.pageview,
        event_name: str = "pageview",
        visitor_id: Optional[str] = None,
        session_id: Optional[str] = None,
        page_path: str = "/",
        referrer_domain: Optional[str] = None,
        device_family: Optional[str] = None,
        os_family: Optional[str] = None,
        browser_family: Optional[str] = None,
        country_code: Optional[str] = None,
        region_code: Optional[str] = None,
        city_name: Optional[str] = None,
        ip_masked: Optional[str] = None,
        duration_ms: Optional[int] = None,
        metadata_json: Optional[Dict[str, Any]] = None,
        timestamp: Optional[datetime | str] = None,
        **kwargs,
    ):
        if isinstance(event_id, str):
            try:
                self.event_id = uuid.UUID(event_id)
            except ValueError:
                self.event_id = event_id
        else:
            self.event_id = event_id or uuid.uuid4()
        self.app_id = app_id
        self.environment = EnvironmentType(environment) if isinstance(environment, str) else environment
        self.event_type = EventCategory(event_type) if isinstance(event_type, str) else event_type
        self.event_name = event_name
        self.visitor_id = visitor_id
        self.session_id = session_id
        self.page_path = page_path
        self.referrer_domain = referrer_domain
        self.device_family = device_family
        self.os_family = os_family
        self.browser_family = browser_family
        self.country_code = country_code
        self.region_code = region_code
        self.city_name = city_name
        self.ip_masked = ip_masked
        self.duration_ms = duration_ms
        self.metadata_json = metadata_json or kwargs.get("metadata") or {}
        if isinstance(timestamp, str):
            self.timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        else:
            self.timestamp = timestamp or datetime.now(timezone.utc)
