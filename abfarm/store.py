"""Account persistence: one JSON object per line, secret keys included."""
from __future__ import annotations

import json
import os
from pathlib import Path

from .signup import Account


class AccountStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def _existing(self) -> set[str]:
        if not self.path.exists():
            return set()
        emails = set()
        for line in self.path.read_text().splitlines():
            try:
                emails.add(json.loads(line)["email"])
            except Exception:
                continue
        return emails

    def add(self, account: Account) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as fh:
            fh.write(json.dumps(account.as_dict()) + "\n")
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def emails(self) -> set[str]:
        return self._existing()

    def keys(self) -> list[str]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text().splitlines():
            try:
                out.append(json.loads(line)["api_key"])
            except Exception:
                continue
        return out