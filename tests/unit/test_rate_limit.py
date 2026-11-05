"""Unit tests for sliding window rate limiter."""

import pytest
from fastapi import HTTPException
from api.app.core.rate_limit import SlidingWindowRateLimiter


def test_rate_limiter_allows_requests_under_threshold():
    limiter = SlidingWindowRateLimiter(key_limit=5, ip_limit=5, window_seconds=60)
    # 5 requests should pass
    for _ in range(5):
        limiter.check_rate_limit(write_key="test_key", client_ip="192.168.1.0")


def test_rate_limiter_blocks_key_exceeding_threshold():
    limiter = SlidingWindowRateLimiter(key_limit=3, ip_limit=10, window_seconds=60)
    for _ in range(3):
        limiter.check_rate_limit(write_key="test_key", client_ip="192.168.1.0")

    with pytest.raises(HTTPException) as exc_info:
        limiter.check_rate_limit(write_key="test_key", client_ip="192.168.1.0")
    assert exc_info.value.status_code == 429
    assert "write_key" in exc_info.value.detail
    assert "Retry-After" in exc_info.value.headers


def test_rate_limiter_blocks_ip_exceeding_threshold():
    limiter = SlidingWindowRateLimiter(key_limit=10, ip_limit=2, window_seconds=60)
    limiter.check_rate_limit(write_key="key_1", client_ip="10.0.0.0")
    limiter.check_rate_limit(write_key="key_2", client_ip="10.0.0.0")

    with pytest.raises(HTTPException) as exc_info:
        limiter.check_rate_limit(write_key="key_3", client_ip="10.0.0.0")
    assert exc_info.value.status_code == 429
    assert "IP" in exc_info.value.detail
