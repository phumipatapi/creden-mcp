"""Playwright-based endpoint discovery.

Logs in via the browser, opens a company detail page, scrolls through it, and
records every XHR/fetch call hitting /sapi. Output is written to
``discovery_output/<company_id>.json`` for offline inspection.

Usage:
    python -m creden_mcp.discovery <company_id> [--lang th|en] [--headed]

This is the tool used to find the financial-graph and shareholder endpoints
that aren't documented in CLAUDE.md yet.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

from playwright.async_api import Request, Response, async_playwright

from .config import Settings

log = logging.getLogger(__name__)

OUTPUT_DIR = Path("discovery_output")


async def _login(page: Any, settings: Settings) -> None:
    email, password = settings.require_credentials()
    await page.goto(f"{settings.base_url}/login", wait_until="domcontentloaded")
    # Form selectors are guessed from typical layouts; adjust if they don't match
    await page.fill('input[type="email"], input[name="email"]', email)
    await page.fill('input[type="password"], input[name="password"]', password)
    await page.click('button[type="submit"], button:has-text("Login"), button:has-text("เข้าสู่ระบบ")')
    await page.wait_for_load_state("networkidle")


async def discover(company_id: str, lang: str, headed: bool) -> Path:
    settings = Settings.from_env()
    OUTPUT_DIR.mkdir(exist_ok=True)
    captures: list[dict[str, Any]] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=not headed)
        context = await browser.new_context(locale="th-TH" if lang == "th" else "en-US")
        page = await context.new_page()

        async def on_response(resp: Response) -> None:
            url = resp.url
            if "/sapi/" not in url:
                return
            entry: dict[str, Any] = {
                "url": url,
                "method": resp.request.method,
                "status": resp.status,
                "request_post_data": resp.request.post_data,
                "response_headers": dict(resp.headers),
            }
            try:
                ctype = resp.headers.get("content-type", "")
                if "json" in ctype:
                    entry["response_json"] = await resp.json()
                else:
                    body = await resp.text()
                    entry["response_text"] = body[:2000]
            except Exception as e:  # noqa: BLE001 — capture is best-effort
                entry["capture_error"] = repr(e)
            captures.append(entry)

        page.on("response", on_response)
        page.on("requestfailed", lambda r: log.warning("requestfailed: %s %s", r.url, r.failure))

        try:
            await _login(page, settings)
            detail_url = f"{settings.base_url}/company/{company_id}?lang={lang}"
            log.info("Opening %s", detail_url)
            await page.goto(detail_url, wait_until="networkidle")
            # Trigger lazy-loaded charts/tabs by scrolling
            for _ in range(8):
                await page.mouse.wheel(0, 1500)
                await page.wait_for_timeout(800)
            # Try clicking common tab labels — best effort
            for label in ["งบการเงิน", "Financial", "ผู้ถือหุ้น", "Shareholders", "เครือข่าย", "Network"]:
                try:
                    await page.get_by_text(label, exact=False).first.click(timeout=1500)
                    await page.wait_for_timeout(1500)
                except Exception:
                    pass
            await page.wait_for_timeout(2000)
        finally:
            await context.close()
            await browser.close()

    out = OUTPUT_DIR / f"{company_id}_{lang}.json"
    out.write_text(json.dumps(captures, ensure_ascii=False, indent=2))
    log.info("Captured %d /sapi calls → %s", len(captures), out)
    return out


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="Discover Creden /sapi endpoints via Playwright")
    p.add_argument("company_id", help="Creden company id (from search results)")
    p.add_argument("--lang", default="th", choices=["th", "en"])
    p.add_argument("--headed", action="store_true", help="Show the browser window")
    args = p.parse_args()
    asyncio.run(discover(args.company_id, args.lang, args.headed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
