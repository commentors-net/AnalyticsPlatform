"""Bot Classification & User-Agent Parsing Service."""

import re
from typing import Optional, Tuple


# Known automated crawler and bot signatures (case-insensitive)
BOT_REGEX = re.compile(
    r"(googlebot|bingbot|yandexbot|baiduspider|duckduckbot|slurp|"
    r"facebookexternalhit|twitterbot|slackbot|telegrambot|whatsapp|"
    r"linkedinbot|discordbot|pinterestbot|ia_archiver|semrushbot|"
    r"ahrefsbot|mj12bot|dotbot|petalbot|exabot|"
    r"headlesschrome|puppeteer|selenium|playwright|phantomjs|lighthouse|"
    r"curl/|python-requests|aiohttp|postmanruntime|wget|go-http-client|"
    r"apache-httpclient|okhttp|httpclient)",
    re.IGNORECASE,
)

# Browser detection patterns
BROWSER_PATTERNS = [
    ("Edge", re.compile(r"Edg[A-Za-z]?/(\d+)", re.IGNORECASE)),
    ("Chrome", re.compile(r"Chrome/(\d+)", re.IGNORECASE)),
    ("Firefox", re.compile(r"Firefox/(\d+)", re.IGNORECASE)),
    ("Safari", re.compile(r"Version/(\d+).+Safari", re.IGNORECASE)),
    ("Opera", re.compile(r"(?:OPR|Opera)/(\d+)", re.IGNORECASE)),
]

# OS detection patterns (check mobile iOS before macOS because iOS UA includes 'like Mac OS X')
OS_PATTERNS = [
    ("iOS", re.compile(r"iPhone|iPad|iPod", re.IGNORECASE)),
    ("Android", re.compile(r"Android", re.IGNORECASE)),
    ("Windows", re.compile(r"Windows NT", re.IGNORECASE)),
    ("macOS", re.compile(r"Macintosh|Mac OS X", re.IGNORECASE)),
    ("Linux", re.compile(r"Linux", re.IGNORECASE)),
]


def classify_user_agent(
    user_agent: Optional[str],
) -> Tuple[bool, Optional[str], Optional[str], Optional[str], Optional[str]]:
    """Analyze User-Agent string to detect bots, browsers, OS, and device types.
    
    Returns:
        (is_bot, bot_name, browser_family, os_family, device_family)
    """
    if not user_agent or not user_agent.strip():
        return False, None, None, None, "unknown"

    ua = user_agent.strip()

    # 1. Check for automated crawlers / bots
    bot_match = BOT_REGEX.search(ua)
    if bot_match:
        bot_name = bot_match.group(1).lower()
        return True, bot_name, bot_name, "Bot", "bot"

    # 2. Detect OS Family
    os_family = None
    for name, pattern in OS_PATTERNS:
        if pattern.search(ua):
            os_family = name
            break

    # 3. Detect Browser Family
    browser_family = None
    for name, pattern in BROWSER_PATTERNS:
        if pattern.search(ua):
            browser_family = name
            break

    # 4. Detect Device Family
    device_family = "desktop"
    if os_family in ("iOS", "Android") or re.search(r"Mobile|Tablet", ua, re.IGNORECASE):
        device_family = "tablet" if re.search(r"iPad|Tablet", ua, re.IGNORECASE) else "mobile"

    return False, None, browser_family, os_family, device_family
