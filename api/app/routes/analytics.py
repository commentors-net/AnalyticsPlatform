"""Analytics Dashboard & Reporting API Routes (Firestore-backed).

Provides tenant-scoped, environment-isolated telemetry reporting, aggregations,
time-series analytics, real-time event inspection, and audit-logged export.
Strictly enforces Firestore namespace isolation and Platform RBAC.
"""

import csv
import io
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.app.core.dependencies import get_current_user, verify_app_access
from api.app.models.api_key import EnvironmentType
from api.app.models.user import User, UserRole
from api.app.services.firestore_repo import FirestoreRepo, get_repo
from api.app.services.dashboard_safety import safe_event_name, safe_path, safe_metadata, geography, safe_event_id, safe_timestamp, family

router = APIRouter(prefix="/api/v1/analytics", tags=["Analytics Dashboard"])


# --- Schemas ---

class MetricDelta(BaseModel):
    value: float
    previous_value: float
    change_pct: float


class OverviewMetricsResponse(BaseModel):
    app_id: str
    environment: str
    start_date: str
    end_date: str
    pageviews: MetricDelta
    visitors: MetricDelta
    sessions: MetricDelta
    bounce_rate: MetricDelta
    avg_duration_sec: MetricDelta


class TimeseriesPoint(BaseModel):
    timestamp: str
    pageviews: int
    sessions: int
    visitors: int


class PageMetricItem(BaseModel):
    page_path: str
    views_count: int
    visitors_count: int
    bounce_rate: float
    avg_duration_sec: float


class ReferrerItem(BaseModel):
    referrer_domain: str
    views_count: int
    visitors_count: int


class BreakdownItem(BaseModel):
    name: str
    count: int
    percentage: float


class DeviceBreakdownResponse(BaseModel):
    devices: List[BreakdownItem]
    os: List[BreakdownItem]
    browsers: List[BreakdownItem]


class GeoMetricItem(BaseModel):
    country_code: str
    city_name: Optional[str]
    visitors_count: int
    pageviews_count: int


class RecentEventItem(BaseModel):
    event_id: str
    timestamp: str
    event_type: str
    event_name: str
    page_path: str
    referrer_domain: Optional[str]
    device_family: Optional[str]
    browser_family: Optional[str]
    os_family: Optional[str]
    country_code: Optional[str]
    duration_ms: Optional[int]
    source: str = "Not reported"
    metadata: Dict[str, Any] = Field(default_factory=dict)


# --- Endpoints ---

@router.get("/overview", response_model=OverviewMetricsResponse)
async def get_overview_metrics(
    app_id: str = Query(..., description="Application identifier"),
    environment: EnvironmentType = Query(EnvironmentType.live, description="Environment (live or test)"),
    start_date: Optional[datetime] = Query(None, description="Start date (UTC)"),
    end_date: Optional[datetime] = Query(None, description="End date (UTC)"),
    current_user: User = Depends(get_current_user),
    repo: FirestoreRepo = Depends(get_repo),
) -> OverviewMetricsResponse:
    """Retrieve top-level KPI metrics with previous period comparison."""
    await verify_app_access(app_id, current_user, repo)

    now = datetime.now(timezone.utc)
    end = end_date or now
    start = start_date or (end - timedelta(days=30))
    env_val = environment.value if hasattr(environment, "value") else str(environment)

    data = repo.get_overview_metrics(app_id, env_val, start, end)
    return OverviewMetricsResponse.model_validate(data)


@router.get("/timeseries", response_model=List[TimeseriesPoint])
async def get_timeseries_metrics(
    app_id: str = Query(..., description="Application identifier"),
    environment: EnvironmentType = Query(EnvironmentType.live, description="Environment (live or test)"),
    interval: str = Query("day", pattern="^(day|hour)$", description="Bucket interval (day or hour)"),
    start_date: Optional[datetime] = Query(None, description="Start date (UTC)"),
    end_date: Optional[datetime] = Query(None, description="End date (UTC)"),
    current_user: User = Depends(get_current_user),
    repo: FirestoreRepo = Depends(get_repo),
) -> List[TimeseriesPoint]:
    """Retrieve time-series trends bucketed by day or hour."""
    await verify_app_access(app_id, current_user, repo)

    now = datetime.now(timezone.utc)
    end = end_date or now
    start = start_date or (end - timedelta(days=30))
    env_val = environment.value if hasattr(environment, "value") else str(environment)

    items = repo.get_timeseries_metrics(app_id, env_val, interval, start, end)
    return [TimeseriesPoint.model_validate(i) for i in items]


@router.get("/pages", response_model=List[PageMetricItem])
async def get_top_pages(
    app_id: str = Query(..., description="Application identifier"),
    environment: EnvironmentType = Query(EnvironmentType.live, description="Environment (live or test)"),
    limit: int = Query(20, ge=1, le=100),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    current_user: User = Depends(get_current_user),
    repo: FirestoreRepo = Depends(get_repo),
) -> List[PageMetricItem]:
    """Retrieve top performing pages with view counts, visitors, and bounce rates."""
    await verify_app_access(app_id, current_user, repo)

    now = datetime.now(timezone.utc)
    end = end_date or now
    start = start_date or (end - timedelta(days=30))
    env_val = environment.value if hasattr(environment, "value") else str(environment)

    items = repo.get_top_pages(app_id, env_val, start, end, limit=limit)
    return [PageMetricItem.model_validate(i) for i in items]


