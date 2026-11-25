"""Unit tests: no browser, no network. Fake page objects model the widget states."""
import asyncio
import json

import pytest

from abfarm import turnstile
from abfarm.config import Config
from abfarm.mailbox import dotted_variants
from abfarm.signup import random_password
from abfarm.store import AccountStore


class FakeMouse:
    def __init__(self, page):
        self.page = page

    async def move(self, x, y):
        self.page.events.append(("move", round(x), round(y)))

    async def click(self, x, y):
        self.page.events.append(("click", round(x), round(y)))
        if self.page.solves_on_click:
            self.page.token = "0.SOLVED-token"


class FakePage:
    """Minimal stand-in for a Playwright page holding a Turnstile widget."""

    def __init__(self, token=None, box=(100, 400, 430, 70), solves_on_click=False,
                 has_frame=True):
        self.token = token
        self.box = box
        self.solves_on_click = solves_on_click
        self.has_frame = has_frame
        self.events = []
        self.mouse = FakeMouse(self)

    async def evaluate(self, script, arg=None):
        if "sel" in script and "el.value" in script:
            return self.token if (self.box or self.token) else None
        if "getBoundingClientRect" in script and "shadowRoot" in script:
            return self.has_frame
        if "getBoundingClientRect" in script:
            return list(self.box) if self.box else None
        return None


def run(coro):
    return asyncio.run(coro)


def test_token_already_present():
    page = FakePage(token="0.READY")
    res = run(turnstile.solve(page, timeout_s=1, list_attempts=1))
    assert res.state == "solved" and res.token == "0.READY"
    assert not page.events


def test_click_mints_token():
    page = FakePage(solves_on_click=True)
    res = run(turnstile.solve(page, timeout_s=6, list_attempts=2))
    assert res.state == "solved"
    clicks = [e for e in page.events if e[0] == "click"]
    assert clicks, "solver must click the checkbox when the widget is interactive"
    x, y = clicks[0][1], clicks[0][2]
    assert 100 <= x <= 140, "click lands inside the checkbox area"
    assert 400 <= y <= 470


def test_missing_widget():
    page = FakePage(box=None)
    res = run(turnstile.solve(page, timeout_s=1, list_attempts=1))
    assert res.state == "missing" and res.token is None


def test_empty_widget_reports_state():
    page = FakePage(has_frame=False, solves_on_click=False)
    res = run(turnstile.solve(page, timeout_s=4, list_attempts=1))
    assert res.state == "empty-widget"


def test_dotted_variants_keep_address():
    base = "someone@gmail.com"
    alias = dotted_variants("someone")
    assert "." in alias
    assert alias.replace(".", "") == "someone"
    assert "@" not in alias


def test_password_shape():
    pw = random_password()
    assert len(pw) >= 12 and pw[0].isalpha()


def test_store_roundtrip(tmp_path):
    from abfarm.signup import Account
    store = AccountStore(tmp_path / "accounts.jsonl")
    acc = Account("a@b.c", "pw", "sk-abc", "proj_1", "2026-01-01T00:00:00Z")
    store.add(acc)
    store.add(Account("d@e.f", "pw", "sk-def", "proj_2", "2026-01-01T00:00:00Z"))
    assert store.emails() == {"a@b.c", "d@e.f"}
    assert store.keys() == ["sk-abc", "sk-def"]
    line = json.loads((tmp_path / "accounts.jsonl").read_text().splitlines()[0])
    assert line["api_key"] == "sk-abc"


def test_config_urls():
    cfg = Config(base_url="https://example.com/")
    assert cfg.signup_url == "https://example.com/sign-up"
    assert cfg.console_url == "https://example.com/console"