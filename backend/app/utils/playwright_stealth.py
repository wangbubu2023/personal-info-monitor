"""Playwright stealth helpers."""


def stealth_init_script() -> str:
    """Return a lightweight anti-detection script for Playwright pages."""
    return """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
window.chrome = window.chrome || { runtime: {} };
Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4]});
"""

