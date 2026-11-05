"""In-Memory Sliding Window Rate Limiter for Telemetry Ingestion."""

import time
from collections import defaultdict
from typing import Dict, List, Tuple
from fastapi import HTTPException, status

from api.app.core.config import settings


class SlidingWindowRateLimiter:
    """Sliding window rate limiter to protect ingestion endpoints from abuse.
    
    Tracks requests per write_key and per source IP within a 60-second window.
    Automatically purges expired timestamps to maintain bounded memory footprint.
    """

    def __init__(self, key_limit: int = 2000, ip_limit: int = 120, window_seconds: int = 60, max_entries: int = 10000):
        self.key_limit = key_limit
        self.ip_limit = ip_limit
        self.window_seconds = window_seconds
        self.max_entries = max_entries
        self._key_windows: Dict[str, List[float]] = defaultdict(list)
        self._ip_windows: Dict[str, List[float]] = defaultdict(list)
        self._last_cleanup = time.time()

    def _cleanup_old_records(self, now: float, force: bool = False) -> None:
        """Purge entries older than the window, bounding total memory footprint."""
        if not force and now - self._last_cleanup < 30.0:
            return

        cutoff = now - self.window_seconds
        for mapping in (self._key_windows, self._ip_windows):
            expired_keys = []
            for k, timestamps in mapping.items():
                valid = [t for t in timestamps if t > cutoff]
                if valid:
                    mapping[k] = valid
                else:
                    expired_keys.append(k)
            for k in expired_keys:
                del mapping[k]

            # If still over max entries after purging expired, evict oldest keys (FIFO safety guard)
            if len(mapping) > self.max_entries:
                overflow_count = len(mapping) - self.max_entries
                keys_to_evict = list(mapping.keys())[:overflow_count]
                for k in keys_to_evict:
                    del mapping[k]

        self._last_cleanup = now

    def check_rate_limit(self, write_key: str, client_ip: str, cost: int = 1) -> None:
        """Check if the request exceeds rate limits, taking batch size cost into account (M2-11).
        
        Raises:
            HTTPException (429) if limits are exceeded.
        """
        now = time.time()
        cutoff = now - self.window_seconds

        self._cleanup_old_records(now)

        # 1. Check IP limit (if IP is present)
        if client_ip:
            ip_times = [t for t in self._ip_windows[client_ip] if t > cutoff]
            if len(ip_times) + cost > self.ip_limit:
                retry_after = int(self.window_seconds - (now - ip_times[0])) + 1 if ip_times else self.window_seconds
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Rate limit exceeded for IP. Max {self.ip_limit} events per minute.",
                    headers={"Retry-After": str(max(1, retry_after))},
                )
            ip_times.extend([now] * cost)
            self._ip_windows[client_ip] = ip_times

        # 2. Check Write Key limit
        if write_key:
            key_times = [t for t in self._key_windows[write_key] if t > cutoff]
            if len(key_times) + cost > self.key_limit:
                retry_after = int(self.window_seconds - (now - key_times[0])) + 1 if key_times else self.window_seconds
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Rate limit exceeded for write_key. Max {self.key_limit} events per minute.",
                    headers={"Retry-After": str(max(1, retry_after))},
                )
            key_times.extend([now] * cost)
            self._key_windows[write_key] = key_times

    def reset(self) -> None:
        """Clear all rate limit records (useful for test suites)."""
        self._key_windows.clear()
        self._ip_windows.clear()
        self._last_cleanup = time.time()


# Global rate limiter singleton initialized with configuration limits
rate_limiter = SlidingWindowRateLimiter(
    key_limit=settings.RATE_LIMIT_PER_KEY_MINUTE,
    ip_limit=settings.RATE_LIMIT_PER_IP_MINUTE,
    window_seconds=60,
)
