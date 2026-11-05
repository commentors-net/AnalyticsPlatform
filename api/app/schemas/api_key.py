"""API Key Schemas."""

from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field
from api.app.models.api_key import EnvironmentType, KeyStatus


class ApiKeyCreate(BaseModel):
    environment: EnvironmentType
    name: str = Field(min_length=1, max_length=255, example="Production Web SDK Key")
    expires_at: Optional[datetime] = None


class ApiKeyResponse(BaseModel):
    id: UUID
    app_id: str
    environment: EnvironmentType
    prefix: str
    name: str
    status: KeyStatus
    created_at: datetime
    expires_at: Optional[datetime] = None
    raw_key: Optional[str] = Field(default=None, description="Returned only once upon creation")

    class Config:
        from_attributes = True


class ApiKeyListItem(BaseModel):
    id: UUID
    app_id: str
    environment: EnvironmentType
    prefix: str
    name: str
    status: KeyStatus
    created_at: datetime
    expires_at: Optional[datetime] = None

    class Config:
        from_attributes = True
