# Release Notes

All notable changes to Card Alert are logged here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/). Versions here are meant to
match git tags of the same name (`v0.0.3`, etc.) — the in-app updater
(Settings → "Check for updates") compares against tags, so cutting a
release means both: add an entry here, then tag the commit.

## [Unreleased]
### Changed
- Update-available text on Settings now shows on two lines
  ("current: X" / "new: Y") instead of one, and there's a bit more
  breathing room between the last settings panel and the "Save settings"
  button.

### Fixed
- **`install.sh` never actually restarted the service on update.**
  `sudo systemctl enable --now cardalert` was used for both fresh installs
  and updates. `--now` is equivalent to `systemctl start`, which is a
  no-op if the service is already running — so every time the installer
  was re-run to pick up a new version, it correctly pulled and wrote the
  new files to disk, but the already-running process kept executing the
  old code in memory, indefinitely. This explains a whole session's worth
  of "the fix isn't working" reports (an empty currency dropdown, 404s on
  `/settings/check-update` and `/settings/test-discord`, a missing
  version display) that all turned out to be the same root cause: the
  code on disk was current, the running process never was. Now calls
  `systemctl enable` and `systemctl restart` explicitly and separately, so
  a re-run of the installer always loads whatever it just pulled.
- SQLite could raise an uncaught "database is locked" error under real
  concurrency — the background scheduler writes to the database
  continuously in its own thread while web requests read and write on
  theirs, and the default rollback-journal mode plus no explicit busy
  timeout meant contention could surface as an uncaught 500 on `/products`
  or `/` (worse on a Pi's slower SD-card storage). Switched to WAL mode
  and gave every connection a 10-second busy timeout. Verified with a real
  multi-threaded stress test (four threads, 800 mixed read/write
  operations against the actual database), not just a mocked scenario —
  zero errors.
- WAL mode's `-wal`/`-shm` sidecar files were being created with the
  process's default (more permissive) permissions instead of matching the
  main database file's owner-only `600` — they briefly hold the same
  credential data during write activity. Now locked down every time a
  connection closes.
- "Check for updates" silently reported "Already up to date" on any
  failed request (a 404, a 500, anything), because the frontend never
  checked the HTTP status before reading the response body — FastAPI's
  default 404 body (`{"detail": "Not Found"}`) has neither an `error` nor
  an `update_available` field, so the code fell through to the "up to
  date" branch by default. Now checks response status first and shows a
  real error, including a hint that a 404 usually means the app itself
  needs updating to a version that has this feature at all.

## [0.0.3]
The "everything free, multi-retailer" release.

### Added
- **Multi-retailer products** — a single product can now have any number
  of retailers attached to it, each polled and alerted on independently.
  Adding Target and Amazon to the same product means either one going in
  stock triggers its own alert; one doesn't suppress or get confused with
  the other.
- **Product editing** — change name, game, quantity, price cap, and alert
  channels on an existing product, and add or remove individual retailer
  attachments, all without deleting and recreating it.
- **Multi-select alert channels** — checkboxes instead of a single choice,
  so one product can alert to Discord *and* ntfy *and* SMS at once.
- **Real currency conversion** — selecting a non-USD currency now actually
  converts displayed prices using live (cached, keyless) exchange rates,
  rather than just swapping the currency symbol on the same USD number.
  Entered prices convert back to USD for storage, so the underlying
  price-cap comparison logic always compares like currencies.
- **Discord @mentions** — optionally mention a user or role on every
  Discord alert.
- **Self-updater** — "Check for updates" / "Update now" buttons on the
  Settings page, backed by git tags with a `main`-branch fallback if no
  tags exist yet.
- **Guaranteed product links in alerts** — alerts now always carry a
  working link to the product, constructing one from the retailer +
  identifier when the "Product URL" field was left blank (a real gap for
  retailer types where the Identifier field is itself a URL).
- **Automatic alert cleanup** — the Dashboard's alert feed clears entries
  older than 7 days on its own.
- **Capitalized display names** throughout (retailers, games, alert
  channels, status labels) instead of raw internal keys like `bn` or
  `pokemon_center`.
- Full pytest suite (150+ tests) and a GitHub Actions CI workflow running
  tests, bandit, and shellcheck on every push/PR to `main`.
- Optional dashboard password (HTTP Basic, salted-hash storage).

### Changed
- **Removed the entire paid tier.** Every feature is free, no license key,
  no Gumroad, no tiers. A Ko-fi link is offered on every page as an
  entirely optional way to support development.
- **Split the monolithic `app.py`** into per-service router modules
  (`routers/dashboard.py`, `products.py`, `settings.py`, `setup.py`,
  `help.py`, `api.py`) plus shared `view_helpers.py`/`templating.py`.
- Data model restructured: `watchlist` (one row = one product at one
  retailer) replaced by `products` + `product_retailers` (one product,
  many retailers). Existing installs migrate automatically and
  losslessly — verified against a real simulated old-schema database.

### Fixed
- Pattern analytics no longer occasionally returned a stale "pro-tier
  feature" message from before the paywall removal.
- Donate links now always render a real `https://ko-fi.com/...` href
  instead of occasionally rendering empty (which just reloaded the page).
- A malformed or unreachable exchange-rate API response no longer crashes
  `/products` and `/` with a 500 — falls back gracefully to a cached or
  1:1 rate instead.
- Credential fields (webhook URLs, API tokens) are now stripped of
  leading/trailing whitespace on save, so a stray space or newline from a
  copy-paste can't silently break the request that uses it later.
- Discord test-send failures now surface Discord's actual response
  (status code + message) instead of a bare pass/fail, making a bad or
  deleted webhook immediately diagnosable instead of a guessing game.

### Removed
- Google AdSense integration — added, then removed at the maintainer's
  request after discussing the fit problem (a private, often
  password-gated single-user instance has no real ad audience, and risks
  an AdSense account suspension for "invalid traffic").

## [0.0.2]
### Added
- Amazon poller — first-party listings only (`Ships from and sold by
  Amazon.com`); explicitly excludes third-party marketplace sellers, which
  are where most TCG price-gouging happens.
- One-line installer (`install.sh`) and an in-browser first-run setup
  wizard — no more manual `.env` editing required to get started.
- Optional dashboard password, notification channel selection (Discord,
  ntfy, Pushover, SMS), and a security review pass (bandit + manual):
  masked credential fields, tag-pinned self-updates, locked-down file
  permissions, trimmed exception logging.
- Split the single-page app into three: Dashboard (monitoring), Products
  (management), Help/FAQ, with a shared nav.

## [0.0.1]
Initial release.

### Added
- Restock/queue detection for Target, Walmart, Best Buy, Barnes & Noble,
  Pokémon Center (with its queue system), and any Shopify-backed local
  game store.
- Per-item max-price cap ("ignore restocks priced too far over MSRP").
- Purchase-quantity tracking with a manual "mark purchased" countdown.
- Discord alerts.
- Restock-pattern analytics and subreddit chatter/forecast signals.
- Multi-game support (Pokémon, Magic, Yu-Gi-Oh, One Piece, other).
- A paid "Pro" tier gating some of the above (later fully removed in
  0.0.3 — see above).
