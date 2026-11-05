"""URL Sanitization & Privacy Parameter Scrubber."""

import re
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

# Sensitive query parameter patterns to redact
SENSITIVE_PARAM_PATTERN = re.compile(
    r"^(token|jwt|key|api_key|auth|password|passwd|secret|ssn|vin|email|mail|user|username|"
    r"session|session_id|access_token|refresh_token|code|id_token|verification_code|magic_link)$",
    re.IGNORECASE,
)


def sanitize_url_path(raw_url: str) -> str:
    """Sanitize URL paths by stripping or redacting sensitive tokens and credentials (M2-07, M2-17).
    
    Supports hash-based SPA routing while scrubbing parameters from both query string and hash fragment.
    """
    if not raw_url:
        return "/"

    try:
        parsed = urlparse(raw_url)
        path = parsed.path if parsed.path else "/"

        # Normalize trailing slashes (except root)
        if len(path) > 1 and path.endswith("/"):
            path = path[:-1]

        # Sanitize query parameters in query string
        clean_query = ""
        if parsed.query:
            clean_params = []
            for key, value in parse_qsl(parsed.query, keep_blank_values=True):
                if SENSITIVE_PARAM_PATTERN.match(key):
                    clean_params.append((key, "[REDACTED]"))
                else:
                    clean_params.append((key, value))
            clean_query = urlencode(clean_params, safe="[]")

        # Sanitize fragment (supporting hash-based SPA routing while redacting tokens)
        clean_fragment = ""
        if parsed.fragment:
            frag = parsed.fragment
            if "?" in frag:
                frag_path, frag_query = frag.split("?", 1)
                frag_clean_params = []
                for key, value in parse_qsl(frag_query, keep_blank_values=True):
                    if SENSITIVE_PARAM_PATTERN.match(key):
                        frag_clean_params.append((key, "[REDACTED]"))
                    else:
                        frag_clean_params.append((key, value))
                clean_frag_query = urlencode(frag_clean_params, safe="[]")
                clean_fragment = f"#{frag_path}?{clean_frag_query}" if clean_frag_query else f"#{frag_path}"
            else:
                clean_fragment = f"#{frag}"

        res = path
        if clean_query:
            res = f"{res}?{clean_query}"
        if clean_fragment:
            res = f"{res}{clean_fragment}"
        return res
    except Exception:
        # Fallback to root path if malformed
        return "/"


def extract_referrer_domain(referrer: Optional[str]) -> Optional[str]:
    """Extract coarse hostname from referrer string, safely handling full URLs, userinfo, and naked hostnames (M2-17)."""
    if not referrer or not referrer.strip():
        return None

    ref = referrer.strip().lower()
    if not ref.startswith("http://") and not ref.startswith("https://") and not ref.startswith("//"):
        ref = "https://" + ref

    try:
        parsed = urlparse(ref)
        domain = parsed.netloc.lower()
        if "@" in domain:
            domain = domain.split("@")[-1]
        if ":" in domain:
            domain = domain.split(":")[0]
        return domain or None
    except Exception:
        return None
