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
**SUPERSEDED — see "Paywall fully removed" entry above.** Ryan reversed
the license/pricing decision below later the same day. Kept here for
history/context only — do not treat anything in this section as current.

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
Target, Walmart, Best Buy, Barnes & Noble, Amazon (first-party listings
only), Pokémon Center, Shopify LGS (any), generic-HTML LGS (any, lower
reliability fallback). Explicitly skipped per Ryan's instruction: Sam's
Club, GameStop.

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

## Root cause found for a whole session's worth of "still not working" reports (2026-07-27)
Ryan reported, over many turns, a series of things that were each verified
working correctly in current code (empty currency dropdown, 404s on
`/settings/check-update` and `/settings/test-discord`, missing version
text on Settings) yet kept "still happening" on his live Pi even after he
ran the installer to update. Root cause, finally found: **`install.sh`
used `sudo systemctl enable --now cardalert` for both fresh installs and
updates.** `--now` is equivalent to `systemctl start`, which does nothing
if the service is already active — so re-running the installer correctly
git-pulled new code to disk (hence the terminal showing a version bump)
but never actually restarted the already-running process, which kept
executing old code in memory indefinitely. Every "verified working in
current code, not on his Pi" finding this session was almost certainly
this one bug, not six separate deployment mishaps. Fixed by calling
`systemctl enable` and `systemctl restart` as two explicit separate
commands. **If a future session gets a report that something "still
isn't fixed" after Ryan says he updated, check whether this exact class
of bug has recurred (a script/tool that updates files but doesn't
actually cause the running process to pick them up) before assuming the
code itself has a bug** — that assumption burned a lot of turns this
session before the actual cause was found.

## Versioning convention established (2026-07-27)
Ryan asked for a RELEASE.md changelog, current version pinned at v0.0.3
(retroactively reconstructed 0.0.1 → 0.0.3 from this log's history — those
two older versions were never actually tagged, so treat their content as
approximate/reconstructed, not verbatim). **Convention going forward, must
be followed by any future session touching this codebase:**
- Every change gets an entry under `RELEASE.md`'s "Unreleased" heading as
  it's made, not batched up later from memory.
- Cutting a release = move "Unreleased" entries under a new version
  heading (v0.0.4, v0.0.5, ...) AND actually tag the commit
  (`git tag v0.0.4`) — the two have to happen together. RELEASE.md
  describing a version that was never tagged doesn't make it real for the
  in-app updater (`updater.py`), which compares against actual git tags,
  not this file's content.
- README.md's "Versioning" section and the version-tag link on the
  Settings page (in `templates/settings.html`) both assume RELEASE.md
  stays current — update all three together, not just one.

## In-app updater (2026-07-27)
Ryan wanted an actual "click to update" control on the Settings page,
not just "re-run the install command from a terminal." Built:
- `updater.py` — `check_for_update()` fetches tags/main from origin and
  compares against the current checkout; `apply_update()` checks out the
  latest tag, reinstalls deps with whatever interpreter/venv the process
  is already running under (`sys.executable`-relative pip), then schedules
  a restart a couple seconds out via a detached thread so the HTTP
  response goes out before the process gets killed.
- **The one genuinely delicate part**: the running process has to trigger
  its own replacement. Solved with `sudo -n systemctl restart cardalert`
  in a detached subprocess (`start_new_session=True`), which only works
  non-interactively because `install.sh` now writes a sudoers rule scoped
  to exactly that one command, for exactly this service and user
  (`/etc/sudoers.d/cardalert-restart`), validated with `visudo -c` before
  being kept. If that rule is missing (manual installs that skip it), the
  git pull and dependency install still succeed; only the automatic
  restart silently no-ops, and a manual `sudo systemctl restart cardalert`
  finishes the job. **Do not widen this sudo rule beyond the single
  restart command if touching this later** — that scoping is the entire
  reason it's safe to grant passwordless.
- `_run`'s `cwd` parameter was initially a default-bound argument
  (`cwd=REPO_DIR`), which silently captured `REPO_DIR`'s value at
  **module-import time**, not call time. Found this while trying to
  redirect `REPO_DIR` at a fresh Python session to test against a real
  throwaway git repo. It's not a bug for the actual running app (its
  `REPO_DIR` never changes after import), but it made the function harder
  to test and slightly less correct in principle. Fixed to read
  `REPO_DIR` inside the function body (`cwd=None` default, resolved at
  call time) instead. **If you ever add another function with a
  module-level constant as a default argument, prefer this pattern.**
