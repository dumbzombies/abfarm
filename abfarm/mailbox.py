"""Mailbox backends: where the verification code comes from.

Three providers ship in the box:

* ``ManualMailbox``  – you paste the code (or point at a file). Useful for smoke tests.
* ``ImapMailbox``    – reads a real inbox over IMAP. With Gmail you can mint a new
  dotted alias per signup for free (``user+a@``/``us.er@`` all land in the same
  mailbox), which is what keeps WorkOS Radar from flagging the address as
  disposable.
* ``VoidashMailbox`` – throwaway API inbox. Cheap and instant, but disposable
  domains are exactly what ``auth_policy_denied`` is about; expect blocks.
"""
from __future__ import annotations

import email
import imaplib
import json
import random
import re
import string
import time
import urllib.request
from email.header import decode_header
from pathlib import Path
from typing import Protocol

CODE_RE = re.compile(r"\b(\d{6})\b")


class Mailbox(Protocol):
    address: str

    def wait_code(self, timeout: int = 180, since_ts: float | None = None) -> str | None: ...


class ManualMailbox:
    """Reads the code from a file (polled) or stdin."""

    def __init__(self, address: str, code_file: str | Path | None = None) -> None:
        self.address = address
        self.code_file = Path(code_file) if code_file else None

    def wait_code(self, timeout: int = 180, since_ts: float | None = None) -> str | None:
        if not self.code_file:
            return input(f"[{self.address}] verification code: ").strip() or None
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.code_file.exists():
                code = self.code_file.read_text().strip()
                if code:
                    self.code_file.unlink(missing_ok=True)
                    return code
            time.sleep(2)
        return None


def dotted_variants(local: str, rng: random.Random | None = None) -> str:
    """Insert dots into a Gmail local part. Dots are ignored by Gmail delivery."""
    rng = rng or random
    chars = list(local)
    positions = list(range(1, len(chars)))
    rng.shuffle(positions)
    for p in positions[: rng.randint(1, 4)]:
        chars.insert(p, ".")
    # collapse accidental doubles
    out = re.sub(r"\.+", ".", "".join(chars)).strip(".")
    return out


class ImapMailbox:
    """IMAP reader with per-signup Gmail aliasing."""

    def __init__(self, host: str, user: str, password: str, folder: str = "INBOX",
                 alias_seed: str | None = None, sender_filter: str | None = None) -> None:
        self.host, self.user, self.password = host, user, password
        self.folder = folder
        self.sender_filter = sender_filter
        self._conn: imaplib.IMAP4_SSL | None = None
        if alias_seed is None:
            alias_seed = user.split("@")[0]
        local, _, domain = user.partition("@")
        self.address = f"{dotted_variants(alias_seed)}@{domain or 'gmail.com'}"
        self._seed_local = local

    def _connect(self) -> imaplib.IMAP4_SSL:
        if self._conn is None:
            conn = imaplib.IMAP4_SSL(self.host)
            conn.login(self.user, self.password)
            conn.select(self.folder)
            self._conn = conn
        return self._conn

    @staticmethod
    def _body_text(msg: email.message.Message) -> str:
        if msg.is_multipart():
            parts = []
            for part in msg.walk():
                if part.get_content_type() in ("text/plain", "text/html"):
                    payload = part.get_payload(decode=True) or b""
                    parts.append(payload.decode(part.get_content_charset() or "utf-8", "replace"))
            return "\n".join(parts)
        payload = msg.get_payload(decode=True) or b""
        return payload.decode(msg.get_content_charset() or "utf-8", "replace")

    def wait_code(self, timeout: int = 180, since_ts: float | None = None) -> str | None:
        conn = self._connect()
        deadline = time.time() + timeout
        while time.time() < deadline:
            typ, data = conn.search(None, "UNSEEN")
            ids = data[0].split() if data and data[0] else []
            for msg_id in reversed(ids):
                typ, raw = conn.fetch(msg_id, "(RFC822)")
                if typ != "OK" or not raw or not isinstance(raw[0], tuple):
                    continue
                msg = email.message_from_bytes(raw[0][1])
                subject = "".join(
                    p.decode(enc or "utf-8", "replace") if isinstance(p, bytes) else p
                    for p, enc in decode_header(msg.get("Subject", ""))
                )
                body = subject + "\n" + self._body_text(msg)
                if self.address.lower() not in body.lower() and self.address.lower() not in str(msg.get("To", "")).lower():
                    continue
                if self.sender_filter and self.sender_filter not in str(msg.get("From", "")):
                    continue
                m = CODE_RE.search(self._body_text(msg) or subject)
                if m:
                    try:
                        conn.store(msg_id, "+FLAGS", "\\Seen")
                    except imaplib.IMAP4.error:
                        pass
                    return m.group(1)
            time.sleep(5)
        return None

    def close(self) -> None:
        if self._conn:
            try:
                self._conn.logout()
            except imaplib.IMAP4.error:
                pass
            self._conn = None


class VoidashMailbox:
    """api.voidash.com throwaway inboxes."""

    API = "https://api.voidash.com/api/v1"

    def __init__(self, domain: str = "voidash.cyou") -> None:
        req = urllib.request.Request(
            f"{self.API}/inboxes",
            data=json.dumps({"domain": domain}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode())
        if isinstance(data.get("data"), dict):
            data = data["data"]
        self.address: str = data["address"]
        self._key: str = data["session_key"]

    def wait_code(self, timeout: int = 180, since_ts: float | None = None) -> str | None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                req = urllib.request.Request(
                    f"{self.API}/messages",
                    headers={"Authorization": "Bearer " + self._key},
                )
                with urllib.request.urlopen(req, timeout=30) as r:
                    payload = json.loads(r.read().decode())
                msgs = payload.get("messages") or payload.get("data") or []
                for m in msgs:
                    m = CODE_RE.search(json.dumps(m))
                    if m:
                        return m.group(1)
            except Exception:
                pass
            time.sleep(5)
        return None


def build_mailbox(cfg, address: str | None = None, code_file: str | None = None) -> Mailbox:
    """Factory used by the CLI."""
    if cfg.mailbox == "imap":
        if not (cfg.imap_user and cfg.imap_pass):
            raise SystemExit("imap mailbox needs ABFARM_IMAP_USER / ABFARM_IMAP_PASS")
        return ImapMailbox(cfg.imap_host, cfg.imap_user, cfg.imap_pass,
                           alias_seed=address, sender_filter="abliteration")
    if cfg.mailbox == "voidash":
        return VoidashMailbox(cfg.voidash_domain)
    if not address:
        raise SystemExit("manual mailbox needs --email")
    return ManualMailbox(address, code_file=code_file)


_ = string  # keep import surface stable for downstream tooling