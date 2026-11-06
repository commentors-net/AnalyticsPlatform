"""Public Telemetry Event Ingestion Routes (Firestore-backed)."""

import json
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Tuple
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status

from api.app.core.config import settings
from api.app.core.dependencies import validate_ingestion_key, validate_origin_allowed
from api.app.core.rate_limit import rate_limiter
from api.app.schemas.event import (
    BatchEventRequest,
    BatchIngestResponse,
    EventIngestResponse,
    SingleEventSchema,
)
from api.app.services.bot_detector import classify_user_agent
from api.app.services.geoip import mask_ip_address, resolve_coarse_geoip
from api.app.services.proxy import extract_client_ip
from api.app.services.sanitizer import classify_referrer, extract_referrer_domain, sanitize_url_path
from api.app.services.firestore_repo import FirestoreRepo, get_repo
import re

router = APIRouter(tags=["Ingestion"])


def _persist_event(repo, **kwargs):
    try:
        return repo.claim_and_ingest_event(**kwargs)
    except ValueError:
        raise HTTPException(status_code=409, detail="Application changed or deletion started; event was not accepted")


BROWSER_NORMALIZATION = {
    "chrome": "Chrome",
    "firefox": "Firefox",
    "safari": "Safari",
    "edge": "Edge",
    "opera": "Opera",
    "mobile safari": "Mobile Safari",
    "chrome mobile": "Chrome Mobile",
    "other": "Other",
    "unknown": "unknown",
}

REFERRER_CAT_MAP = {
    "direct": "Direct / None",
    "search": "Search",
    "social": "Social",
    "internal": "Internal",
    "other": "Referral",
    "referral": "Referral",
    "direct / none": "Direct / None",
}


def _resolve_device_family(item: SingleEventSchema, default_device: Optional[str]) -> Optional[str]:
    raw_device = (
        item.device_family
        or getattr(item, "client_device", None)
        or (item.metadata.get("client_device") if isinstance(item.metadata, dict) else None)
        or (item.metadata.get("device_family") if isinstance(item.metadata, dict) else None)
    )
    if raw_device:
        dev_str = str(raw_device).lower().strip()
        allowed = {"desktop", "mobile", "tablet", "bot", "unknown"}
        return dev_str if dev_str in allowed else "Other"
    return default_device


def _resolve_browser_family(item: SingleEventSchema, default_browser: Optional[str]) -> Optional[str]:
    raw_browser = (
        item.browser_family
        or getattr(item, "client_browser", None)
        or (item.metadata.get("client_browser") if isinstance(item.metadata, dict) else None)
        or (item.metadata.get("browser_family") if isinstance(item.metadata, dict) else None)
    )
    if raw_browser:
        norm = BROWSER_NORMALIZATION.get(str(raw_browser).lower().strip())
        if norm:
            return norm
    return default_browser


def _resolve_referrer_category(item: SingleEventSchema, ref_domain: Optional[str], allowed_origins: Optional[str]) -> str:
    ref_cat = classify_referrer(ref_domain, allowed_origins)
    raw_cat = (
        getattr(item, "referrer_category", None)
        or (item.metadata.get("referrer_category") if isinstance(item.metadata, dict) else None)
    )
    if raw_cat:
        cat_clean = str(raw_cat).lower().strip()
        if cat_clean in REFERRER_CAT_MAP:
            return REFERRER_CAT_MAP[cat_clean]
    return ref_cat


def _resolve_geography(
    item: SingleEventSchema,
    client_ip: Optional[str],
    request: Request,
    is_browser_call: bool,
) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    country_code = None
    geo_source = None
    region_code = None
    city_name = None

    # Untrusted browser calls (CORS with Origin, or browser source) cannot claim verified geography
    if not is_browser_call:
        raw_country = (
            item.country_code
            or getattr(item, "client_country", None)
            or (item.metadata.get("client_country") if isinstance(item.metadata, dict) else None)
            or (item.metadata.get("country_code") if isinstance(item.metadata, dict) else None)
        )
        if raw_country:
            candidate = str(raw_country).strip().upper()
            if re.fullmatch(r"[A-Z]{2}", candidate) and candidate not in ("LO", "ZZ", "XX"):
                country_code = candidate
                geo_source = "trusted_edge_or_client"

        if not country_code:
            # Genuine edge proxy headers (cf-ipcountry from Cloudflare, x-appengine-country from GCP)
            for header_name in ("cf-ipcountry", "x-appengine-country"):
                hdr_val = request.headers.get(header_name)
                if hdr_val:
                    candidate = hdr_val.strip().upper()
                    if re.fullmatch(r"[A-Z]{2}", candidate) and candidate not in ("LO", "ZZ", "XX"):
                        country_code = candidate
                        geo_source = "trusted_edge_or_client"
                        break

    if not country_code:
        country_code, region_code, city_name = resolve_coarse_geoip(client_ip)
        if country_code:
            geo_source = "verified_coarse_lookup"
    else:
        region_code, city_name = None, None

    return country_code, region_code, city_name, geo_source


