# Card Alert

A self-hosted restock/queue-detection dashboard for trading card games
(Pokémon, Magic, Yu-Gi-Oh, One Piece, or anything else) across major
retailers and local game stores. Built to run on a Raspberry Pi.

Free. Every feature, no license, no tiers. If it's useful to you,
donations are welcome, never required: https://ko-fi.com/ryanthedev

## What this does
- Watches Target, Walmart, Best Buy, Barnes & Noble, Amazon (first-party
  listings only, see below), Pokémon Center (queue + stock), and any local
  game store, Shopify-backed or otherwise.
- Ignores restocks priced more than X% over MSRP (set per item).
- Tracks a target quantity per product. Log purchases manually and watch it
  count down to zero.
- Surfaces subreddit restock chatter and community "weekly forecast"
  threads for the games you're tracking.
- Historical pattern analytics: "this SKU has restocked at Target 4 times,
  all Tue/Fri mornings," computed from your own polling history.
- Sends alerts to any combination of Discord, ntfy, Pushover, and SMS per
  item (checkboxes, not an either/or). It always shows on the Dashboard too,
  regardless of what else is checked.

### Amazon: first-party listings only
The Amazon poller only counts a restock as real when the listing says
"Ships from and sold by Amazon.com," never a third-party marketplace
seller. Third-party listings on hot TCG products are almost always marked
up well above MSRP, so those get filtered out instead of alerted on.
Amazon also changes its page structure and fights scraping harder than any
other retailer here, so this is the poller most likely to occasionally
need a fix.

## What this deliberately does not do
No login capture, no cart automation, no checkout automation, for any
price, ever. See the header comment in `pollers.py` and `LICENSE.md`
section 4. This is a structural decision, not a missing feature.
Automating past a retailer's cart, checkout, or queue system is exactly
what their anti-bot defenses and Terms of Service exist to stop, and it's
the piece most likely to get an account banned, regardless of stated
intent or quantity.

## Cost to run: $0
- Discord alerts: free.
- ntfy push alerts: free, no signup (ntfy.sh is public and open source).
- Pushover: one-time ~$5 per platform, paid directly to Pushover by you.
- SMS alerts: uses **your own** Twilio account. Twilio charges you
  fractions of a cent per text plus about $1/month for a number. This
  project never centralizes or touches that billing.
- Best Buy polling needs a free API key from developer.bestbuy.com.
- Card Alert itself: free, no license key, no paid tier.

## Notification setup

Easiest path: use the setup wizard on first visit, or the **Settings**
page any time after. Both let you paste these credentials straight into
the browser, no file editing or restart required. The steps below cover
the same ground, for reference or if you'd rather configure through
`.env`.

### Discord (free, always available)
1. In your Discord server: Server Settings → Integrations → Webhooks → New Webhook.
2. Pick the channel it should post to, copy the Webhook URL.
3. Set `DISCORD_WEBHOOK_URL` in `.env`.

