# Release Notes

All notable changes to Card Alert are logged here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/). Versions here are meant to
match git tags of the same name (`v0.0.3`, etc.) — the in-app updater
(Settings → "Check for updates") compares against tags, so cutting a
release means both: add an entry here, then tag the commit.

## [Unreleased]
### Fixed
- Target's anti-bot detection was checking for the wrong markers —
  built from a guess about what a PerimeterX block page's HTML might
  say, but a real 403 response shared by a user showed Target's redsky
  API actually responds with a structured JSON captcha challenge
  (`captchaRelativeURL`/`captchaAbsoluteURL` pointing to
  `/captcha?trackingId=...`), which matched none of those markers and
  fell through to the generic "Blocked by retailer" label. Added
  detection for the real, confirmed format as its own status,
  "Blocked — captcha required" — unambiguous proof it's anti-bot
  detection specifically, since a bad key produces an "unauthorized"
  error, not a captcha challenge. Test built directly from the real
  response body, not a synthetic guess.

### Added
- Target's poller now distinguishes an anti-bot block from a generic
  key/rate-limit rejection, based on real evidence (checked the response
  body for known bot-mitigation markers, e.g. PerimeterX, which is
  visibly present on Target's own page via its "humanSensor" script and
  `_pxhd` cookie), instead of guessing from the status code alone. Shows
  as "Blocked by anti-bot protection," distinct from "Blocked by
  retailer." Also confirmed, by inspecting real Target page source,
  that the key embedded in the page is a static default served to every
  visitor (`defaultServicesApiKey`), not a private one — so "Find
  automatically" can only ever find the same shared key everyone already
  has, and that's now documented honestly rather than implied to be a
  real fix for anti-bot blocking.

## [0.0.13]
### Fixed
- **Reverted a scope-boundary violation introduced in the last pull**:
  `pollers.py` had grown a `sync_target_session()` that launched headless
  Chromium via Playwright to harvest Target's anti-bot session cookies
  and Redsky API key, then replayed them on requests. That's
  session-token capture, the exact thing this project's `PROJECT_LOG.md`
  and `LICENSE.md` §4 rule out — detection/alerting/tracking only, never
  anything that holds or replays a captured session. Removed
  `sync_target_session`/`TARGET_SESSION` entirely, dropped
  `playwright`/`greenlet`/`pyee` from `requirements.txt`, and restored
  `check_target`'s Redsky URL, which the same pull had broken down to a
  bare `https://target.com` (would have failed every request).
- `check_target` now sends `TARGET_HEADERS` (`Accept: application/json`,
  `Origin`, `Referer`) instead of the generic `HEADERS` — that dict
  existed but was never actually used, so every request looked less like
  a real browser hit than it should have.
- `check_bestbuy` had silently regressed to hitting a made-up
  `bestbuy.com/{sku}/fulfillment` endpoint instead of the documented,
  official Best Buy Products API — always failed. Restored the
  API-key-based implementation.
- `check_amazon`'s first-party/third-party seller detection had
  regressed to structural HTML checks (specific element IDs/merchant
  input fields) that don't match the page shapes this was built and
  tested against, silently misclassifying in-stock first-party listings
  as third-party. Restored the original regex-based detection.
- Removed `license.py` — dead code left over from the fully-removed
  paywall (see `PROJECT_LOG.md`, "Paywall fully removed"), referencing
  two `config` keys that no longer exist and would `KeyError` on any
  call.
- `signals.py`'s `RETAILER_NAMES` was missing `amazon`, `lgs_shopify`,
  and `lgs_generic`, so Reddit restock-chatter scanning silently never
  covered those retailers. Added them, fixed "Barnes Noble" →
  "Barnes & Noble", and deduped the lookup.
- The repo's ignore file was named `gitignore` instead of `.gitignore`,
  so git never actually read it — `.venv/`, `__pycache__/`, etc. all
  showed as untracked. Renamed.
- Six `test_pollers.py` mocks for Target's HTTP layer used a narrower
  function signature than `check_target`/`discover_target_api_key`
  actually call (missing the `impersonate` kwarg), so they'd been
  failing independent of any of the above. Widened the mocks.

