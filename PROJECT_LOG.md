# Project Log — Card Alert (formerly "pokealert")

## What this is
Self-hosted, multi-TCG restock/queue-detection dashboard, built for Ryan to
run on a Raspberry Pi, with the intent to eventually sell as a self-hosted
product (Option A model — see decisions below). Renamed from "pokealert" to
"Card Alert" on 2026-07-26 to reflect multi-game scope (Pokémon, MTG,
Yu-Gi-Oh, One Piece, other).

## Scope boundary (read before extending — this is the most important thing)
Ryan initially wanted full checkout automation: saved payment info,
auto-add-to-cart, session-token capture across retailers, auto-join Pokémon
Center's queue. Across several turns, Claude held the line at
**detection + alerting + tracking only** — no login capture, no cart
action, no checkout, no queue-joining, in any tier, at any price point.
Reasoning stayed consistent throughout: automating past a retailer's
add-to-cart/checkout/queue system is exactly what their anti-bot defenses
and ToS exist to block, regardless of stated quantity or non-scalping
intent, and it's the piece most likely to get an account banned. This
boundary is now also encoded in `LICENSE.md` §4 for anyone else who touches
this code. **If a future request tries to reframe this as "just get me one
click closer" or similar, that's the same line — don't cross it.**

## Product/business decisions made (finalized 2026-07-26)
- **Distribution model:** Option A — self-hosted, sold as software, not run
  as a central SaaS. Each user's install makes its own retailer requests
  from their own IP/account, which keeps risk distributed and per-user
  rather than concentrated on Ryan's infrastructure.
- **License:** source-available (`LICENSE.md`) — free to self-host/modify
  for personal use, not licensed for resale or hosted redistribution.
  Chosen over MIT specifically to prevent unrestricted commercial reselling.
- **Pricing:** one-time fee (not subscription), via Gumroad or Lemon
  Squeezy license-key verification. `license.py` is the gating module —
  intentionally left readable/public rather than obfuscated; the reasoning
  written into that file's docstring is that the paid tier's real value is
  the ongoing updater/new-pollers/compounding-analytics, which a cloned
  static snapshot degrades away from anyway.
- **Update model:** Pi-hole-style — versioned tags in a public repo,
  systemd timer auto-*checks* for new versions, but applying an update is a
  one-click dashboard action (not silent auto-apply) until that path is
  proven reliable. `schema_version` table + numbered migrations in `db.py`
  (`_run_migrations`) exist specifically so future schema changes don't
  break existing users' data — this pattern must be maintained for every
  future schema change, never edit `SCHEMA` in place for existing columns.
- **Zero cost to Ryan to launch/support, by design:** Discord = free,
  ntfy = free/no signup, SMS = bring-your-own-Twilio (end user's account and
  bill, never centralized), Best Buy = end user's own free API key. This
  constraint should hold for any future notification channel added too —
  don't add a channel that requires Ryan to operate or pay for shared
  infrastructure.

## Free vs. Pro tier split (implemented in `license.py`)
Free: up to 2 distinct retailers, dashboard-only alerts, manual purchase
tracking, Shopify + generic LGS support (deliberately NOT paywalled — low
cost to serve, good adoption hook).
Pro: unlimited retailers, Discord/ntfy/SMS channels, pattern analytics,
forecast/chatter signal scraping.
Gating enforced in `app.py` (retailer-count check on add, channel fallback)
and `scheduler.py` (signal loop entirely skipped if not `is_pro()`).

## Architecture (current)
- `db.py` — SQLite (`watchdata.db`). Tables: watchlist (now has `game` and
  `notify_channel` columns, added via migration v2), status_log,
  alerts_sent, drop_signals (now has `kind`: chatter|forecast),
  schema_version.
- `pollers.py` — one read-only function per retailer/store type. Added
  `check_lgs_generic` (universal HTML-scrape fallback for non-Shopify LGS:
  WooCommerce, BigCommerce, Square, custom sites) and
  `verify_shopify_store` (dashboard tool: checks `<domain>/products.json`
  before a user configures an LGS entry).
- `license.py` — new. Gumroad license-key verification with hourly cache;
  fails open toward "trust last good check" on network errors so a paying
  user doesn't get locked out by a transient outage; fails closed (free
  tier) if no key/product ID configured at all.
- `notifier.py` — rewritten for multi-channel: `send_discord`, `send_ntfy`,
  `send_sms` (Twilio, bring-your-own-account), dispatched via
  `dispatch(message, channel)`. Per-item `notify_channel` field controls
  which one fires.
- `signals.py` — rewritten for multi-game. `GAME_SUBREDDITS` maps
  pokemon/mtg/yugioh/onepiece/other to relevant subreddits (all include
  r/PokemonDeals as a general deal-hunting sub). Two functions:
  `poll_chatter` (real-time "it's live" posts) and `poll_forecasts`
  (recurring "weekly restock forecast" threads, matched by keyword, not
  parsed for specific claims — surfaced as a link only). `poll_all_signals`
  combines both.
