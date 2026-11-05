"""Conservative display projection for legacy as well as newly ingested records."""
import math
import re
import uuid
from datetime import datetime, timezone
from urllib.parse import unquote, urlsplit

SOURCES = {"browser", "python", "server", "backend", "flask_example", "smoke_test"}
PATH_SEGMENTS = {"home", "pricing", "dashboard", "analytics", "action", "checkout", "search", "settings", "products", "docs", "help", "about", "contact", "features", "welcome", "integration", "plans"}


def safe_event_name(value):
    if not isinstance(value, str) or len(value) > 128 or re.search(r"(?i)(apk_(live|test)_|eyJ|[a-f0-9]{16,}|[0-9]{7,})", value):
        return "Hidden"
    return value if re.fullmatch(r"[A-Za-z][A-Za-z0-9_.:-]{0,127}", value) else "Hidden"


def safe_path(value):
    try:
        path = unquote(urlsplit(value or "/").path)
        return "/" + "/".join(segment if segment.lower() in PATH_SEGMENTS else "[hidden]" for segment in path.split('/') if segment)[:1023]
    except Exception:
        return "/[hidden]"


def safe_event_id(value):
    try:
        return str(uuid.UUID(str(value)))
    except Exception:
        return ""


def safe_timestamp(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).isoformat()
    except Exception:
        return ""


def family(value, kind):
    allowed = {
        "device": {"desktop", "mobile", "tablet", "bot", "Other"},
        "browser": {"Chrome", "Firefox", "Safari", "Edge", "Opera", "Mobile Safari", "Chrome Mobile", "Other"},
        "os": {"Windows", "Linux", "Android", "iOS", "Mac OS X", "Other"},
    }
    return value if isinstance(value, str) and value in allowed[kind] else None


def safe_metadata(value):
    if not isinstance(value, dict):
        return {}
    result = {}
    for key in ("is_bot", "is_automated", "is_returning"):
        if type(value.get(key)) is bool:
            result[key] = value[key]
    for key, low, high in (("status_code", 100, 599), ("items", 0, 1000000), ("duration_ms", 0, 86400000)):
        number = value.get(key)
        if type(number) in (int, float) and low <= number <= high and math.isfinite(number):
            result[key] = number
    if isinstance(value.get("source"), str) and value["source"] in SOURCES:
        result["source"] = value["source"]
    if value.get("method") in ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"):
        result["method"] = value["method"]
    return result


def geography(record):
    # LO/DEV/Localhost and old unproven location claims are not visitor geography.
    # No verified lookup is configured today; only server-provenanced data may qualify.
    country = record.get("country_code")
    if record.get("geo_source") != "verified_coarse_lookup" or not isinstance(country, str) or not re.fullmatch(r"[A-Z]{2}", country) or country in ("LO", "ZZ", "XX"):
        return None, None
    city = record.get("city_name")
    if not isinstance(city, str) or not re.fullmatch(r"[A-Za-z .'-]{1,64}", city) or city.lower() in ("localhost", "local", "unknown"):
        city = None
    return country, city
