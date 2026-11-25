"""Runtime configuration for abfarm."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_BASE_URL = "https://abliteration.ai"


@dataclass
class Config:
    """Everything the farm needs, resolved from CLI flags and env vars."""

    base_url: str = DEFAULT_BASE_URL
    proxy: str | None = None
    browser: str = "camoufox"         # camoufox | cloak | chromium
    headless: bool = True
    humanize: bool = True
    timeout_s: int = 90
    turnstile_click_attempts: int = 3
    turnstile_wait_s: int = 45
    out_dir: Path = field(default_factory=lambda: Path("out"))
    mailbox: str = "manual"           # manual | imap | voidash
    imap_host: str = "imap.gmail.com"
    imap_user: str | None = None
    imap_pass: str | None = None
    voidash_domain: str = "voidash.cyou"
    rotate_cmd: str | None = None     # shell command run between retry attempts

    signup_url: str = field(init=False, default="")
    console_url: str = field(init=False, default="")

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        self.signup_url = self.base_url + "/sign-up"
        self.console_url = self.base_url + "/console"
        self.out_dir = Path(self.out_dir)

    @classmethod
    def from_env(cls, **overrides) -> "Config":
        cfg = cls(
            proxy=os.environ.get("ABFARM_PROXY") or None,
            browser=os.environ.get("ABFARM_BROWSER", "camoufox"),
            mailbox=os.environ.get("ABFARM_MAILBOX", "manual"),
            imap_user=os.environ.get("ABFARM_IMAP_USER"),
            imap_pass=os.environ.get("ABFARM_IMAP_PASS"),
            rotate_cmd=os.environ.get("ABFARM_ROTATE_CMD") or None,
        )
        for k, v in overrides.items():
            if v is not None:
                setattr(cfg, k, v)
        cfg.__post_init__()
        return cfg

    def api_key_file(self) -> Path:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        return self.out_dir / "accounts.jsonl"