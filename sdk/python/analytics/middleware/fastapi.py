"""FastAPI / Starlette ASGI Middleware for Server-Side Analytics (Milestone M4)."""

import time
from typing import Callable, Optional
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from analytics.client import AnalyticsClient, AsyncAnalyticsClient


class AnalyticsMiddleware(BaseHTTPMiddleware):
    """FastAPI/Starlette middleware for non-blocking server telemetry."""

    def __init__(
        self,
        app,
        client: AnalyticsClient | AsyncAnalyticsClient,
        exclude_paths: Optional[list[str]] = None,
    ):
        super().__init__(app)
        self.client = client
        self.exclude_paths = set(exclude_paths or ["/health/live", "/health/ready", "/metrics", "/favicon.ico"])

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Check exclusion list
        path = request.url.path
        if path in self.exclude_paths:
            return await call_next(request)

        start_time = time.time()
        response = None
        try:
            response = await call_next(request)
            return response
        finally:
            try:
                duration_ms = int((time.time() - start_time) * 1000)
                status_code = response.status_code if response else 500
                user_agent = request.headers.get("user-agent", "")
                referrer = request.headers.get("referer", None)

                metadata = {
                    "method": request.method,
                    "status_code": status_code,
                    "user_agent": user_agent[:255] if user_agent else None,
                }

                # Non-blocking tracking
                if isinstance(self.client, AsyncAnalyticsClient):
                    await self.client.track(
                        event_name=f"http_{request.method.lower()}",
                        event_type="pageview" if request.method == "GET" else "custom",
                        page_path=path,
                        referrer=referrer,
                        duration_ms=duration_ms,
                        source="python",
                        user_agent=user_agent[:512] if user_agent else None,
                        metadata=metadata,
                    )
                else:
                    self.client.track(
                        event_name=f"http_{request.method.lower()}",
                        event_type="pageview" if request.method == "GET" else "custom",
                        page_path=path,
                        referrer=referrer,
                        duration_ms=duration_ms,
                        source="python",
                        user_agent=user_agent[:512] if user_agent else None,
                        metadata=metadata,
                    )
            except Exception:
                # Fail-open guarantee: telemetry recording failure never interrupts response
                pass