@router.get("/referrers", response_model=List[ReferrerItem])
async def get_top_referrers(
    app_id: str = Query(..., description="Application identifier"),
    environment: EnvironmentType = Query(EnvironmentType.live),
    limit: int = Query(20, ge=1, le=100),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    current_user: User = Depends(get_current_user),
    repo: FirestoreRepo = Depends(get_repo),
) -> List[ReferrerItem]:
    """Retrieve top referrer domains driving traffic."""
    await verify_app_access(app_id, current_user, repo)

    now = datetime.now(timezone.utc)
    end = end_date or now
    start = start_date or (end - timedelta(days=30))
    env_val = environment.value if hasattr(environment, "value") else str(environment)

    items = repo.get_top_referrers(app_id, env_val, start, end, limit=limit)
    return [ReferrerItem.model_validate(i) for i in items]


@router.get("/devices", response_model=DeviceBreakdownResponse)
async def get_device_breakdown(
    app_id: str = Query(..., description="Application identifier"),
    environment: EnvironmentType = Query(EnvironmentType.live),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    current_user: User = Depends(get_current_user),
    repo: FirestoreRepo = Depends(get_repo),
) -> DeviceBreakdownResponse:
    """Retrieve device, OS, and browser category distributions."""
    await verify_app_access(app_id, current_user, repo)

    now = datetime.now(timezone.utc)
    end = end_date or now
    start = start_date or (end - timedelta(days=30))
    env_val = environment.value if hasattr(environment, "value") else str(environment)

    data = repo.get_device_breakdown(app_id, env_val, start, end)
    return DeviceBreakdownResponse.model_validate(data)


@router.get("/geo", response_model=List[GeoMetricItem])
async def get_geo_metrics(
    app_id: str = Query(..., description="Application identifier"),
    environment: EnvironmentType = Query(EnvironmentType.live),
    limit: int = Query(20, ge=1, le=100),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    current_user: User = Depends(get_current_user),
    repo: FirestoreRepo = Depends(get_repo),
) -> List[GeoMetricItem]:
    """Retrieve geographic breakdown by country and coarse city."""
    await verify_app_access(app_id, current_user, repo)

    now = datetime.now(timezone.utc)
    end = end_date or now
    start = start_date or (end - timedelta(days=30))
    env_val = environment.value if hasattr(environment, "value") else str(environment)

    items = repo.get_geo_breakdown(app_id, env_val, start, end, limit=limit)
    return [GeoMetricItem.model_validate(i) for i in items]


@router.get("/recent", response_model=List[RecentEventItem])
async def get_recent_events(
    app_id: str = Query(..., description="Application identifier"),
    environment: EnvironmentType = Query(EnvironmentType.live),
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    repo: FirestoreRepo = Depends(get_repo),
) -> List[RecentEventItem]:
    """Inspect real-time recent events (up to 100 items)."""
    await verify_app_access(app_id, current_user, repo)
    env_val = environment.value if hasattr(environment, "value") else str(environment)

    raw_events = repo.get_live_events(app_id, env_val, limit=limit)
    return [
        RecentEventItem(
            event_id=safe_event_id(r.get("event_id")),
            timestamp=safe_timestamp(r.get("timestamp")),
            event_type=r.get("event_type") if r.get("event_type") in ("pageview", "custom", "click", "timing") else "Unknown",
            event_name=safe_event_name(r.get("event_name")),
            page_path=safe_path(r.get("page_path")),
            referrer_domain=None,
            device_family=family(r.get("device_family"), "device"),
            browser_family=family(r.get("browser_family"), "browser"),
            os_family=family(r.get("os_family"), "os"),
            country_code=geography(r)[0],
            duration_ms=r.get("duration_ms") if type(r.get("duration_ms")) is int and 0 <= r["duration_ms"] <= 86400000 else None,
            metadata=safe_metadata(r.get("metadata")),
            source=safe_metadata(r.get("metadata")).get("source", "Not reported"),
        )
        for r in raw_events
    ]


@router.post("/export")
async def export_analytics_data(
    app_id: str = Query(...),
    environment: EnvironmentType = Query(EnvironmentType.live),
    export_format: str = Query("csv", pattern="^(csv|json)$"),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    current_user: User = Depends(get_current_user),
    repo: FirestoreRepo = Depends(get_repo),
) -> StreamingResponse:
    """Export telemetry records with mandatory immutable audit logging."""
    await verify_app_access(app_id, current_user, repo)

    now = datetime.now(timezone.utc)
    end = end_date or now
    start = start_date or (end - timedelta(days=30))
    env_val = environment.value if hasattr(environment, "value") else str(environment)

    records = repo.get_events_for_export(app_id, env_val, start, end)

    # Immutable Audit Log Record
    repo.log_audit(
        user_id=str(current_user.id),
        action="EXPORT_ANALYTICS",
        resource_type="application",
        resource_id=app_id,
        details={
            "format": export_format,
            "record_count": len(records),
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "environment": env_val,
        },
    )

    # Generate Export Stream
    if export_format == "json":
        formatted_data = [
            {
                **r,
                "event_id": str(r.get("event_id")),
                "timestamp": r.get("timestamp") or "",
            }
            for r in records
        ]
        content = json.dumps(formatted_data, indent=2)
        media_type = "application/json"
        filename = f"analytics-{app_id}-{env_val}-{start.strftime('%Y%m%d')}-{end.strftime('%Y%m%d')}.json"
        return StreamingResponse(
            io.StringIO(content),
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    else:
        output = io.StringIO()
        fieldnames = [
            "event_id", "timestamp", "event_type", "event_name", "page_path",
            "referrer_domain", "device_family", "browser_family", "os_family",
            "country_code", "duration_ms",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for r in records:
            writer.writerow({
                **r,
                "event_id": str(r.get("event_id")),
                "timestamp": r.get("timestamp") or "",
            })
        output.seek(0)
        filename = f"analytics-{app_id}-{env_val}-{start.strftime('%Y%m%d')}-{end.strftime('%Y%m%d')}.csv"
        return StreamingResponse(
            output,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
