# abfarm

Automated account provisioning for [abliteration.ai](https://abliteration.ai) — a clean-room
rewrite of the abandoned `abliteration-farm` script.

The old repo did two things this one refuses to do: it shipped a hardcoded referral code
(`ref_yrd8gnW-d4ir`) so every account it made credited a stranger, and it delegated the
Cloudflare Turnstile step to a separate paid solver. There is no referral handling here at
all, and the captcha is solved by the page's own widget — click the checkbox, take the token,
spend it in the same session.

## What it does

For each account: fresh mailbox alias → signup form (email → password) → Turnstile token →
email verification code → console → project API key. Results land in
`out/accounts.jsonl` (mode 0600) as `{email, password, api_key, project_id, created_at}`.

## Requirements

- Python ≥ 3.10 and Playwright
- One browser backend:
  - **cloak** (default) — [CloakBrowser](https://cloakbrowser.dev) Pro binary. Best pass rate;
    handles fingerprinting and humanised input. `pip install cloakbrowser`
  - **camoufox** — `pip install "camoufox[geoip]"`. Headless Firefox is detected more often;
    expect widget retries. Needs GTK libraries on Linux.
  - **chromium** — plain Playwright Chromium, debugging only.
- A mailbox that isn't flagged as disposable (see below)

## Install

```bash
git clone <this-repo> && cd abfarm
python -m venv .venv && . .venv/bin/activate
pip install -e .            # add .[cloak] or .[camoufox] for the browser backend
playwright install chromium # only needed for the chromium backend
```

## Use

```bash
# 1. sanity-check the site's markup and your browser stack (no account is created)
abfarm doctor

# 2. one account, Gmail dot-trick alias over IMAP
export ABFARM_IMAP_USER=you@gmail.com
export ABFARM_IMAP_PASS=<gmail app password>
abfarm run --mailbox imap --count 3

# 3. manual mode (you paste codes; handy for a smoke test)
abfarm run --email you+tag@gmail.com --mailbox manual

# 4. through a residential exit
abfarm run --mailbox imap --proxy http://127.0.0.1:8080
```

Useful flags: `--headful`, `--no-humanize`, `--out DIR`, `--base-url`, `--password`.

## Mailboxes

| provider | flag | notes |
|---|---|---|
| Gmail dot-trick over IMAP | `--mailbox imap` | Dots in the local part are ignored by Gmail, so `a.b.c@gmail.com` is a fresh-looking address that still delivers to you. **This is the only provider that consistently survives signup.** |
| Manual | `--mailbox manual` | You paste the code (or drop it in `--code-file` for scripting). |
| Voidash | `--mailbox voidash` | Instant throwaway inbox... and a fast route to `auth_policy_denied`, because WorkOS Radar blocks disposable domains. |

## The Turnstile step

`abfarm/turnstile.py` talks to the real widget: it polls
`input[name="cf-turnstile-response"]`, clicks the checkbox at the widget's left edge when
Cloudflare asks for an interaction, and returns the token. No OCR, no slider, no third-party
service — the widget the site renders is the widget that mints the token.

It reports one of four states, which map straight onto what to fix:

| state | meaning | fix |
|---|---|---|
| `solved` | token minted | — |
| `no-token` | widget drew itself but never issued a token | burned exit IP or a detected browser. Rotate the proxy, use `--browser cloak`. |
| `empty-widget` | the widget box exists but the challenge iframe never mounted | Turnstile rate limited this session; wait a few minutes and retry. |
| `missing` | no widget in the DOM | the page changed; run `abfarm doctor`. |

Verified working configuration: CloakBrowser headless + residential exit + humanised typing.
Camoufox headless produced `empty-widget` on every attempt from the same IP.

## Failure modes

- **`403 auth_policy_denied`** — WorkOS Radar refused the attempt. Almost always the email
  domain: disposable inboxes are blocked outright. Switch to a real mailbox.
- **`no code form`** — the signup was accepted but the app didn't advance; usually a stale
  `workspace_setup_pending` user. Log in once in a browser and finish onboarding.
- **`no project id in console session`** — workspace provisioning is slow; the code polls for
  two minutes. Retry with `--count 1` before assuming breakage.

## Tests

```bash
pip install pytest && pytest -q     # 8 unit tests, no browser or network needed
```

## Scope

Accounts are created against a service you sign up to yourself; you're responsible for the
ToS of that service and for what you do with the keys. Nothing here defeats a captcha
cryptographically — it clicks the same checkbox a human would.