"""Health Check Schemas."""

from pydantic import BaseModel, Field


class HealthLiveResponse(BaseModel):
    status: str = Field(default="ok", example="ok")


class HealthReadyResponse(BaseModel):
    status: str = Field(default="ready", example="ready")
    database: str = Field(default="connected", example="connected")
