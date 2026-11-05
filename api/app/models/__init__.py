"""SQLAlchemy Models Registry."""

from api.app.models.base import Base
from api.app.models.application import Application, AppStatus
from api.app.models.api_key import ApiKey, EnvironmentType, KeyStatus
from api.app.models.event import Event, EventCategory
from api.app.models.session import Session
from api.app.models.metric import DailyAppMetric, DailyPageMetric, DailyGeoMetric
from api.app.models.idempotency import IngestionIdempotency
from api.app.models.user import User, UserRole, UserAppPermission, AuditLog

__all__ = [
    "Base",
    "Application",
    "AppStatus",
    "ApiKey",
    "EnvironmentType",
    "KeyStatus",
    "Event",
    "EventCategory",
    "Session",
    "IngestionIdempotency",
    "DailyAppMetric",
    "DailyPageMetric",
    "DailyGeoMetric",
    "User",
    "UserRole",
    "UserAppPermission",
    "AuditLog",
]
