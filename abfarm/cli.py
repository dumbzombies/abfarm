"""CLI: `abfarm run`, `abfarm doctor`."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .config import Config
from .mailbox import ImapMailbox, build_mailbox, dotted_variants
from .signup import SignupError, run_one
from .store import AccountStore


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="abfarm", description="Abliteration account farm")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--browser", choices=["camoufox", "cloak", "chromium"], default=None,
                        help="default: camoufox (or ABFARM_BROWSER)")
        sp.add_argument("--proxy", default=None, help="http://host:port or socks5://host:port")
        sp.add_argument("--headful", action="store_true")
        sp.add_argument("--no-humanize", action="store_true")
        sp.add_argument("--out", default="out", help="output directory for accounts.jsonl")
        sp.add_argument("--base-url", default=None)

    run = sub.add_parser("run", help="create accounts")
    common(run)
    run.add_argument("--count", type=int, default=1)
    run.add_argument("--mailbox", choices=["manual", "imap", "voidash"], default=None)
    run.add_argument("--email", default=None, help="address for --mailbox manual")
    run.add_argument("--code-file", default=None, help="manual mailbox: file the code is dropped into")
    run.add_argument("--password", default=None)

    doc = sub.add_parser("doctor", help="check page markup + browser stack")
    common(doc)
    return p


async def _doctor(cfg: Config) -> int:
    from . import turnstile
    from .browsers import BrowserSession

    async with BrowserSession(cfg) as page:
        await page.goto(cfg.signup_url, wait_until="domcontentloaded", timeout=cfg.timeout_s * 1000)
        await page.wait_for_selector('input[name="email"]', timeout=30000)
        html = await page.content()
        print("signup page:", page.url)
        print("email input:", 'name="email"' in html)
        print("sitekey present:", "0x4AAAAAAEcO2qYYBE_ztENL" in html)
        await page.fill('input[name="email"]', "doctor@example.com")
        await page.click("button.auth-primary-action")
        try:
            await page.wait_for_selector('input[name="password"]', timeout=30000)
            print("password step: ok")
        except Exception:
            print("password step: MISSING")
        await asyncio.sleep(4)
        box = await turnstile.widget_box(page)
        print("widget box:", box)
        if box:
            await page.mouse.click(box[0] + 25, box[1] + box[3] / 2)
            tok = None
            for _ in range(40):
                tok = await turnstile.read_token(page)
                if tok:
                    break
                await asyncio.sleep(1)
            print("turnstile token:", "ok" if tok else "FAILED")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    cfg = Config.from_env(
        browser=args.browser,
        proxy=args.proxy,
        headless=(not args.headful) if args.headful else None,
        humanize=(None if not args.no_humanize else False),
        out_dir=(Path(args.out) if args.out else None),
        base_url=args.base_url,
        mailbox=getattr(args, "mailbox", None),
    )
    if args.no_humanize:
        cfg.humanize = False

    if args.cmd == "doctor":
        return asyncio.run(_doctor(cfg))

    store = AccountStore(cfg.api_key_file())
    failures = 0
    for i in range(args.count):
        print(f"[{i + 1}/{args.count}] mailbox={cfg.mailbox}")
        try:
            if cfg.mailbox == "imap":
                from .mailbox import dotted_variants as dv
                import random, string
                seed = "".join(random.choices(string.ascii_lowercase, k=8))
                box = ImapMailbox(cfg.imap_host, cfg.imap_user or "", cfg.imap_pass or "",
                                  alias_seed=seed, sender_filter="abliteration")
            else:
                box = build_mailbox(cfg, address=args.email, code_file=args.code_file)
            print("  address:", box.address)
            account = asyncio.run(run_one(cfg, box, args.password))
            store.add(account)
            print("  OK key:", account.api_key[:12] + "..." + account.api_key[-4:])
        except SignupError as exc:
            failures += 1
            print("  FAILED:", exc)
        except KeyboardInterrupt:
            break
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print("  ERROR:", type(exc).__name__, exc)
    print(json.dumps({"saved": len(store.keys()), "failures": failures}))
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())