@router.options("/v1/{path:path}")
async def cors_preflight(path: str, request: Request) -> Response:
    """Handle CORS preflight requests with aggressive caching and origin reflection (M2-08)."""
    origin = request.headers.get("origin") or "*"
    headers = {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, X-Write-Key, Authorization",
        "Access-Control-Max-Age": "86400",
    }
    if origin != "*":
        headers["Access-Control-Allow-Credentials"] = "true"

    return Response(status_code=status.HTTP_204_NO_CONTENT, headers=headers)


async def _read_bounded_body(request: Request, max_bytes: int) -> bytes:
    """Stream request body, immediately aborting with 413 if max_bytes is exceeded (M2-12)."""
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > max_bytes:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"Payload exceeds maximum allowable size of {max_bytes} bytes",
                )
        except ValueError:
            pass

    chunks: List[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Payload exceeds maximum allowable size of {max_bytes} bytes",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _extract_write_key(request: Request, x_write_key: Optional[str], body_key: Optional[str]) -> Optional[str]:
    """Extract write key from X-Write-Key header, Authorization Bearer, or request body."""
    if x_write_key and x_write_key.strip():
        return x_write_key.strip()
    auth_header = request.headers.get("authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
        if token.startswith("apk_"):
            return token
    if body_key and body_key.strip():
        return body_key.strip()
    return None


async def _parse_single_event_body(request: Request) -> SingleEventSchema:
    """Read and validate request body enforcing 64KB limit and text/plain beacon compatibility (M2-08, M2-12)."""
    body = await _read_bounded_body(request, settings.MAX_PAYLOAD_SIZE_BYTES)
    try:
        data = json.loads(body.decode("utf-8")) if body else {}
        return SingleEventSchema.model_validate(data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))


async def _parse_batch_event_body(request: Request) -> BatchEventRequest:
    """Read and validate batch body enforcing 512KB limit and text/plain beacon compatibility (M2-08, M2-12)."""
    body = await _read_bounded_body(request, settings.MAX_BATCH_SIZE_BYTES)
    try:
        data = json.loads(body.decode("utf-8")) if body else {}
        return BatchEventRequest.model_validate(data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))


