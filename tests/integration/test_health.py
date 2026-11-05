"""Integration Tests for Health & Readiness Probes."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_live_endpoint(client: AsyncClient):
    """Verify liveness probe returns HTTP 200 and ok status."""
    response = await client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_health_ready_endpoint(client: AsyncClient):
    """Verify readiness probe returns HTTP 200 when database connection is healthy."""
    response = await client.get("/health/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["database"] == "connected"