### ntfy (free, no signup)
1. Install the ntfy app ([iOS](https://apps.apple.com/app/ntfy/id1625396347) / [Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy)), or just use a browser.
2. In the app, subscribe to a topic name you make up. Treat it like a
   password, something unguessable, e.g. `cardalert-yourname-x92q7`.
3. Set `NTFY_TOPIC` in `.env` to that same name (and `NTFY_SERVER` if
   you're self-hosting ntfy instead of using the public ntfy.sh).

No account, no cost, ever.

### Pushover (one-time ~$5 per platform, paid to Pushover directly)
1. Create a free account at [pushover.net](https://pushover.net), install
   the app on your phone.
2. On your account page, copy your **User Key**.
3. Create an "Application" (Pushover requires this to issue an API
   token). Name it anything, e.g. "Card Alert," and copy the **API Token**.
4. Set `PUSHOVER_USER_KEY` and `PUSHOVER_APP_TOKEN` in `.env`.
5. The $5 charge (per platform, one-time, not recurring) happens inside
   the Pushover app itself after a trial period. That's between you and
   Pushover; this project never touches that payment.

### SMS via Twilio (your own account, your own cost)
1. Create a free Twilio account at [twilio.com](https://www.twilio.com),
   which includes trial credit.
2. From the console dashboard, copy your **Account SID** and **Auth Token**.
3. Get a Twilio phone number (Phone Numbers → Buy a Number), a few
   dollars a month after the trial.
4. Set `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`
   (the Twilio number), and `TWILIO_TO_NUMBER` (your real phone, with
   country code, e.g. `+12065551234`) in `.env`.
5. Every text after that costs fractions of a cent, billed directly to
   your Twilio account. This project never sees or handles that billing.

## Setup

```bash
curl -sSL https://raw.githubusercontent.com/rgreen1207/cardalert/main/install.sh | bash
```

That's it. The script clones the repo, sets up a Python venv, installs
dependencies, creates and starts a systemd service, and prints a URL. Open
that URL in a browser on the same network and you'll land on a short
setup wizard for notification channels (Discord, ntfy, Pushover, SMS).
Every step is skippable. The dashboard works immediately either way, and
anything you skip can be added later from the **Settings** page.

Re-running the same install command later updates an existing install in
place instead of duplicating it. So does the "Check for updates" button on
the **Settings** page inside the app itself, which pulls the latest
release, reinstalls dependencies, and restarts the service, all with one
click. It relies on a narrowly-scoped sudo rule the installer sets up
(see Security below) to restart its own service; without that rule the
update still downloads, it just needs a manual restart to take effect.

### Manual setup (if you'd rather not run a piped script)
```bash
git clone https://github.com/rgreen1207/cardalert.git
cd cardalert
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # optional, same settings can be entered in-browser instead
uvicorn app:app --host 0.0.0.0 --port 8420
```

To run it permanently via systemd instead of the installer:
```bash
sudo cp cardalert.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now cardalert
```

## Adding items
Identifier format depends on retailer, shown as a hint on the dashboard's
add-item form:

| Retailer | Identifier format |
|---|---|
| `target` | numeric TCIN from the URL, e.g. `target.com/p/-/A-1011209279` → `1011209279` |
| `walmart` / `bn` / `pokemon_center` / `lgs_generic` | full product URL |
| `bestbuy` | SKU number |
| `amazon` | ASIN (10-char code) or full product URL, first-party listings only, see above |
| `lgs_shopify` | `shopdomain.com/products/product-handle` |

Not sure if your local shop runs Shopify? Use the "Check if a local shop
is Shopify-backed" tool on the dashboard. It hits `<domain>/products.json`
and tells you which poller type to use.

## Games supported
Pick a `game` per watchlist item: `pokemon`, `mtg`, `yugioh`, `onepiece`,
or `other`. This only affects which subreddits the signal scraper checks.
Every retailer poller already works for any product regardless of game.

## Pokémon Center schedule
Hardcoded to Monday through Thursday, 8am to 1pm PST, every 10 minutes,
skipped entirely outside that window. Change it in `scheduler.py` if you
need something different.

## Versioning
Current version: **v0.0.3**. Changes are logged in [`RELEASE.md`](RELEASE.md)
as they land, under an "Unreleased" heading; cutting a release means
moving that heading's entries under a new version number and tagging the
commit (`git tag v0.0.4`, etc.) — the in-app updater checks tags, so a
release isn't "real" for update purposes until it's tagged, not just
described in RELEASE.md.

## Testing & CI
```bash
pip install -r requirements-dev.txt
pytest
```
77 tests cover the data layer, config/settings, every retailer poller
(all HTTP calls mocked, so the suite never hits a real retailer site), the
notification dispatch logic, the Pokémon Center schedule window, and the
full web app via FastAPI's TestClient (setup flow, auth gating,
multi-channel alerts, currency persistence, the Discord test button). One
test is a regression guard that fails if any pro-tier or license language
ever comes back.

CI (`.github/workflows/ci.yml`) runs on every push or PR to `main`: the
test suite on Python 3.11 and 3.12, a bandit security scan, and shellcheck
on `install.sh`. All three have to pass before merging.

## Security

A security review (bandit static analysis plus manual review) found and
fixed the items below, and flags a couple of things that are
architectural tradeoffs rather than bugs.

**Fixed:**
- Credential fields (Discord webhook, API tokens) now render as masked
  `type="password"` inputs on Setup/Settings instead of plain text. This
  masks the on-screen display, not the page source: anyone with direct
  access to view-source or your browser's saved form data could still see
  the value. The real protection is the dashboard password below.
- Added an optional dashboard password (Settings → "Dashboard password").
  Stored as a salted SHA-256 hash, never plaintext, checked with a
  constant-time comparison. **Off by default.** Card Alert has no login
  out of the box, same as before, so set one if this device is reachable
  by anyone other than you.
- `install.sh` updates now pull the latest git **tag**, not `main`
  directly, so an existing install won't auto-pick-up an unreviewed commit.
- `.env` is chmod'd to `600` on install; `watchdata.db` is chmod'd to `600`
  on first run, since it now holds settings-page credentials too.
- Notification-send failures log only the exception type, not the full
  exception string, since that string can include the failing URL, which
  may embed a webhook path or token.
- The "Update now" button restarts the app via `sudo -n systemctl restart
  cardalert` in a detached subprocess. This only works non-interactively
  because `install.sh` sets up a sudoers rule scoped to exactly that one
  command for exactly this service and this user, nothing broader. All
  subprocess calls in `updater.py` use fixed argument lists with no
  `shell=True` and no user-supplied input, so there's no command
  injection surface even though this feature genuinely executes real
  commands (bandit-verified, see the CI job).

**Verified, not changed (already fine):**
- All SQL is parameterized (`?` placeholders), so there's no injection
  surface.
- Jinja2 autoescaping is on. Tested a `<script>` payload through the
  settings form and confirmed it comes back HTML-escaped, not executed.
- No `eval`, `exec`, or shell-string-formatting anywhere in the codebase.

**Architectural tradeoffs, not bugs, but worth understanding:**
- The retailer/LGS pollers fetch whatever URL you give them. That's the
  point; it's how stock-checking works. It also means anyone who can
  reach the app (once past the optional password) can make your Pi issue
  HTTP requests to arbitrary hosts. Setting a dashboard password is the
  mitigation. Don't port-forward this to the public internet without one.
- HTTP Basic auth (used for the dashboard password) has no CSRF
  protection of its own; browsers resend credentials automatically. That's
  a reasonable tradeoff for a personal LAN tool. If you expose this
  beyond your LAN, put it behind a VPN (e.g. Tailscale) rather than
  relying on the password alone.
- Self-hosted git-pull updates carry inherent supply-chain trust in
  whoever controls the repo. Pinning to tags (above) narrows this but
  doesn't eliminate it.

## Licensing
Source-available (see `LICENSE.md`): free to read, self-host, and modify
for your own use, and free of any license key or paid tier. Not licensed
for resale or hosted-service redistribution without permission.

## Support
Open a GitHub Issue. Retailer pages change their structure periodically,
so if a poller stops working, that's the most likely cause. Check Issues
for a fix before filing a new one.

## Closing the loop on checkout speed
The dashboard's job ends at "notify you." For the manual checkout step:
- Save your card in a password manager (1Password/Bitwarden). It
  autofills on mobile web and most retailer apps.
- Save your address in your phone's browser/OS autofill.
- Stay logged into retailer sites and apps on your phone so there's no
  login step between an alert and checkout.
