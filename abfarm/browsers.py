"""Browser backends.

cloak     CloakBrowser Pro (stealth Chromium, licensed). Best Turnstile pass rate.
camoufox  Camoufox (patched Firefox). Needs GTK shared libs; headless is detected
          more often by Cloudflare, expect "empty widget" retries.
chromium  Vanilla Playwright Chromium. Only for debugging markup.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from .config import Config


@dataclass
class BrowserSession:
    cfg: Config
    _stack: list[Any] | None = None

    async def __aenter__(self) -> Any:
        self._stack = []
        if self.cfg.browser == "cloak":
            try:
                from cloakbrowser import launch_async
            except ImportError as exc:  # pragma: no cover
                raise SystemExit("pip install cloakbrowser (Pro binary required)") from exc
            browser = await launch_async(
                headless=self.cfg.headless,
                proxy=self.cfg.proxy,
                humanize=self.cfg.humanize,
                geoip=False,
            )
            self._stack.append(browser)
            ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
            return await ctx.new_page()

        if self.cfg.browser == "camoufox":
            from camoufox.async_api import AsyncCamoufox
            kwargs: dict[str, Any] = {"headless": self.cfg.headless, "i_know_what_im_doing": True}
            if self.cfg.proxy:
                kwargs["proxy"] = {"server": self.cfg.proxy}
            cm = AsyncCamoufox(**kwargs)
            browser = await cm.__aenter__()
            self._stack.append(cm)
            ctx = await browser.new_context()
            return await ctx.new_page()

        from playwright.async_api import async_playwright
        pw = await async_playwright().start()
        self._stack.append(pw)
        proxy = {"server": self.cfg.proxy} if self.cfg.proxy else None
        browser = await pw.chromium.launch(headless=self.cfg.headless, proxy=proxy,
                                           args=["--no-sandbox", "--disable-dev-shm-usage"])
        self._stack.append(browser)
        ctx = await browser.new_context()
        return await ctx.new_page()

    async def __aexit__(self, *exc: Any) -> None:
        for item in reversed(self._stack or []):
            try:
                if hasattr(item, "__aexit__"):
                    await item.__aexit__(None, None, None)
                elif hasattr(item, "close"):
                    await item.close()
                elif hasattr(item, "stop"):
                    await item.stop()
            except Exception:
                pass
        self._stack = []
        await asyncio.sleep(0)