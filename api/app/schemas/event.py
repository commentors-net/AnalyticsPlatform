"""Telemetry Event Ingestion Schemas (M2-07, M2-12 Recursive Validation & Strict Limits)."""

import re
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator
from api.app.core.config import settings
from api.app.models.event import EventCategory

EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}")


def _validate_recursive_prohibited(data: Any, depth: int = 0) -> None:
    """Recursively inspect dictionary keys and string values for prohibited PII/chat content."""
    if depth > 5:
        raise ValueError("Metadata nesting exceeds maximum allowable depth of 5 levels.")

    if isinstance(data, dict):
        for k, v in data.items():
            if not isinstance(k, str):
                continue
            lower_k = k.lower().strip()
            if (
                lower_k in settings.PROHIBITED_METADATA_FIELDS
                or "secret" in lower_k
                or "password" in lower_k
                or "credential" in lower_k
                or lower_k.endswith("_email")
            ):
                raise ValueError(
                    f"Prohibited telemetry fields detected in metadata: '{k}'. "
                    "PII, VINs, emails, phone numbers, GPS coordinates, passwords and chat messages are strictly barred."
                )
            _validate_recursive_prohibited(v, depth + 1)
    elif isinstance(data, list):
        for item in data:
            _validate_recursive_prohibited(item, depth + 1)
    elif isinstance(data, str):
        if "@" in data and EMAIL_PATTERN.search(data):
            raise ValueError(
                "Prohibited telemetry fields detected in metadata value: plaintext email detected. "
                "PII, emails, and credentials are strictly barred."
            )


class SingleEventSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: Optional[UUID] = Field(default=None, description="Client-generated unique event ID for deduplication")
    write_key: Optional[str] = Field(default=None, description="Ingestion key in request body for beacon/CORS support")
    event_type: EventCategory = Field(default=EventCategory.pageview)
    event_name: str = Field(min_length=1, max_length=128, example="page_view")
    visitor_id: Optional[str] = Field(default=None, max_length=128, example="vid_9f2a4b8c...")
    session_id: Optional[str] = Field(default=None, max_length=128, example="ses_1a2b3c4d...")
    page_path: str = Field(min_length=1, max_length=1024, example="/dashboard/home")
    referrer: Optional[str] = Field(default=None, max_length=1024)
    duration_ms: Optional[int] = Field(default=None, ge=0)
    source: Optional[str] = Field(default=None, max_length=64, description="Reporting source e.g. python, browser, server")
    user_agent: Optional[str] = Field(default=None, max_length=512, description="Client user agent when forwarded by server")
    country_code: Optional[str] = Field(default=None, max_length=2, description="Coarse ISO-3166-1 alpha-2 country code")
    device_family: Optional[str] = Field(default=None, max_length=32, description="Reviewed device category")
    browser_family: Optional[str] = Field(default=None, max_length=32, description="Reviewed browser category")
    os_family: Optional[str] = Field(default=None, max_length=32, description="Reviewed OS category")
    client_device: Optional[str] = Field(default=None, max_length=32, description="Client device category alias")
    client_browser: Optional[str] = Field(default=None, max_length=32, description="Client browser category alias")
    referrer_category: Optional[str] = Field(default=None, max_length=64, description="Referrer category")
    client_country: Optional[str] = Field(default=None, max_length=2, description="Coarse country code alias")
    metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: Optional[datetime] = Field(default=None)

    @field_validator("country_code", "client_country")
    @classmethod
    def validate_country_code(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            code = v.strip().upper()
            if not re.fullmatch(r"[A-Z]{2}", code) or code in ("LO", "ZZ", "XX"):
                raise ValueError("Invalid ISO 3166-1 alpha-2 country code")
            return code
        return None

    @field_validator("device_family", "client_device")
    @classmethod
    def validate_device_family(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            dev = v.lower().strip()
            allowed = {"desktop", "mobile", "tablet", "bot", "unknown"}
            return dev if dev in allowed else "Other"
        return None

    @field_validator("browser_family", "client_browser")
    @classmethod
    def validate_browser_family(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            norm = {
                "chrome": "Chrome", "firefox": "Firefox", "safari": "Safari",
                "edge": "Edge", "opera": "Opera", "mobile safari": "Mobile Safari",
                "chrome mobile": "Chrome Mobile", "other": "Other", "unknown": "unknown"
            }.get(v.lower().strip(), "Other")
            return norm
        return None

    @field_validator("referrer_category")
    @classmethod
    def validate_referrer_category(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            norm = {
                "direct": "Direct / None", "search": "Search", "social": "Social",
                "internal": "Internal", "other": "Referral", "referral": "Referral",
                "direct / none": "Direct / None",
            }.get(v.lower().strip(), "Direct / None")
            return norm
        return None

    @field_validator("os_family")
    @classmethod
    def validate_os_family(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            allowed = {"Windows", "Linux", "Android", "iOS", "macOS", "Mac OS X", "Other", "unknown"}
            return v if v in allowed else "Other"
        return None

    @field_validator("source")
    @classmethod
    def validate_source(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            cleaned = v.strip().lower()[:64]
            return cleaned if cleaned else None
        return None

    @field_validator("metadata")
    @classmethod
    def validate_metadata_fields(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        """Strictly and recursively reject payloads containing prohibited privacy/PII fields."""
        _validate_recursive_prohibited(v)
        return v

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp_bounds(cls, v: Optional[datetime]) -> Optional[datetime]:
        """Enforce timestamp sanity bounds (max 30 days past, max 15 minutes future for skew)."""
        if v is not None:
            # Normalize to UTC for comparison
            ts = v if v.tzinfo else v.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            if ts < now - timedelta(days=30):
                raise ValueError("Event timestamp cannot be older than 30 days.")
            if ts > now + timedelta(minutes=15):
                raise ValueError("Event timestamp cannot be more than 15 minutes in the future.")
            return ts
        return v


class BatchEventRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    write_key: Optional[str] = Field(default=None, description="Shared write key for the batch")
    batch: List[SingleEventSchema] = Field(default_factory=list, max_length=50)
    events: Optional[List[SingleEventSchema]] = Field(default=None)

    @field_validator("batch", mode="before")
    @classmethod
    def populate_batch(cls, v: Any, info) -> Any:
        return v

    def __init__(self, **data: Any):
        if "batch" not in data and "events" in data:
            data["batch"] = data["events"]
        super().__init__(**data)


class EventIngestResponse(BaseModel):
    status: str = "success"
    event_id: UUID
    persisted_at: datetime


class BatchIngestResponse(BaseModel):
    status: str = "accepted"
    processed_count: int
    failed_count: int
    persisted_event_ids: List[UUID]
