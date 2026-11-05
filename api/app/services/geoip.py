"""In-Memory GeoIP Resolution & IP Masking (Zero Raw IP Persistence)."""

import ipaddress
from typing import Optional, Tuple


def mask_ip_address(ip_str: Optional[str]) -> Optional[str]:
    """Truncate IP address to preserve privacy (IPv4 /24, IPv6 /48).
    
    Zero raw IP is ever persisted to PostgreSQL.
    Example:
        '203.0.113.195' -> '203.0.113.0'
        '2001:db8:85a3:8d3:1319:8a2e:370:7348' -> '2001:db8:85a3::'
    """
    if not ip_str:
        return None

    try:
        # Strip potential port
        clean_ip = ip_str.split(",")[0].strip().split(":")[0] if "." in ip_str else ip_str.split(",")[0].strip()
        ip_obj = ipaddress.ip_address(clean_ip)

        if isinstance(ip_obj, ipaddress.IPv4Address):
            # Mask to /24 (zero last octet)
            network = ipaddress.IPv4Network(f"{clean_ip}/24", strict=False)
            return str(network.network_address)
        elif isinstance(ip_obj, ipaddress.IPv6Address):
            # Mask to /48
            network = ipaddress.IPv6Network(f"{clean_ip}/48", strict=False)
            return str(network.network_address)
    except Exception:
        pass
    return None


def resolve_coarse_geoip(ip_str: Optional[str]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Resolve client IP to coarse location in volatile RAM without saving raw IP (M2-17).
    
    Returns:
        (country_code, region_code, city_name) or (None, None, None) if unknown.
    """
    if not ip_str:
        return None, None, None

    # A private/proxy/loopback address describes transport, not a visitor location.
    # Without a reviewed lookup provider every address has unknown geography.
    return None, None, None