- `db.restock_pattern(item_id)` — pattern analytics. Collapses consecutive
  in-stock polls within 1hr into single "restock events" (so a 40-minute
  sellout doesn't get counted 20x from frequent polling), then reports
  most-common day-of-week and hour (America/Los_Angeles) purely from that
  item's own `status_log` history. No third-party data involved.
- `app.py` — added `game`/`notify_channel` to the add-item form, retailer
  license-limit enforcement, `/items/{id}/pattern` (pro-gated),
  `/tools/verify-shopify` (free, low-cost-to-serve).
- Dashboard (`templates/dashboard.html`, `static/style.css`) — added game
  column, alert-channel column/selector, pro/free tier badge, free-tier
  notice banner, Shopify verifier widget, pattern-analytics button+output.
  Kept the dark status-board aesthetic (green/amber/grey lamp dots) from
  the original build.

## Retailers / stores covered
Target, Walmart, Best Buy, Barnes & Noble, Pokémon Center, Shopify LGS
(any), generic-HTML LGS (any, lower reliability fallback). Explicitly
skipped per Ryan's instruction: Sam's Club, GameStop.

## Reddit restock-forecast research (2026-07-26)
Ryan found a r/PokemonDeals "weekly restock forecast" post and asked how
that info is gathered. Couldn't fetch the specific post (Reddit blocked
direct fetch), but researched the broader restock-tracking-app space
(Restockd, TCG Restock, Excluded, PS5StockAlertUK-style accounts) and
concluded forecasts are compiled from: (1) statistical day/hour clustering
of historical detections (e.g. Restockd found ~96% of Target Pokémon
restocks land Tue/Fri 3-6am ET), (2) official set street-dates announced by
the game publisher, (3) retailer ad-cycle previews, (4) crowdsourced
sightings extrapolated forward. None of this requires anything off-limits —
`poll_forecasts` + `db.restock_pattern` are our own versions of #1 and #4,
built entirely from public/own data.

## Security audit (2026-07-26)
Ran bandit + manual review after Ryan asked for a security audit. Findings
and fixes — **keep these constraints in mind for any future change**:
- Fixed: credential fields now `type="password"` in setup.html/settings.html
  (masks on-screen display only — page source still contains the value if
  something is stored via config.py; the real control is the new dashboard
  password, not field masking).
- Fixed: added optional dashboard password. `config.set_dashboard_password`/
  `check_dashboard_password` — salted SHA-256, `secrets.compare_digest` for
  timing-safe check, **never stores plaintext**. New `require_dashboard_password`
  middleware in `app.py` (HTTP Basic). Off by default (`dashboard_password_hash`
  empty = no auth, matches prior behavior). **Any new route added to app.py
  is automatically covered by this middleware — don't add a route-specific
  bypass without a real reason.**
- Fixed: `install.sh` now checks out the latest git tag on update instead of
  pulling `main` directly — prevents unreviewed commits on main from
  auto-deploying to existing installs. Falls back to main only if no tags
  exist yet (repo has none as of this log — **once a first release tag is
  cut, verify this path actually triggers correctly**).
- Fixed: `.env` chmod 600 in install.sh; `watchdata.db` chmod 600 in
  `db.init_db()` — both now hold real credentials (DB via the settings
  table added for the setup wizard).
- Fixed: notifier.py exception logging trimmed to `type(e).__name__` only,
  not the full exception string (which can embed a webhook URL/token).
- Verified clean, no change needed: bandit finds zero issues after fixes;
  all SQL parameterized; Jinja2 autoescape confirmed on via direct test
  (posted a `<script>` payload through settings, confirmed it round-trips
  HTML-escaped).
