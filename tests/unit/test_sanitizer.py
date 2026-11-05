"""Unit Tests for URL Sanitization, Privacy Parameter Scrubbing & IP Masking."""

from api.app.services.geoip import mask_ip_address, resolve_coarse_geoip
from api.app.services.sanitizer import extract_referrer_domain, sanitize_url_path


def test_url_path_sanitization_removes_sensitive_parameters():
    """Verify that credentials and tokens in URL parameters are scrubbed."""
    raw_url = "https://askanna.ai/chat?session_id=98765&token=eyJhbGciOi...&q=search_term&auth=secret"
    sanitized = sanitize_url_path(raw_url)

    assert "/chat" in sanitized
    assert "token=[REDACTED]" in sanitized
    assert "auth=[REDACTED]" in sanitized
    assert "session_id=[REDACTED]" in sanitized
    assert "q=search_term" in sanitized


def test_url_path_normalization():
    """Verify trailing slash normalization."""
    assert sanitize_url_path("/dashboard/") == "/dashboard"
    assert sanitize_url_path("/dashboard") == "/dashboard"
    assert sanitize_url_path("/") == "/"


def test_referrer_domain_extraction():
    """Verify clean extraction of hostname from referrer URLs."""
    assert extract_referrer_domain("https://google.com/search?q=analytics") == "google.com"
    assert extract_referrer_domain("https://sub.domain.co.uk:8080/path") == "sub.domain.co.uk"
    assert extract_referrer_domain(None) is None


def test_ip_address_masking_zeroes_host_bits():
    """Verify that IPv4 is masked to /24 and raw IP is never retained."""
    assert mask_ip_address("203.0.113.195") == "203.0.113.0"
    assert mask_ip_address("192.168.1.50") == "192.168.1.0"
    assert mask_ip_address("10.0.5.23:8080") == "10.0.5.0"
    assert mask_ip_address(None) is None


def test_coarse_geoip_resolution_does_not_leak_raw_ip():
    """Transport/private addresses are not reliable visitor geography."""
    country, region, city = resolve_coarse_geoip("127.0.0.1")
    assert (country, region, city) == (None, None, None)

    # Public IPs must return unknown (None) rather than fabricated US/CA data (M2-17)
    country, region, city = resolve_coarse_geoip("8.8.8.8")
    assert country is None
    assert region is None
    assert city is None