- Settings page: new "Software updates" panel showing the currently
  checked-out ref, a "Check for updates" button, and a "Update now"
  button that only appears once a check finds something newer. JS
  deliberately treats a fetch error on `/settings/apply-update` as
  *expected success* (the connection drops because the app is mid-restart)
  and reloads the page after a delay either way.
- Tests: `tests/test_updater.py` (17 tests, all subprocess calls mocked
  via a `FakeCompletedProcess` helper, mirroring the pattern already used
  for HTTP mocking elsewhere) plus 3 new integration tests in
  `tests/test_app.py` for the two endpoints and the settings-page version
  display. **Also independently verified against a real throwaway git
  repo** (two tags, a real `origin` remote, actual `git fetch`/`checkout`
  calls, no mocking) to confirm the tag-comparison logic and the checkout
  itself genuinely work, not just that the mocks were self-consistent.
  Confirmed: correctly detected v1.1.0 as newer than a v1.0.0 checkout,
  and `apply_update()` actually changed the checked-out file to the newer
  version's contents.
- bandit flagged the subprocess usage here (B404/B603), as expected for
  a file that legitimately runs external commands. Annotated with `#
  nosec B404` / `# nosec B603` plus a plain-comment justification on the
  line above each (bandit's nosec syntax only accepts bare test IDs after
  `nosec`; extra trailing text produces harmless but noisy parser
  warnings, learned this the first time through and reformatted). Also
  fixed a real (if minor) finding: the restart call used partial paths
  (`"sudo"`, `"systemctl"`) instead of absolute ones; switched to
  `/usr/bin/sudo` / `/bin/systemctl` with existence checks and a fallback,
  matching what the sudoers rule itself expects.
- All 94 tests pass, bandit clean, shellcheck clean, verified live via a
  real server boot plus the real-git-repo test described above.

## Test suite + CI (2026-07-27)
Added a real pytest suite (`tests/`, 77 tests) and a GitHub Actions workflow
(`.github/workflows/ci.yml`) that runs on every push/PR to `main`.
- `tests/conftest.py` — every test gets an isolated temp SQLite file (via
  monkeypatching `db.DB_PATH`) and `scheduler.start_background_thread` is
  stubbed to a no-op everywhere, so the test suite **never spins up the
  real polling loop and never makes real network calls to any retailer**.
  A `FakeResponse` helper + `fake_response` fixture stand in for
  `requests.Response` across poller/notifier tests. **Any new test that
  touches `pollers.py` or `notifier.py` must mock `requests.get`/`post` the
  same way — don't let a test hit a real URL.**
- `tests/test_db.py`, `test_config.py`, `test_pollers.py`,
  `test_notifier.py`, `test_scheduler.py`, `test_app.py` — unit tests per
  module plus full integration tests of the web app via FastAPI's
  `TestClient` (setup flow, dashboard-password auth gating, multi-channel
  item add, currency persistence, the Discord test endpoint, pattern
  analytics, Shopify verifier).
- One deliberate regression-guard test
  (`test_no_pro_or_license_language_anywhere`) fails if `gumroad`,
  `"pro tier"`, or `"license key"` ever reappear in any rendered page —
  this exists specifically to catch anyone (including a future me)
  accidentally reintroducing the paywall that was removed earlier.
- Caught one real test-authoring bug during development: an early version
  of `test_restock_pattern_collapses_consecutive_polls` used a 50-minute
  gap while asserting it should count as a separate restock event (the
  collapse window is 1 hour) — fixed the test's timestamps, not the
  underlying `db.restock_pattern` logic, which was correct as written.
