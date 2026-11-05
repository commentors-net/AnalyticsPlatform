"""Tenant Application Schemas."""

from datetime import datetime
from urllib.parse import urlsplit
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from api.app.models.application import AppStatus


def normalize_origins(value: str | None) -> str | None:
    if value is None:
        return None
    origins = []
    for entry in value.replace("\n", ",").split(","):
        entry = entry.strip()
        if not entry:
            continue
        try:
            url = urlsplit(entry)
            port = url.port
            if port == 0:
                raise ValueError()
            if (url.scheme not in ("https", "http") or not url.hostname
                    or url.username is not None or url.password is not None
                    or url.path not in ("", "/") or url.query or url.fragment
                    or "*" in entry or any(c.isspace() for c in entry)):
                raise ValueError()
            if url.scheme == "http" and url.hostname not in ("localhost", "127.0.0.1", "::1"):
                raise ValueError()
            host = url.hostname.lower()
            if ":" in host:
                host = f"[{host}]"
            suffix = f":{port}" if port and port != (443 if url.scheme == "https" else 80) else ""
            origin = f"{url.scheme}://{host}{suffix}"
        except ValueError:
            raise ValueError("Use HTTPS website origins without paths, credentials, queries or wildcards; HTTP is allowed only for localhost.")
        if origin not in origins:
            origins.append(origin)
    if len(origins) > 50:
        raise ValueError("At most 50 origins are allowed per field")
    return ",".join(origins)


class ApplicationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    app_id: str = Field(min_length=3, max_length=64, pattern="^[a-z0-9_-]+$", example="askanna")
    name: str = Field(min_length=1, max_length=255)
    allowed_origins: str = Field(default="", max_length=8192)
    live_origins: str | None = Field(default=None, max_length=8192)
    test_origins: str | None = Field(default=None, max_length=8192)
    classification: Literal["REAL", "SAMPLE", "UNCLASSIFIED"] = "UNCLASSIFIED"

    _origins = field_validator("allowed_origins", "live_origins", "test_origins")(normalize_origins)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        if value is None:
            return None
        if not value.strip():
            raise ValueError("Application name is required")
        return value.strip()


class ApplicationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=255)
    status: AppStatus | None = None
    allowed_origins: str | None = Field(default=None, max_length=8192)
    live_origins: str | None = Field(default=None, max_length=8192)
    test_origins: str | None = Field(default=None, max_length=8192)
    classification: Literal["REAL", "SAMPLE", "UNCLASSIFIED"] | None = None

    _origins = field_validator("allowed_origins", "live_origins", "test_origins")(normalize_origins)
    _name = field_validator("name")(ApplicationCreate.clean_name)

    @model_validator(mode="after")
    def nonempty_update(self):
        if self.status == AppStatus.DELETING:
            raise ValueError("Use the confirmed deletion workflow")
        if not self.model_fields_set or any(getattr(self, key) is None for key in self.model_fields_set):
            raise ValueError("Provide at least one non-null field to update")
        return self


class ApplicationResponse(BaseModel):
    app_id: str
    name: str
    status: AppStatus
    allowed_origins: str
    live_origins: str | None = None
    test_origins: str | None = None
    can_manage: bool = False
    can_delete: bool = False
    classification: Literal["REAL", "SAMPLE", "UNCLASSIFIED"] = "UNCLASSIFIED"
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ApplicationDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmation: str = Field(min_length=3, max_length=64)
    preview_token: str = Field(min_length=1, max_length=4096)