@router.post(
    "/v1/events",
    response_model=EventIngestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest Single Telemetry Event",
)
async def ingest_event(
    request: Request,
    response: Response,
    x_write_key: Optional[str] = Header(default=None, alias="X-Write-Key"),
    repo: FirestoreRepo = Depends(get_repo),
) -> EventIngestResponse:
    """Ingest a single telemetry event with Firestore durability."""
    payload = await _parse_single_event_body(request)

    raw_key = _extract_write_key(request, x_write_key, payload.write_key)
    if not raw_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing write_key in X-Write-Key header or request body",
        )

    # 1. Pre-check IP rate limit before DB lookup
    client_ip = extract_client_ip(request)
    masked_ip = mask_ip_address(client_ip)
    rate_limiter.check_rate_limit(write_key="", client_ip=masked_ip or "", cost=1)

    # 2. Validate Write Key
    api_key = await validate_ingestion_key(raw_key, repo)
    app_id = api_key.app_id
    environment = api_key.environment.value if hasattr(api_key.environment, "value") else str(api_key.environment)

    # 3. Check key rate limit
    rate_limiter.check_rate_limit(write_key=raw_key, client_ip="", cost=1)

    # 4. Origin & Abuse Check
    origin = request.headers.get("origin")
    if not validate_origin_allowed(api_key.application.allowed_origins, origin, exact=getattr(api_key.application, "strict_origins", False)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Request origin not authorized for this application",
        )

    # 5. User-Agent / Bot Classification
    forwarded_ua = payload.user_agent or (payload.metadata.get("user_agent") if isinstance(payload.metadata, dict) else None)
    effective_ua = forwarded_ua or request.headers.get("user-agent")
    is_bot, bot_name, browser_family, os_family, device_family = classify_user_agent(effective_ua)

    is_browser_call = bool(origin) or (getattr(payload, "source", None) == "browser") or (isinstance(payload.metadata, dict) and payload.metadata.get("source") == "browser")
    device_family = _resolve_device_family(payload, device_family)
    browser_family = _resolve_browser_family(payload, browser_family)
    if payload.os_family:
        os_family = payload.os_family

    country_code, region_code, city_name, geo_source = _resolve_geography(
        payload, client_ip, request, is_browser_call
    )

    clean_path = sanitize_url_path(payload.page_path)
    ref_domain = extract_referrer_domain(payload.referrer)
    ref_cat = _resolve_referrer_category(payload, ref_domain, getattr(api_key.application, "allowed_origins", None))

    event_timestamp = payload.timestamp or datetime.now(timezone.utc)
    event_id = payload.event_id or uuid.uuid4()
    event_id_str = str(event_id)

    # 7. Source Mapping
    source = payload.source or (payload.metadata.get("source") if isinstance(payload.metadata, dict) else None)
    if not source:
        raw_ua = (request.headers.get("user-agent") or "").lower()
        if "python" in raw_ua or "httpx" in raw_ua or "aiohttp" in raw_ua or (isinstance(payload.metadata, dict) and "method" in payload.metadata):
            source = "python"
        elif request.headers.get("origin") or (effective_ua and ("mozilla" in effective_ua.lower() or "chrome" in effective_ua.lower())):
            source = "browser"
        else:
            source = "server"

    metadata = dict(payload.metadata) if payload.metadata else {}
    metadata["source"] = source
    if is_bot:
        metadata["is_bot"] = True
        metadata["bot_name"] = bot_name

    event_data = {
        "event_id": event_id_str,
        "app_id": app_id,
        "environment": environment,
        "event_type": payload.event_type.value if hasattr(payload.event_type, "value") else str(payload.event_type),
        "event_name": payload.event_name,
        "visitor_id": payload.visitor_id,
        "session_id": payload.session_id,
        "page_path": clean_path,
        "referrer_domain": ref_domain,
        "referrer_category": ref_cat,
        "source": source,
        "device_family": device_family,
        "os_family": os_family,
        "browser_family": browser_family,
        "country_code": country_code,
        "region_code": region_code,
        "city_name": city_name,
        "geo_source": geo_source,
        "ip_masked": masked_ip,
        "duration_ms": payload.duration_ms,
        "consent_status": getattr(payload, "consent_status", "ANALYTICS_ALLOWED" if payload.visitor_id else "NO_STORAGE"),
        "metadata": metadata,
        "timestamp": event_timestamp.isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    is_pv = 1 if str(event_data["event_type"]).lower() == "pageview" else 0
    duration_sec = max(0, (payload.duration_ms or 0) // 1000)
    session_data = {
        "session_id": payload.session_id or f"sess_{uuid.uuid4().hex[:12]}",
        "visitor_id": payload.visitor_id,
        "started_at": event_timestamp.isoformat(),
        "pageviews_count": is_pv,
        "duration_seconds": duration_sec,
        "event_type": event_data["event_type"],
        "entry_page": clean_path,
        "referrer_domain": ref_domain,
        "referrer_category": ref_cat,
        "country_code": country_code,
        "geo_source": geo_source,
        "device_family": device_family,
    }

    is_new = _persist_event(repo,
        app_id=app_id,
        environment=environment,
        event_id=event_id_str,
        event_data=event_data,
        session_data=session_data,
    )

    if not is_new:
        # Idempotent response for duplicate/retried event
        response.status_code = status.HTTP_200_OK

    return EventIngestResponse(
        status="success",
        event_id=event_id,
        persisted_at=datetime.now(timezone.utc),
    )


@router.post(
    "/v1/batch",
    response_model=BatchIngestResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ingest Batch of Telemetry Events",
)
@router.post(
    "/v1/events/batch",
    response_model=BatchIngestResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ingest Batch of Telemetry Events (Alias)",
)
async def ingest_batch(
    request: Request,
    x_write_key: Optional[str] = Header(default=None, alias="X-Write-Key"),
    repo: FirestoreRepo = Depends(get_repo),
) -> BatchIngestResponse:
    """Ingest a batch of events within Firestore."""
    payload = await _parse_batch_event_body(request)

    first_item_key = payload.batch[0].write_key if payload.batch else None
    raw_key = _extract_write_key(request, x_write_key, payload.write_key or first_item_key)
    if not raw_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing write_key for batch ingestion",
        )

    # 1. Pre-check IP rate limit before DB lookup
    client_ip = extract_client_ip(request)
    masked_ip = mask_ip_address(client_ip)
    batch_cost = len(payload.batch)
    rate_limiter.check_rate_limit(write_key="", client_ip=masked_ip or "", cost=batch_cost)

    # 2. Validate Write Key
    api_key = await validate_ingestion_key(raw_key, repo)
    app_id = api_key.app_id
    environment = api_key.environment.value if hasattr(api_key.environment, "value") else str(api_key.environment)

    # 3. Check key rate limit
    rate_limiter.check_rate_limit(write_key=raw_key, client_ip="", cost=batch_cost)

    # 4. Origin & Abuse Check
    origin = request.headers.get("origin")
    if not validate_origin_allowed(api_key.application.allowed_origins, origin, exact=getattr(api_key.application, "strict_origins", False)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Request origin not authorized for this application",
        )

    # 5. User-Agent / Bot Classification fallback
    req_ua = request.headers.get("user-agent")
    is_browser_call = bool(origin)

    persisted_ids: List[uuid.UUID] = []

    for item in payload.batch:
        event_id = item.event_id or uuid.uuid4()
        event_id_str = str(event_id)
        clean_path = sanitize_url_path(item.page_path)
        ref_domain = extract_referrer_domain(item.referrer)
        ref_cat = _resolve_referrer_category(item, ref_domain, getattr(api_key.application, "allowed_origins", None))
        event_timestamp = item.timestamp or datetime.now(timezone.utc)

        # User agent resolution
        forwarded_ua = item.user_agent or (item.metadata.get("user_agent") if isinstance(item.metadata, dict) else None)
        effective_ua = forwarded_ua or req_ua
        is_bot, bot_name, browser_family, os_family, device_family = classify_user_agent(effective_ua)

        item_is_browser = is_browser_call or (getattr(item, "source", None) == "browser") or (isinstance(item.metadata, dict) and item.metadata.get("source") == "browser")
        device_family = _resolve_device_family(item, device_family)
        browser_family = _resolve_browser_family(item, browser_family)
        if item.os_family:
            os_family = item.os_family

        # Country & Geography resolution
        country_code, region_code, city_name, geo_source = _resolve_geography(
            item, client_ip, request, item_is_browser
        )

        # Source resolution
        source = item.source or (item.metadata.get("source") if isinstance(item.metadata, dict) else None)
        if not source:
            raw_ua = (req_ua or "").lower()
            if "python" in raw_ua or "httpx" in raw_ua or "aiohttp" in raw_ua or (isinstance(item.metadata, dict) and "method" in item.metadata):
                source = "python"
            elif request.headers.get("origin") or (effective_ua and ("mozilla" in effective_ua.lower() or "chrome" in effective_ua.lower())):
                source = "browser"
            else:
                source = "server"

        metadata = dict(item.metadata) if item.metadata else {}
        metadata["source"] = source
        if is_bot:
            metadata["is_bot"] = True
            metadata["bot_name"] = bot_name

        event_data = {
            "event_id": event_id_str,
            "app_id": app_id,
            "environment": environment,
            "event_type": item.event_type.value if hasattr(item.event_type, "value") else str(item.event_type),
            "event_name": item.event_name,
            "visitor_id": item.visitor_id,
            "session_id": item.session_id,
            "page_path": clean_path,
            "referrer_domain": ref_domain,
            "referrer_category": ref_cat,
            "source": source,
            "device_family": device_family,
            "os_family": os_family,
            "browser_family": browser_family,
            "country_code": country_code,
            "region_code": region_code,
            "city_name": city_name,
            "geo_source": geo_source,
            "ip_masked": masked_ip,
            "duration_ms": item.duration_ms,
            "consent_status": getattr(item, "consent_status", "ANALYTICS_ALLOWED" if item.visitor_id else "NO_STORAGE"),
            "metadata": metadata,
            "timestamp": event_timestamp.isoformat(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        is_pv = 1 if str(event_data["event_type"]).lower() == "pageview" else 0
        duration_sec = max(0, (item.duration_ms or 0) // 1000)
        session_data = {
            "session_id": item.session_id or f"sess_{uuid.uuid4().hex[:12]}",
            "visitor_id": item.visitor_id,
            "started_at": event_timestamp.isoformat(),
            "pageviews_count": is_pv,
            "duration_seconds": duration_sec,
            "event_type": event_data["event_type"],
            "entry_page": clean_path,
            "referrer_domain": ref_domain,
            "referrer_category": ref_cat,
            "country_code": country_code,
            "geo_source": geo_source,
            "device_family": device_family,
        }

        _persist_event(repo,
            app_id=app_id,
            environment=environment,
            event_id=event_id_str,
            event_data=event_data,
            session_data=session_data,
        )
        persisted_ids.append(event_id)

    return BatchIngestResponse(
        status="accepted",
        processed_count=len(persisted_ids),
        failed_count=0,
        persisted_event_ids=persisted_ids,
    )
