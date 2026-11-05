"""Administrative Users, RBAC Permissions & Audit Logging Models."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


class UserRole(str, enum.Enum):
    SuperAdmin = "SuperAdmin"
    AppAdmin = "AppAdmin"
    AppViewer = "AppViewer"


class User:
    def __init__(
        self,
        id: Optional[uuid.UUID | str] = None,
        email: str = "",
        role: UserRole | str = UserRole.AppViewer,
        status: str = "ACTIVE",
        password_hash: Optional[str] = None,
        google_sub: Optional[str] = None,
        created_at: Optional[datetime | str] = None,
        last_login_at: Optional[datetime | str] = None,
        **kwargs,
    ):
        if isinstance(id, str):
            try:
                self.id = uuid.UUID(id)
            except ValueError:
                self.id = id
        else:
            self.id = id or uuid.uuid4()
        self.email = email
        self.password_hash = password_hash
        self.google_sub = google_sub
        self.role = UserRole(role) if isinstance(role, str) else role
        self.status = status
        if isinstance(created_at, str):
            self.created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        else:
            self.created_at = created_at or datetime.now(timezone.utc)
        if isinstance(last_login_at, str):
            self.last_login_at = datetime.fromisoformat(last_login_at.replace("Z", "+00:00"))
        else:
            self.last_login_at = last_login_at


class UserAppPermission:
    def __init__(
        self,
        id: Optional[uuid.UUID | str] = None,
        user_id: Optional[uuid.UUID | str] = None,
        app_id: str = "",
        granted_role: UserRole | str = UserRole.AppViewer,
        granted_at: Optional[datetime | str] = None,
        **kwargs,
    ):
        if isinstance(id, str):
            try:
                self.id = uuid.UUID(id)
            except ValueError:
                self.id = id
        else:
            self.id = id or uuid.uuid4()
        self.user_id = str(user_id) if user_id else ""
        self.app_id = app_id
        self.granted_role = UserRole(granted_role) if isinstance(granted_role, str) else granted_role
        if isinstance(granted_at, str):
            self.granted_at = datetime.fromisoformat(granted_at.replace("Z", "+00:00"))
        else:
            self.granted_at = granted_at or datetime.now(timezone.utc)


class AuditLog:
    def __init__(
        self,
        id: Optional[uuid.UUID | str] = None,
        user_id: Optional[uuid.UUID | str] = None,
        action: str = "",
        resource_type: str = "",
        resource_id: str = "",
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        timestamp: Optional[datetime | str] = None,
        **kwargs,
    ):
        if isinstance(id, str):
            try:
                self.id = uuid.UUID(id)
            except ValueError:
                self.id = id
        else:
            self.id = id or uuid.uuid4()
        self.user_id = str(user_id) if user_id else ""
        self.action = action
        self.resource_type = resource_type
        self.resource_id = resource_id
        self.details = details or {}
        self.ip_address = ip_address
        if isinstance(timestamp, str):
            self.timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        else:
            self.timestamp = timestamp or datetime.now(timezone.utc)
