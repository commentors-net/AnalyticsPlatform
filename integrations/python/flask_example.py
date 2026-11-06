"""Minimal server-side integration using this repository's existing Python SDK.

Install sdk/python[flask] first. No telemetry is enabled until explicitly configured.
No identifiers, cookies, browser storage or new sessions are created by this example.
"""

import logging
import os
from urllib.parse import urlsplit

from flask import Flask, g, jsonify, request
from analytics.client import AnalyticsClient


def _existing_identifiers():
    """Optional adapter for the host's already approved pseudonymous identifiers.

    The host may set these g attributes in its own before_request hook. Never use
    an authentication session token, email, user message or customer record ID.
    """
    consent = getattr(g, "analytics_consent", "NO_STORAGE")
    if consent not in ("ANONYMOUS", "ANALYTICS_ALLOWED"):
        return None, None

    def valid(value):
        return value if isinstance(value, str) and 0 < len(value) <= 128 else None

    visitor = valid(getattr(g, "analytics_visitor_id", None)) if consent == "ANALYTICS_ALLOWED" else None
    session = valid(getattr(g, "analytics_session_id", None))
    return visitor, session


def create_app():
    app = Flask(__name__)
    # Do not enable SDK/httpx DEBUG logging: the SDK can log rejected payloads.
    logging.getLogger("analytics").setLevel(logging.WARNING)
    client = None
    try:
        enabled = os.environ.get("ANALYTICS_ENABLED", "false").lower() == "true"
        environment = os.environ.get("ANALYTICS_ENVIRONMENT", "test").lower()
        endpoint = os.environ.get(
            "ANALYTICS_ENDPOINT", "https://analytics-platform-427212681311.us-central1.run.app"
        ).rstrip("/")
        key = os.environ.get(f"ANALYTICS_WRITE_KEY_{environment.upper()}", "").strip()
        url = urlsplit(endpoint)
        local_http = url.scheme == "http" and url.hostname in ("localhost", "127.0.0.1", "::1")
        valid_endpoint = (
            (url.scheme == "https" or local_http) and url.hostname
            and url.username is None and url.password is None
            and not url.query and not url.fragment and not url.path
        )
        if enabled and environment in ("test", "live") and valid_endpoint and key.startswith(f"apk_{environment}_"):
            # Compatibility settings, not a delivery guarantee: worker and manual
            # flush stay below the current server's 50-event limit. Queue pressure
            # drops events; this intentionally favors the host request's latency.
            client = AnalyticsClient(
                endpoint=endpoint,
                write_key=key,
                batch_size=1,
                max_queue_size=1,
                flush_interval_sec=0.1,
                timeout_sec=2.0,
            )
    except Exception:
        # Analytics setup must not prevent the host application from serving.
        app.logger.warning("Analytics disabled because client setup failed")

    app.extensions["analytics_client"] = client

    def emit(page_path, event_name=None):
        if client is None:
            return
        try:
            visitor_id, session_id = _existing_identifiers()
            ua = request.headers.get("User-Agent", "")[:512] if request else None
            # Optional trustworthy coarse country from edge proxy headers (e.g. CF-IPCountry)
            country = request.headers.get("CF-IPCountry", "")[:2].upper() if request else None
            country = country if country and len(country) == 2 and country.isalpha() and country not in ("LO", "ZZ", "XX") else None
            metadata = {"source": "flask_example"}
            if event_name is None:
                client.pageview(page_path, visitor_id=visitor_id, session_id=session_id, user_agent=ua, country_code=country, metadata=metadata)
            else:
                client.track(event_name, event_type="custom", page_path=page_path,
                             visitor_id=visitor_id, session_id=session_id, user_agent=ua, country_code=country, metadata=metadata)
        except Exception:
            # Also protects the host if an optional existing-ID adapter fails.
            pass

    @app.get("/")
    def index():
        emit("/")
        return jsonify(service="Flask integration example", status="ok")

    @app.post("/action")
    def action():
        # Place the telemetry call after the host's successful business action.
        # This demonstration reads no body, URL parameters, cookies or headers.
        emit("/action", "example_action")
        return jsonify(ok=True)

    @app.get("/health")
    def health():
        return jsonify(status="ok")  # No telemetry for health checks.

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)
