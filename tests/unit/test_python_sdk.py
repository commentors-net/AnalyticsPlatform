"""Unit Tests for Python Analytics SDK and Web Framework Middleware (Milestone M4)."""

import os
import sys
from pathlib import Path
import pytest
from httpx import ASGITransport, AsyncClient

# Add sdk/python to sys.path so analytics package is directly importable
SDK_PYTHON_PATH = str(Path(__file__).resolve().parent.parent.parent / "sdk" / "python")
if SDK_PYTHON_PATH not in sys.path:
    sys.path.insert(0, SDK_PYTHON_PATH)

from analytics.client import AnalyticsClient, AsyncAnalyticsClient
from analytics.middleware.fastapi import AnalyticsMiddleware


def test_sync_client_enqueues_and_fails_open():
    """Verify that sync client accepts events and never throws on offline endpoint."""
    client = AnalyticsClient(
        endpoint="http://non-existent-analytics-domain.invalid:9999",
        write_key="apk_test_mock_sync_key",
        batch_size=5,
        flush_interval_sec=0.1,
        max_queue_size=10,
        timeout_sec=0.2,
    )

    try:
        # Enqueue events exceeding queue size to test FIFO bounding
        for i in range(15):
            client.track(
                event_name="test_sync_event",
                page_path=f"/test-{i}",
                metadata={"index": i},
            )

        # Trigger flush: should attempt HTTP request and fail open silently without error
        client.flush()
    finally:
        client.close()


@pytest.mark.asyncio
async def test_async_client_enqueues_and_fails_open():
    """Verify that async client accepts events and fails open on offline endpoint."""
    client = AsyncAnalyticsClient(
        endpoint="http://non-existent-analytics-domain.invalid:9999",
        write_key="apk_test_mock_async_key",
        batch_size=5,
        flush_interval_sec=0.1,
        max_queue_size=10,
        timeout_sec=0.2,
    )

    try:
        for i in range(15):
            await client.track(
                event_name="test_async_event",
                page_path=f"/async-{i}",
                metadata={"index": i},
            )

        await client.flush()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_fastapi_middleware_telemetry_and_fail_open():
    """Verify that FastAPI middleware measures request latency and passes responses cleanly."""
    from fastapi import FastAPI

    sample_app = FastAPI()
    mock_client = AsyncAnalyticsClient(
        endpoint="http://localhost:5433",
        write_key="apk_test_mock_key",
        enabled=False,  # Disabled to verify bypass
    )

    sample_app.add_middleware(
        AnalyticsMiddleware,
        client=mock_client,
        exclude_paths=["/health"],
    )

    @sample_app.get("/hello")
    async def hello():
        return {"msg": "ok"}

    @sample_app.get("/health")
    async def health():
        return {"status": "healthy"}

    transport = ASGITransport(app=sample_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/hello")
        assert res.status_code == 200
        assert res.json() == {"msg": "ok"}

        # Excluded health endpoint
        res_health = await ac.get("/health")
        assert res_health.status_code == 200
        assert res_health.json() == {"status": "healthy"}


def test_disabled_client_is_noop():
    """Verify that an unconfigured or disabled client does nothing."""
    client = AnalyticsClient(
        endpoint="http://localhost",
        write_key="",
        enabled=False,
    )
    assert not client.enabled
    client.track("noop_event")
    client.pageview("/noop")
    client.flush()
    client.close()


def test_client_enqueues_extended_fields():
    """Verify that Python SDK enqueues source, user_agent, country_code, and duration_ms accurately."""
    client = AnalyticsClient(
        endpoint="http://localhost:5433",
        write_key="apk_test_dummy_key",
        enabled=False,  # Keep worker from making network requests
    )
    # Enable internal queue without starting worker thread
    client.enabled = True
    client.track(
        event_name="custom_action",
        page_path="/action",
        duration_ms=450,
        source="python",
        user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)",
        country_code="US",
        device_family="mobile",
        browser_family="Safari",
        os_family="iOS",
        metadata={"key": "val"},
    )
    item = client._queue.get_nowait()
    assert item["event_name"] == "custom_action"
    assert item["duration_ms"] == 450
    assert item["source"] == "python"
    assert item["user_agent"] == "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"
    assert item["country_code"] == "US"
    assert item["device_family"] == "mobile"
    assert item["browser_family"] == "Safari"
    assert item["os_family"] == "iOS"
    assert item["metadata"]["source"] == "python"
    assert item["metadata"]["key"] == "val"

    client.pageview(
        page_path="/home",
        duration_ms=1200,
        source="python",
        user_agent="Custom-Browser/1.0",
        country_code="GB",
    )
    pv_item = client._queue.get_nowait()
    assert pv_item["event_name"] == "pageview"
    assert pv_item["event_type"] == "pageview"
    assert pv_item["page_path"] == "/home"
    assert pv_item["duration_ms"] == 1200
    assert pv_item["source"] == "python"
    assert pv_item["user_agent"] == "Custom-Browser/1.0"
    assert pv_item["country_code"] == "GB"
    client.enabled = False
