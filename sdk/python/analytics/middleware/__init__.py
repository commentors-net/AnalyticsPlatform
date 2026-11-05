"""Web Framework Middleware for Python Analytics SDK."""

from analytics.middleware.fastapi import AnalyticsMiddleware
from analytics.middleware.flask import FlaskAnalytics

__all__ = ["AnalyticsMiddleware", "FlaskAnalytics"]
