"""Analytics Platform Python SDK.

Provides high-performance, non-blocking telemetry clients with strict fail-open guarantees.
"""

from analytics.client import AnalyticsClient, AsyncAnalyticsClient

__all__ = ["AnalyticsClient", "AsyncAnalyticsClient"]
__version__ = "0.1.0"
