"""Flask Extension for Server-Side Analytics (Milestone M4)."""

import time
from typing import Optional
from analytics.client import AnalyticsClient


class FlaskAnalytics:
    """Flask extension for automated request tracking with strict fail-open guarantees."""

    def __init__(
        self,
        app=None,
        client: Optional[AnalyticsClient] = None,
        exclude_paths: Optional[list[str]] = None,
    ):
        self.client = client
        self.exclude_paths = set(exclude_paths or ["/health", "/static", "/favicon.ico"])
        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        from flask import g, request

        @app.before_request
        def before_request():
            g._analytics_start_time = time.time()

        @app.after_request
        def after_request(response):
            try:
                if not self.client or request.path in self.exclude_paths:
                    return response

                start_time = getattr(g, "_analytics_start_time", None)
                duration_ms = int((time.time() - start_time) * 1000) if start_time else None
                user_agent = request.headers.get("User-Agent", "")
                referrer = request.referrer

                metadata = {
                    "method": request.method,
                    "status_code": response.status_code,
                    "user_agent": user_agent[:255] if user_agent else None,
                }

                self.client.track(
                    event_name=f"http_{request.method.lower()}",
                    event_type="pageview" if request.method == "GET" else "custom",
                    page_path=request.path,
                    referrer=referrer,
                    duration_ms=duration_ms,
                    source="python",
                    user_agent=user_agent[:512] if user_agent else None,
                    metadata=metadata,
                )
            except Exception:
                # Fail-open guarantee: telemetry recording never affects response
                pass
            return response
