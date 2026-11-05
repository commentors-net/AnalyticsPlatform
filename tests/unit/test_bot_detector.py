"""Unit tests for bot classification and User-Agent parsing."""

from api.app.services.bot_detector import classify_user_agent


def test_search_engine_bot_detection():
    ua = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
    is_bot, bot_name, browser, os_name, device = classify_user_agent(ua)
    assert is_bot is True
    assert bot_name == "googlebot"
    assert device == "bot"


def test_headless_browser_bot_detection():
    ua = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/114.0.5735.198 Safari/537.36"
    is_bot, bot_name, browser, os_name, device = classify_user_agent(ua)
    assert is_bot is True
    assert bot_name == "headlesschrome"
    assert device == "bot"


def test_script_client_bot_detection():
    ua = "python-requests/2.31.0"
    is_bot, bot_name, browser, os_name, device = classify_user_agent(ua)
    assert is_bot is True
    assert bot_name == "python-requests"


def test_legitimate_desktop_browser():
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    is_bot, bot_name, browser, os_name, device = classify_user_agent(ua)
    assert is_bot is False
    assert bot_name is None
    assert browser == "Chrome"
    assert os_name == "Windows"
    assert device == "desktop"


def test_legitimate_mobile_browser():
    ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1"
    is_bot, bot_name, browser, os_name, device = classify_user_agent(ua)
    assert is_bot is False
    assert os_name == "iOS"
    assert device == "mobile"
