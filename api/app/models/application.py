"""Tenant Application Model."""

from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Optional


class AppStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    ARCHIVED = "ARCHIVED"
    DELETING = "DELETING"


class Application:
    def __init__(
        self,
        app_id: str = "",
        name: str = "",
        status: AppStatus | str = AppStatus.ACTIVE,
        allowed_origins: Optional[str] = "",
        created_at: Optional[datetime | str] = None,
        updated_at: Optional[datetime | str] = None,
        live_origins: Optional[str] = None,
        test_origins: Optional[str] = None,
        classification: str = "UNCLASSIFIED",
        **kwargs,
    ):
        self.app_id = app_id
        self.name = name
        self.status = AppStatus(status) if isinstance(status, str) else status
        self.allowed_origins = allowed_origins or ""
        self.live_origins = live_origins
        self.test_origins = test_origins
        self.classification = classification if classification in ("REAL", "SAMPLE") else "UNCLASSIFIED"
        if isinstance(created_at, str):
            self.created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        else:
            self.created_at = created_at or datetime.now(timezone.utc)
        if isinstance(updated_at, str):
            self.updated_at = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        else:
            self.updated_at = updated_at or datetime.now(timezone.utc)
