"""Reverse Proxy & Client IP Extraction Service (M2-10 Verified Trust Boundary)."""

import ipaddress
from typing import Optional
from fastapi import Request
from api.app.core.config import settings


def is_trusted_proxy(ip_str: Optional[str]) -> bool:
    """Check if an IP address belongs to the configured trusted proxies or CIDR subnets."""
    if not ip_str:
        return False
    try:
        ip_obj = ipaddress.ip_address(ip_str.strip())
        for proxy_pattern in settings.TRUSTED_PROXIES.split(","):
            pattern = proxy_pattern.strip()
            if not pattern:
                continue
            if "/" in pattern:
                if ip_obj in ipaddress.ip_network(pattern, strict=False):
                    return True
            else:
                if ip_obj == ipaddress.ip_address(pattern):
                    return True
    except Exception:
        pass
    return False


def extract_client_ip(request: Request) -> Optional[str]:
    """Securely extract client IP address enforcing verified trust boundaries (M2-10).
    
    1. If BEHIND_PROXY is False (local dev or direct connection), request.client.host is used.
       Untrusted X-Forwarded-For headers are discarded.
    2. If BEHIND_PROXY is True, verifies direct_peer against TRUSTED_PROXIES.
       If direct_peer is untrusted, X-Forwarded-For is discarded.
       If direct_peer is trusted, walks X-Forwarded-For right-to-left, stripping trusted hops.
       The first untrusted IP encountered is returned as the client IP.
    """
    direct_peer = request.client.host if request.client else None
    if not direct_peer:
        return None

    if not settings.BEHIND_PROXY:
        return direct_peer

    # Direct connection MUST come from a trusted proxy to evaluate XFF
    if not is_trusted_proxy(direct_peer):
        return direct_peer

    xff = request.headers.get("X-Forwarded-For")
    if not xff:
        return direct_peer

    # Walk right-to-left: discard trusted proxy hops
    hops = [h.strip() for h in xff.split(",") if h.strip()]
    for hop in reversed(hops):
        try:
            ipaddress.ip_address(hop)
        except ValueError:
            # Malformed/spoofed hop chain: fail-closed by discarding XFF and returning direct_peer
            return direct_peer

        if not is_trusted_proxy(hop):
            return hop

    return direct_peer