### Changed
- **The whole app is now async**, top to bottom: `db.py` runs on
  `aiosqlite` instead of blocking `sqlite3`, `pollers.py` uses
  `curl_cffi`'s `AsyncSession`, and `notifier.py`/`signals.py`/`fx.py`
  use `httpx.AsyncClient`. Every route in `routers/` and the scheduler
  loop are `async def`, all sharing FastAPI's single event loop instead
  of the scheduler running in its own background thread.
- The scheduler now polls every retailer that's due in a given tick
  **concurrently** (`asyncio.gather`) instead of one at a time — wall
  clock per tick is the slowest single check, not the sum of all of
  them.
- To keep that concurrency from turning into a burst of simultaneous,
  identically-timed requests at the same retailer (itself a pattern
  anti-bot systems watch for), added a per-retailer-type concurrency cap
  (`RETAILER_CONCURRENCY = 3`) and a small random jitter
  (0–2s) before each request, so different products at the same
  retailer don't all hit the wire in the same instant.
- Scheduler now backs off exponentially (up to 8x the normal interval)
  on a retailer that comes back captcha/anti-bot/rate-limited/blocked
  several times in a row, instead of continuing to poll it at full
  speed while already blocked — resets to normal cadence the moment a
  check succeeds again.
- `signals.py`'s Reddit chatter/forecast search now fans out its
  per-subreddit, per-retailer searches concurrently too (capped at 5 at
  once), instead of running them one after another.

## [0.0.9]
Continuation of v0.0.8's Pokémon Center and Target work, plus a fix for
a jarring UI issue.

### Changed
- **"Queue is live" alerts are now one per opening by default**, not
  periodic reminders. Fires the moment the queue transitions from closed
  to live, then stays quiet for as long as it remains live — only alerts
  again if it closes and reopens later. An opt-in setting, "Alert me
  multiple times while the queue is live, every ___ seconds," switches
  to repeated reminders instead (minimum 30 seconds between them),
  spaced by whatever interval you set, for people who'd rather get
  several chances to notice a queue that opened early in the morning.
  Replaces the previous 90-second-cooldown design, which was closer to
  "periodic reminders" than "one alert."
- Target's automatic key discovery now tries your own saved Target
  products first (real, currently-live pages you already care about),
  falling back to the one fixed example page only if you have none
  saved or none of them happen to have the key embedded.
- Consolidated and clarified the Pokémon Center explanation on
  Settings — the fast check and full check are now described together
  in one place, in plain terms, instead of split across a hint paragraph
  and a separate FAQ entry.

### Fixed
- **The Dashboard's auto-refresh was a full page reload every 30
  seconds** — the visible "tab keeps refreshing" issue. Replaced with a
  quiet background fetch that swaps only the fragments showing live data
  (status table, alerts, chatter, the Pokémon Center window indicator),
  with no visible flash, no lost scroll position, and no interrupted
  in-progress "Pattern" lookup. The Pattern button's click handling
  switched to event delegation so it keeps working after every refresh
  without needing to be re-wired each time.
- The fast Pokémon Center queue check was resolving the wrong URL —
  found and fixed during live verification of this release, not by
  inspection alone. It only read the `product_url` field, but Pokémon
  Center's documented convention is that the `identifier` field itself
  IS the URL when `product_url` is left blank (the normal case for this
  retailer type) — every other part of the app already accounted for
  this via `notifier.resolve_product_url`, the fast check didn't, and
  would try to fetch an empty string for any Pokémon Center item added
  the normal way.
- A test-isolation bug: a few of the scheduler's timing trackers live in
  plain in-memory dictionaries (by design, since they don't need to
  survive a restart) that weren't being reset between tests, unlike the
  database. Since each test's fresh database restarts its retailer IDs
  from 1, stale state from one test's retailer could silently leak into
  an unrelated later test that happened to get the same ID.

Two feature areas: faster Pokémon Center queue detection, and three
Settings-page improvements (multiple Discord mentions, a Best Buy signup
link, and automatic Target API key discovery).

