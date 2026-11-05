"""API Ingestion Keys Model (Hashed Storage)."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any, Optional


class EnvironmentType(str, enum.Enum):
    test = "test"
    live = "live"


class KeyStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class ApiKey:
    def __init__(
        self,
        id: Optional[uuid.UUID | str] = None,
        app_id: str = "",
        environment: EnvironmentType | str = EnvironmentType.live,
        key_hash: str = "",
        prefix: str = "",
        name: str = "",
        status: KeyStatus | str = KeyStatus.ACTIVE,
        created_at: Optional[datetime | str] = None,
        expires_at: Optional[datetime | str] = None,
        revoked_at: Optional[datetime | str] = None,
        application: Optional[Any] = None,
        **kwargs,
    ):
        if isinstance(id, str):
            try:
                self.id = uuid.UUID(id)
            except ValueError:
                self.id = id
        else:
            self.id = id or uuid.uuid4()
        self.app_id = app_id
        self.environment = EnvironmentType(environment) if isinstance(environment, str) else environment
        self.key_hash = key_hash
        self.prefix = prefix
        self.name = name
        self.status = KeyStatus(status) if isinstance(status, str) else status
        if isinstance(created_at, str):
            self.created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        else:
            self.created_at = created_at or datetime.now(timezone.utc)
        if isinstance(expires_at, str):
            self.expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        else:
            self.expires_at = expires_at
        if isinstance(revoked_at, str):
            self.revoked_at = datetime.fromisoformat(revoked_at.replace("Z", "+00:00"))
        else:
            self.revoked_at = revoked_at
        self.application = application
