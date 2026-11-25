"""Cloudflare Turnstile handling for abliteration.ai.

The site mounts ``turnstile.render()`` on the password step with
``action=password_signup`` and sitekey ``0x4AAAAAAEcO2qYYBE_ztENL``. In managed
mode the widget usually verifies invisibly; when Cloudflare asks for an
interaction it draws a checkbox at the left edge of the widget box and clicking
it mints the token. There is no puzzle, so no OCR/slider solver and no third
party service is involved: the page's own widget mints a token and the same
page spends it immediately.

Two failure modes seen in the wild, both handled here:

* widget renders but never issues a token  -> the session is rate limited or the
  browser is fingerprinted. Rotate the exit IP, use a stealth browser, and retry.
* widget area collapses to an empty div   -> ``turnstile.render`` errored out.
  Reload the page and walk the form again.
"""
from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from typing import Any

TOKEN_SELECTOR = 'input[name="cf-turnstile-response"]'
WIDGET_SELECTOR = ".auth-turnstile"
CLICK_OFFSET_X = 25  # checkbox lives ~25px inside the widget box


@dataclass
class TurnstileResult:
    token: str | None
    state: str  # solved | empty-widget | no-token | missing


async def _safe_eval(page: Any, script: str, arg: Any = None) -> Any:
    """evaluate() that tolerates the page navigating mid-flight."""
    try:
        return await page.evaluate(script, arg)
    except Exception:
        return None


async def read_token(page: Any) -> str | None:
    """Return the current token value, or None."""
    return await _safe_eval(
        page,
        """(sel) => { const el = document.querySelector(sel); return el ? (el.value || null) : null; }""",
        TOKEN_SELECTOR,
    )


async def widget_box(page: Any) -> list[float] | None:
    return await _safe_eval(
        page,
        """(sel) => { const w = document.querySelector(sel); if (!w) return null;
            const r = w.getBoundingClientRect();
            return [r.x, r.y, r.width, r.height]; }""",
        WIDGET_SELECTOR,
    )


async def widget_has_frame(page: Any) -> bool:
    """The challenge iframe is injected inside the widget (sometimes shadow DOM)."""
    return bool(await _safe_eval(
        page,
        """(sel) => { const w = document.querySelector(sel); if (!w) return false;
            return !!(w.querySelector('iframe') || (w.shadowRoot && w.shadowRoot.querySelector('iframe'))); }""",
        WIDGET_SELECTOR,
    ))


async def solve(page: Any, timeout_s: int = 45, list_attempts: int = 3) -> TurnstileResult:
    """Poll, click the checkbox when needed, return the token."""
    tok = await read_token(page)
    if tok:
        return TurnstileResult(tok, "solved")

    box = await widget_box(page)
    if box is None:
        return TurnstileResult(None, "missing")

    # let the widget finish its own invisible pass before poking it
    for _ in range(6):
        tok = await read_token(page)
        if tok:
            return TurnstileResult(tok, "solved")
        await asyncio.sleep(1)

    for attempt in range(list_attempts):
        box = await widget_box(page)
        if box is None:
            return TurnstileResult(None, "missing")
        x = box[0] + CLICK_OFFSET_X + random.uniform(-2, 2)
        y = box[1] + max(18.0, min(35.0, box[3] / 2)) + random.uniform(-2, 2)
        await page.mouse.move(x - 40, y - 12)
        await asyncio.sleep(random.uniform(0.15, 0.35))
        await page.mouse.click(x, y)
        for _ in range(timeout_s // list_attempts):
            tok = await read_token(page)
            if tok:
                return TurnstileResult(tok, "solved")
            await asyncio.sleep(1)
        if not await widget_has_frame(page):
            return TurnstileResult(None, "empty-widget")
    return TurnstileResult(None, "no-token")