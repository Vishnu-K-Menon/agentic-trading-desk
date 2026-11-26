"""MCP server that reads a web page in a real browser, for pages a plain fetch cannot read.

One stateless tool, so a single server can be shared by every researcher: each call gets
a fresh browser context, and one headless browser is reused across calls.
"""

import asyncio
import ipaddress
import os
import socket
from urllib.parse import urlparse
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("browser_server")

MAX_CHARS = 12_000
PAGE_TIMEOUT_MS = 30_000
SETTLE_MS = 1_500
CONCURRENT_PAGES = 2

_playwright = None
_browser = None
_launch_lock = asyncio.Lock()
_pages = asyncio.Semaphore(CONCURRENT_PAGES)


def _is_public(host: str) -> bool:
    """True only if every address the host resolves to is on the public internet."""
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, None)}
    except socket.gaierror:
        return False
    return bool(addresses) and all(ipaddress.ip_address(address).is_global for address in addresses)


async def _allowed(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    return await asyncio.to_thread(_is_public, parsed.hostname)


async def _get_browser():
    global _playwright, _browser
    async with _launch_lock:
        if _browser is None or not _browser.is_connected():
            from playwright.async_api import async_playwright

            _playwright = _playwright or await async_playwright().start()
            # Use the installed Chrome where there is one; in the container, the bundled Chromium.
            channel = os.getenv("BROWSER_CHANNEL", "chrome" if os.name == "nt" else "")
            _browser = await _playwright.chromium.launch(headless=True, channel=channel or None)
    return _browser


@mcp.tool()
async def read_page(url: str) -> dict:
    """Open a web page in a real browser and return its title and readable text. Slower
    than fetch: use it only when fetch fails or returns an empty or blocked page, for
    example on sites that need JavaScript.

    Args:
        url: the full http or https address of the page
    """
    if not await _allowed(url):
        return {"url": url, "error": "Only public http and https addresses can be read"}
    async with _pages:
        browser = await _get_browser()
        context = await browser.new_context()
        try:
            # Requests the page makes are held to the same rule as the page itself.
            async def guard(route):
                if await _allowed(route.request.url):
                    await route.continue_()
                else:
                    await route.abort()

            await context.route("**/*", guard)
            page = await context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
            await page.wait_for_timeout(SETTLE_MS)
            # Redirects are followed by the browser itself, so check where the page ended up.
            for frame in page.frames:
                if frame.url not in ("", "about:blank") and not await _allowed(frame.url):
                    return {"url": url, "error": "The page redirected to an address that cannot be read"}
            title = await page.title()
            text = await page.inner_text("body", timeout=PAGE_TIMEOUT_MS)
        except Exception as e:
            return {"url": url, "error": f"Could not read the page: {str(e)[:200]}"}
        finally:
            await context.close()
    text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    return {"url": url, "title": title, "text": text[:MAX_CHARS], "truncated": len(text) > MAX_CHARS}


if __name__ == "__main__":
    mcp.run(transport="stdio")
