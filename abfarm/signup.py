"""The signup walk: email -> password -> Turnstile -> emailed code -> API key."""
from __future__ import annotations

import asyncio
import json
import random
import re
import string
import time
from dataclasses import dataclass, asdict
from typing import Any

from . import turnstile
from .config import Config

PROJECT_RE = re.compile(r"proj_[A-Za-z0-9_\-]+")
SECRET_RE = re.compile(r'"secret_key"\s*:\s*"([^"]+)"')


class SignupError(RuntimeError):
    pass


@dataclass
class Account:
    email: str
    password: str
    api_key: str
    project_id: str
    created_at: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def random_password(length: int = 14) -> str:
    body = "".join(random.choices(string.ascii_letters, k=length - 4))
    return "Pr" + body + "7x!Q"


async def _human_type(page: Any, selector: str, text: str) -> None:
    await page.locator(selector).click()
    await asyncio.sleep(random.uniform(0.3, 0.8))
    await page.keyboard.type(text, delay=random.randint(60, 130))


async def _wait_input(page: Any, selector: str, timeout_s: int) -> None:
    await page.wait_for_selector(selector, timeout=timeout_s * 1000)


async def signup(page: Any, cfg: Config, mailbox: Any, password: str | None = None) -> Account:
    """Drive one signup on an already-open page. Raises SignupError on a hard block."""
    password = password or random_password()
    hits: dict[str, int] = {}

    async def on_response(resp: Any) -> None:
        url = resp.url
        if "/auth/password/sign-up" in url:
            hits["signup"] = resp.status
        elif "/auth/password/verify" in url and "resend" not in url:
            hits["verify"] = resp.status
    page.on("response", lambda r: asyncio.create_task(on_response(r)))

    await page.goto(cfg.signup_url, wait_until="domcontentloaded", timeout=cfg.timeout_s * 1000)
    await _wait_input(page, 'input[name="email"]', cfg.timeout_s)
    await asyncio.sleep(random.uniform(2, 3))
    await _human_type(page, 'input[name="email"]', mailbox.address)
    await asyncio.sleep(random.uniform(0.5, 1.2))
    for _ in range(3):
        try:
            await page.click("button.auth-primary-action", timeout=8000)
            break
        except Exception:
            await asyncio.sleep(1)
    await _wait_input(page, 'input[name="password"]', 30)
    await asyncio.sleep(random.uniform(1.5, 2.5))
    await _human_type(page, 'input[name="password"]', password)

    result = await turnstile.solve(page, timeout_s=cfg.turnstile_wait_s,
                                   list_attempts=cfg.turnstile_click_attempts)
    if not result.token:
        raise SignupError(f"turnstile: {result.state}")
    await asyncio.sleep(random.uniform(0.4, 0.9))

    submit = page.locator("button.auth-primary-action").first
    for _ in range(20):
        if await submit.is_enabled():
            break
        await asyncio.sleep(0.5)
    await submit.click()

    for _ in range(cfg.timeout_s * 2):
        if "signup" in hits:
            break
        await asyncio.sleep(0.5)
    status = hits.get("signup")
    if status == 403:
        raise SignupError("auth_policy_denied: WorkOS Radar blocked this email/IP "
                          "(disposable domain or burned exit). Use a real mailbox + fresh residential exit.")
    if status not in (200, 201):
        raise SignupError(f"sign-up returned {status}")

    try:
        await _wait_input(page, 'input[name="code"]', cfg.timeout_s)
    except Exception as exc:
        raise SignupError(f"no code form (url={page.url})") from exc

    code = await asyncio.to_thread(mailbox.wait_code, 240)
    if not code:
        raise SignupError("no verification code arrived")
    await _human_type(page, 'input[name="code"]', code)

    # WorkOS auto-submits on the 6th digit, but some builds need the button
    await asyncio.sleep(3)
    for _ in range(30):
        if page.url.rstrip("/") != cfg.signup_url or "verify" in hits:
            break
        btn = page.locator("button.auth-primary-action").first
        if await btn.count() and await btn.is_enabled():
            try:
                await btn.click()
            except Exception:
                pass
        await asyncio.sleep(1)

    project_id, api_key = await _provision_key(page, cfg)
    return Account(mailbox.address, password, api_key, project_id, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


async def _provision_key(page: Any, cfg: Config) -> tuple[str, str]:
    """Wait for the workspace, then mint a project API key from the console."""
    project_id = ""
    for attempt in range(24):
        if "/console" not in page.url:
            try:
                await page.goto(cfg.console_url, wait_until="domcontentloaded", timeout=45000)
            except Exception:
                pass
        try:
            session = await page.evaluate(
                """async () => { const r = await fetch('/api/console/v1/session', {credentials:'include'});
                    return await r.text(); }"""
            )
        except Exception:
            session = ""
        if "workspace_setup_pending" in session:
            await asyncio.sleep(5)
            continue
        m = PROJECT_RE.search(session)
        if m:
            project_id = m.group(0)
            break
        await asyncio.sleep(5)
    if not project_id:
        raise SignupError("no project id in console session")

    created = await page.evaluate(
        """async (p) => {
            const r = await fetch('/api/console/v1/projects/' + p + '/api-keys', {
                method: 'POST', credentials: 'include',
                headers: {'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID()},
                body: JSON.stringify({name: 'farm'})});
            return {status: r.status, body: await r.text()}; }""",
        project_id,
    )
    m = SECRET_RE.search(created.get("body", ""))
    if created["status"] not in (200, 201) or not m:
        raise SignupError(f"key creation failed: {created['status']} {created.get('body', '')[:200]}")
    return project_id, m.group(1)


async def run_one(cfg: Config, mailbox: Any, password: str | None = None) -> Account:
    """End-to-end single account, retrying the whole walk on transient widget fails."""
    from .browsers import BrowserSession

    last: Exception | None = None
    for attempt in range(1, 4):
        async with BrowserSession(cfg) as page:
            try:
                return await signup(page, cfg, mailbox, password)
            except SignupError as exc:
                last = exc
                msg = str(exc)
                print(f"  attempt {attempt} failed: {msg}")
                if msg.startswith("auth_policy_denied"):
                    raise
                await asyncio.sleep(3)
    raise SignupError(f"gave up after 3 attempts: {last}")


_ = json