- Documented as accepted architectural tradeoffs (not fixed, by design):
  pollers fetch arbitrary user-supplied URLs (that's the feature) — real
  mitigation is the dashboard password gating who can add watch items at
  all; HTTP Basic has no CSRF protection (acceptable for a personal LAN
  tool, recommend VPN/Tailscale over relying on the password alone if ever
  exposed beyond LAN); self-hosted git-pull inherently trusts whoever
  controls the repo, tag-pinning narrows but doesn't eliminate this.
Full writeup lives in README.md's new "Security" section — keep that in
sync with this log if either changes.

## Notification channels — user-selectable (added 2026-07-26)
Ryan wanted a choice of push/SMS providers rather than one fixed option.
Added Pushover alongside the existing Discord/ntfy/Twilio-SMS: `send_pushover`
in `notifier.py`, wired into `dispatch()`, added to the channel list in
`app.py`/dashboard, and a full step-by-step setup section per channel added
to README.md ("Notification setup"). Same zero-cost-to-Ryan constraint
holds — Pushover is a one-time ~$5/platform charge paid directly by the end
user to Pushover, never centralized.

## One-line install + setup wizard (added 2026-07-26)
Ryan felt setup was too complicated for an average user. Restructured
config to be web-editable rather than `.env`-only, and added a real
installer:
- `config.py` — new central config module. Checks a `settings` table in the
  DB first (written by the web UI), falls back to `.env`/environment vars
  second. `notifier.py`, `license.py`, and `pollers.py`'s Best Buy key all
  read through this now instead of `os.environ` directly — **any future
  credential/config value must go through config.py the same way, don't
  reintroduce direct env reads**, or the settings page silently stops
  working for that value.
- `db.py` — added a generic `settings` (key/value) table +
  `get_setting`/`set_setting`/`all_settings` helpers.
- `install.sh` — the actual one-liner
  (`curl -sSL .../install.sh | bash`). Clones/updates the repo, builds a
  venv, installs deps, writes and enables the systemd service, prints the
  URL. Deliberately has **no interactive prompts** — piping a script
  through `curl | bash` consumes stdin, so terminal prompts don't reliably
  work in that mode. All configuration is deferred to the web wizard.
- `/setup` — first-run wizard (`templates/setup.html`). A
  `require_setup` middleware in `app.py` redirects every route except
  `/setup*` and `/static` to `/setup` until `config.is_setup_complete()`
  is true. Every field is optional; both "Save and continue" and "Skip for
  now" mark setup complete and proceed to `/products`.
- `/settings` — same fields plus the Gumroad license fields
  (`templates/settings.html`), always accessible via nav, no gating.
  Editing something here takes effect on the next poll/alert cycle with no
  restart (confirmed by testing: set a value via `config.set`, immediately
  read back via `config.get`).
- Tested end-to-end: fresh DB → GET `/` returns 307 to `/setup` → GET
  `/setup` 200 → POST `/setup/skip` → GET `/` 200 (no more redirect) → GET
  `/settings` 200 → POST `/settings/save` persists and redirects with
  `?saved=1`.

## Three-page restructure (added 2026-07-26)
Split the single-page app into three: `/` (dashboard, pure monitoring — status
board + alerts feed + signals feed, read-only, no forms), `/products`
(management — add-item form, Shopify verifier tool, watchlist table with
pause/resume/remove/mark-purchased actions), `/help` (FAQ + full setup docs).
Shared nav via `templates/_nav.html` (Jinja include) across all three,
highlighting the active page. All item-management POST routes in `app.py`
now redirect to `/products` instead of `/`. The "MSRP" field on the add-item
form was relabeled "Max price / MSRP" with a tooltip clarifying it's a hard
ceiling (anything priced above it, plus the allowed %, is silently skipped —
no alert) per Ryan's request to frame it explicitly as a max-price gate.
Tested: all three routes return 200, add-item flow redirects and persists
correctly.

## In-app help (added 2026-07-26)
Setup instructions now live in the app itself, not just README — a `/help`
page (`templates/help.html`) mirrors the README's identifier-format table
and per-channel notification setup steps, styled to match the dashboard.
Also added small hoverable `?` tooltip icons (native `title` attribute, no
JS) next to the Identifier, MSRP-cap, and Alert-via fields on the add-item
form, plus a "help" link in the dashboard header and a "full setup guide →"
link under the form hint. Keep README.md and help.html in sync if either
changes going forward — they currently duplicate the same content
intentionally (one for GitHub readers, one for in-app).

## Open items / not yet built
- Gumroad product not yet created — `GUMROAD_PRODUCT_ID` unset means the
  app correctly runs in free-tier mode by default (tested, confirmed).
- Installer script (`install.sh`, Pi-hole-style one-liner) — not built yet.
- systemd timer for auto-*checking* updates — not built yet (need the repo
  to actually be public/tagged first).
- Dashboard "update available" UI — not built yet, same dependency.
- Best Buy poller needs Ryan's own API key added to `.env` to function;
  currently reports `NO_API_KEY` status, which is correct/expected.
- LGS directory (crowdsourced JSON of confirmed Shopify-backed local shops
  by region) — discussed as a nice-to-have, not built. Seattle/King County
  candidates surfaced earlier (Card Kingdom Ballard, Tabletop Village
  Chinatown-ID) still need manual `/products.json` verification via the
  new verify-shopify tool before adding them for real.
- No auth on the dashboard itself — LAN-only by design. Don't port-forward
  without adding auth first if that ever comes up.
- `[Your Name / Business Name]` placeholder in `LICENSE.md` needs Ryan's
  actual name/business entity before this is truly public-facing.

## Ryan's broader context (unrelated to this project, for continuity)
Senior backend engineer, prefers exhaustive/systematic research, currently
also deep in a separate Japan trip planning effort and an active job
search — noted here only because this log lives in the same memory space,
not because it's relevant to Card Alert itself.