### Added
- A much faster, much lighter check specifically for the Pokémon Center
  queue, separate from the existing full stock/price check. It only asks
  "is the queue live" using a HEAD request instead of a full page fetch,
  which is what makes checking every 15 seconds (configurable, minimum
  10) reasonable instead of excessive — there's no true push/webhook API
  available from Pokémon Center, so fast+light polling is the closest
  available to "actively listening." Queue-live alerts now share a
  90-second cooldown across both checks (previously no cooldown at all,
  which was fine at a 10-minute interval but would have meant an alert
  every 10-15 seconds at the new one) — the first alert still fires
  promptly, repeats are limited to roughly once per cooldown window.
- Discord mentions now support multiple users and roles, comma
  separated, instead of just one of either — two separate fields
  ("Mention users" / "Mention roles"), each accepting a comma-separated
  list of numeric Discord IDs. Any non-numeric entry in a list is
  skipped independently without affecting the others.
- A direct link to developer.bestbuy.com on the Best Buy settings panel.
- A "Find automatically" button for the Target API key — tries to find
  a currently-working one by reading it out of a real Target page (the
  key is something Target's own frontend already sends to every
  visitor, not something hidden), and falls back to manual entry with a
  clear message if it can't find one. Not guaranteed to keep working
  forever if Target changes how they embed it, hence the fallback always
  being there.
- A clear reminder on Settings that changes only take effect after
  clicking "Save settings," plus a sticky "you have unsaved changes" bar
  that appears the moment anything is edited and stays reachable without
  scrolling. "Send test alert" now also refuses to run (with an
  explanation) if there are unsaved changes, instead of silently testing
  the old saved value with no warning — the exact confusion this was
  meant to fix.
- A "Target polling" field on Settings to use your own redsky API key
  instead of the shared default one. The shared key is public and used
  across the hobbyist restock-tracking community, so it absorbs
  aggregate rate-limiting from everyone on it, not just you — a key only
  you use avoids that. Found the same legitimate way the default one
  was: opening Target's site and watching what its own frontend requests.
- Target's requests now send `Origin`, `Referer`, and `Accept` headers
  matching what a real page load includes, not just a bare User-Agent —
  a normal completeness fix, not fingerprint evasion. Deliberately did
  not go further into proxy rotation, headless-browser automation, or
  anything else specifically meant to defeat Target's anti-bot
  detection — that's a different category of thing than this project
  does at any tier.

## [0.0.8]
Note: v0.0.7 was intentionally skipped, never used for a release.

Two feature areas: faster Pokémon Center queue detection, and three
Settings-page improvements (multiple Discord mentions, a Best Buy signup
link, and automatic Target API key discovery — later improved further
in v0.0.9 above).

## [0.0.6]
A redesign pass plus one diagnostics improvement: the app finally has a
real visual identity instead of a bare ops-dashboard look, and Target's
poller errors are now debuggable without ever leaking raw error text into
the rendered pages.

### Added
- Redesigned the whole app with a genuine visual identity instead of a
  bare ops-dashboard look — a warm plum-navy palette with gold and mint
  accents (inspired by holographic card foil, not a generic dark-mode
  default), Fraunces for headings and Plus Jakarta Sans for body text,
  generous rounded corners and soft shadows on every panel instead of
  hard borders, and pill-shaped buttons/tabs throughout.
- The add-product form now shows only the essential fields (name, game,
  quantity, max price, retailers) by default; price tolerance and alert
  channels are tucked behind a "More options" disclosure, since both
  already have sensible defaults and don't need to be visible for a
  first-time add.
- A status-light legend on the Dashboard explaining what each lamp color
  means (in stock/alerted, in stock but over price cap, everything else),
  since the colors alone weren't self-explanatory.
- Target's poller errors (blocked/rate-limited/malformed response) now
  log the real detail to the console/systemd journal and include it
  verbatim in the JSON API responses (inspectable via a browser's Network
  tab), while the rendered dashboard/products pages only ever show a
  masked, generic label. Verified this split explicitly: added an
  integration test confirming the raw error text never appears in
  rendered HTML but does appear in the `/api/items` response.

### Changed
- "Send test alert" now reports exactly which mention (if any) it
  applied, instead of just "Sent" with no visibility into whether the
  mention rule actually fired — verified the full save-then-test flow
  end to end through the real HTTP endpoints (not just the internal
  function) and confirmed the mention is correctly built and sent. If a
  role mention still doesn't ping in Discord despite showing as applied,
  that's almost always the role's own "Allow anyone to @mention this
  role" setting on Discord's side, not something this app controls —
  documented in the Help page.
