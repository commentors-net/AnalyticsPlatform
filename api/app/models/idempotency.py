"""Ingestion Idempotency Registry Model."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional
from api.app.models.api_key import EnvironmentType


class IngestionIdempotency:
    def __init__(
        self,
        app_id: str = "",
        environment: EnvironmentType | str = EnvironmentType.live,
        event_id: Optional[uuid.UUID | str] = None,
        created_at: Optional[datetime | str] = None,
        **kwargs,
    ):
        self.app_id = app_id
        self.environment = EnvironmentType(environment) if isinstance(environment, str) else environment
        if isinstance(event_id, str):
            try:
                self.event_id = uuid.UUID(event_id)
            except ValueError:
                self.event_id = event_id
        else:
            self.event_id = event_id or uuid.uuid4()
        if isinstance(created_at, str):
            self.created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        else:
            self.created_at = created_at or datetime.now(timezone.utc)
