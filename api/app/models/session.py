"""Visitor Session Model."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional
from api.app.models.api_key import EnvironmentType


class Session:
    def __init__(
        self,
        id: Optional[uuid.UUID | str] = None,
        session_id: str = "",
        app_id: str = "",
        environment: EnvironmentType | str = EnvironmentType.live,
        visitor_id: Optional[str] = None,
        started_at: Optional[datetime | str] = None,
        ended_at: Optional[datetime | str] = None,
        duration_seconds: int = 0,
        pageviews_count: int = 1,
        entry_page: str = "/",
        exit_page: Optional[str] = None,
        is_bounce: bool = True,
        referrer_domain: Optional[str] = None,
        country_code: Optional[str] = None,
        device_family: Optional[str] = None,
        **kwargs,
    ):
        if isinstance(id, str):
            try:
                self.id = uuid.UUID(id)
            except ValueError:
                self.id = id
        else:
            self.id = id or uuid.uuid4()
        self.session_id = session_id
        self.app_id = app_id
        self.environment = EnvironmentType(environment) if isinstance(environment, str) else environment
        self.visitor_id = visitor_id
        if isinstance(started_at, str):
            self.started_at = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        else:
            self.started_at = started_at or datetime.now(timezone.utc)
        if isinstance(ended_at, str):
            self.ended_at = datetime.fromisoformat(ended_at.replace("Z", "+00:00"))
        else:
            self.ended_at = ended_at or self.started_at
        self.duration_seconds = duration_seconds
        self.pageviews_count = pageviews_count
        self.entry_page = entry_page
        self.exit_page = exit_page
        self.is_bounce = is_bounce
        self.referrer_domain = referrer_domain
        self.country_code = country_code
        self.device_family = device_family