- Target's poller now distinguishes *why* a check failed instead of
  collapsing everything into "Error checking stock": a 401/403 (most
  likely the hardcoded API key needs rotating) shows as "Blocked by
  retailer," a 429 shows as "Rate limited, will retry," and a response
  that isn't valid JSON shows as "Unexpected response" — separate from
  "Not found," which means Target responded fine, just without the usual
  stock fields (e.g. a delisted item). This sandbox can't reach Target's
  real API to test live (confirmed: the network proxy here blocks
  `redsky.target.com` outright), so if "Blocked by retailer" shows up
  consistently, the embedded API key most likely needs an actual update —
  that's a real, expected maintenance point for this specific poller, not
  a bug to chase further without seeing the real response.

## [0.0.5]
Bug-fix release covering six issues found in real use, plus the root
cause behind a whole prior session's worth of "already fixed but not
working" reports, plus the Pokémon Center queue-alert fix below.

### Added
- "Always alert when the Pokémon Center queue is live" — confirmed the
  existing alert path actually works end-to-end (it had zero test
  coverage before now) and closed a real gap: polling used to stop
  entirely outside the Mon-Thu 8am-1pm PST window, so a queue opening at
  any other time could never be detected or alerted on at all. Now polls
  every 30 minutes outside that window instead of not polling, so
  "always" is actually true. Queue-live alerts also have no cooldown —
  they fire again on every poll for as long as the queue stays open,
  unlike restock alerts, which dedupe for 30 minutes.

### Fixed
- **The remove ("×") button on a retailer row in the add-product form
  wrapped to its own line instead of staying on the same line as the
  rest of the row.** Switched the row from CSS Grid to flexbox with
  `flex-wrap: nowrap`, so it can't wrap regardless of container width.
- **Adding multiple retailers to a product at once only kept the
  first one** — investigated thoroughly, including simulating the exact
  raw, interleaved form encoding a real browser sends (not just a
  dict-based test helper), and the backend correctly handles this in
  current code. The real gap: the Identifier field on each retailer row
  had no `required` attribute, so a row left incomplete (e.g. retailer
  selected but identifier never filled in) was silently dropped
  server-side with zero feedback — which looks exactly like "retailers
  vanishing" from the user's side. Now required client-side, so the
  browser blocks submission instead of silently losing data.
- **Target quantity appeared to reset to 1** — thoroughly tested the
  full add → display → edit → re-display lifecycle with quantities of 3
  and 5; found no bug in current code. Locked in with a permanent
  regression test covering all four surfaces (add, listing page, edit
  page, post-edit) so this can't silently regress later.
- **The Dashboard showed "Error checking stock" for items that were
  actually just out of stock.** Found a real bug: `check_target` used
  direct dictionary indexing (`data["data"]["product"]`) with no
  fallback, so any Target API response missing that structure (delisted
  items, restricted items, occasional API quirks) raised an uncaught
  `KeyError`, which got logged as a generic error rather than the more
  accurate "not found." Switched to defensive `.get()` access.
- **Amazon (and other retailer) links in alerts carried tracking
  parameters** instead of a clean product URL. Added URL stripping that
  removes the query string and fragment from every resolved link,
  applied whether the URL came from the identifier field, the explicit
  "Product URL" field, or was constructed from an ASIN/TCIN. Deliberately
  exempted Best Buy's search link, since its `?st=...` parameter is the
  actual search query, not tracking data — stripping it would have left
  a dead search page.
- **Discord @mentions rendered as literal `<@id>` text instead of
  actually pinging.** Found two real, independent causes and fixed both:
  (1) the webhook payload never included an `allowed_mentions` field,
  and without it Discord can render mention syntax as plain unlinked
  text instead of resolving it; (2) the mention ID field wasn't
  validated as numeric, so a non-numeric value (e.g. a username typed by
  mistake instead of the actual snowflake ID) could never have resolved
  to a real mention regardless of the payload fix. Both are now handled:
  `allowed_mentions` is always sent, and a non-numeric ID is skipped
  entirely rather than sent as broken-looking text, with the Settings
  page's help text now explicit about needing the numeric ID.

## [0.0.4]
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
