"""FastAPI Integration Example for Analytics SDK."""

from fastapi import FastAPI
from analytics.client import AsyncAnalyticsClient
from analytics.middleware.fastapi import AnalyticsMiddleware

app = FastAPI(title="Consumer Service (FastAPI)")

# Initialize Async Analytics Client
analytics_client = AsyncAnalyticsClient(
    endpoint="http://localhost:8000",
    write_key="apk_live_sample_server_key_001",
    flush_interval_sec=1.0,
)

# Attach fail-open ASGI telemetry middleware
app.add_middleware(
    AnalyticsMiddleware,
    client=analytics_client,
    exclude_paths=["/health"],
)


@app.get("/")
async def root():
    return {"message": "Hello from Consumer FastAPI Service"}


@app.get("/items/{item_id}")
async def get_item(item_id: str):
    # Custom business event
    await analytics_client.track(
        event_name="item_viewed",
        event_type="custom",
        page_path=f"/items/{item_id}",
        metadata={"item_id": item_id, "category": "electronics"},
    )
    return {"item_id": item_id, "name": "Wireless Headphones"}


@app.on_event("shutdown")
async def shutdown():
    await analytics_client.close()