- `requirements-dev.txt` — pytest, httpx (needed by FastAPI's TestClient),
  bandit. Kept separate from `requirements.txt` so a normal install doesn't
  pull test tooling onto someone's Pi.
- `pytest.ini` — test discovery + suppresses the known-harmless FastAPI
  `on_event`/Jinja2 `TemplateResponse` deprecation warnings (not fixed at
  the source — cosmetic only, didn't want to risk touching every template
  call for a warning that isn't a real bug).
- CI runs three jobs: pytest on Python 3.11 + 3.12, bandit
  (`bandit -r . -x ./venv,./tests`), and shellcheck on `install.sh` (ran
  shellcheck locally too — zero warnings, it was already clean from the
  earlier `set -euo pipefail` + `SC1091` disable comment).
- All 77 tests + bandit + shellcheck verified passing locally before
  calling this done.

## Paywall fully removed + Amazon added + UX fixes (2026-07-26/27)
Ryan decided against any paid tier — deleted `license.py` entirely and
stripped every `is_pro`/tier/Gumroad reference from `app.py`, `scheduler.py`,
`config.py`, and all templates (verified via grep: zero hits left anywhere).
Everything that was pro-gated (unlimited retailers, all alert channels,
pattern analytics, forecast signals) is now free by default. Added a
Ko-fi donation link (`https://ko-fi.com/ryanthedev`) in the nav bar and
`LICENSE.md`, framed as optional/never required — **do not reintroduce any
gating tied to it**, it's a plain donate link, not a feature unlock.

Also in this pass:
- **Multi-channel alerts**: `notify_channel` column now stores a
  comma-separated list (e.g. `"discord,ntfy"`) instead of a single value.
  UI changed from a `<select>` to checkboxes (`notify_channels` repeated
  form field, joined server-side in `app.py`). `scheduler.py`'s
  `_channels_for()` splits and dispatches to every selected channel.
  **Any future channel-related code must treat notify_channel as CSV, not
  a single string.**
- **Currency**: new `currency` setting (`config.py`, `CURRENCY_SYMBOLS`
  map, `config.currency_symbol()` helper), selectable on Settings. Templates
  use `currency_symbol` from context instead of hardcoded `$`. Tested with
  GBP end-to-end (`£99.99` rendered correctly).
- **Discord webhook test button**: `POST /settings/test-discord` — actually
  fires a real request via `notifier.send_discord` (now returns a bool)
  and reports success/failure in the UI. Tested both the "no webhook
  configured" and "webhook configured but fails" paths.
- **Tooltip layout fix**: `.tip` icons were stacking onto their own line
  below the label text because the parent `<label>` is `flex-direction:
  column` and the tip span was a separate flex child. Fixed by wrapping
  label text + tip icon together in a single `<span class="label-row">`
  per field in `products.html`.
- **Amazon poller added** (`pollers.py: check_amazon`). Deliberately
  **first-party only** — regex-checks for "Ships from and sold by
  Amazon.com" and returns `THIRD_PARTY_SELLER_ONLY` (not in stock) if the
  listing is from a marketplace seller instead. Accepts a bare ASIN or a
  full product URL, normalizes to `/dp/{ASIN}`. Unit-tested the
  classification logic against 4 synthetic HTML cases (first-party in
  stock, third-party, sold out, first-party-but-sold-out) — all correct.
  **Flagged as the least reliable poller of the set** — Amazon changes
  page structure and fights scraping harder than any other retailer here;
  documented in README/help.html as the one most likely to need retuning.
  Poll interval set to 150s in `scheduler.py`.

All changes syntax-checked, bandit-clean, and smoke-tested end-to-end
(setup skip → all 4 pages 200 → multi-channel item add → currency
round-trip → Amazon item add via bare ASIN, all confirmed via `/api/items`).

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
- Gumroad product not yet created — this note is now moot; the whole
  license/pro-tier system was removed on 2026-07-26, see the entry above.
- ~~Installer script~~ — built (`install.sh`), see the "One-line install"
  entry above.
- ~~systemd timer for auto-checking updates~~ — superseded by the in-app
  "Check for updates" button, which checks on demand rather than on a
  timer. A background auto-check (not auto-apply) could still be added
  later if Ryan wants it, but isn't built.
- ~~Dashboard "update available" UI~~ — built, see the "In-app updater"
  entry above.
- No tagged releases exist on the repo yet as of this log. `install.sh`
  and `updater.py` both fall back to `main` gracefully when there are no
  tags, but the real one-click-update value (pinned, reviewed releases
  rather than whatever's on main) only kicks in once Ryan actually cuts a
  first release tag. Worth flagging if a future session is asked to
  debug "why did update pull main instead of a specific version."
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
