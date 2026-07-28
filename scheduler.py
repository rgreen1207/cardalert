"""
Background polling loop. Runs as an asyncio task started from app.py's
startup event, sharing the same event loop as the web server — so pollers,
notifiers, and DB access all run as async I/O instead of blocking a thread.

Polling happens per (product, retailer) pairing, not per product — a
product with both Target and Amazon attached gets each checked and
alerted on independently, on its own schedule. If Target goes in stock
and alerts, that doesn't suppress a later, separate alert when Amazon
also goes in stock; the two are unrelated events even though they're
both about the same product.

Poll intervals per retailer (seconds), tuned to be far under any threshold
that looks like scraping abuse. Adjust freely in POLL_INTERVALS.

Retailers due for a check in the same tick are polled concurrently via
asyncio.gather rather than one at a time, which is both faster (wall-clock
per tick is the slowest single check, not the sum of all of them) and
capped per retailer type by a semaphore plus a small random jitter before
each request, so a burst of due checks doesn't turn into simultaneous,
identically-timed hits on the same retailer — a request pattern that's
itself a signal anti-bot systems look for.
"""
import asyncio
import random
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import db
import pollers
import notifier
import signals
import config

PST = ZoneInfo("America/Los_Angeles")

POLL_INTERVALS = {
    "target": 90,
    "walmart": 120,
    "bestbuy": 120,
    "bn": 300,
    "amazon": 150,
    "lgs_shopify": 180,
    "pokemon_center": 600,   # the FULL stock/price check — see the fast queue-only check below for queue detection specifically
}

# Pokémon Center: full stock/price checks every 10 minutes Mon-Thu
# 8am-1pm PST (when restocks and queues most often happen), and less
# frequently the rest of the time so a queue opening outside that window
# still gets caught rather than never checked at all.
POKEMON_CENTER_ALLOWED_DAYS = {0, 1, 2, 3}  # Monday=0 ... Thursday=3
POKEMON_CENTER_START_HOUR = 8
POKEMON_CENTER_END_HOUR = 13
POKEMON_CENTER_OFF_WINDOW_INTERVAL = 1800  # 30 min outside the primary window

# Separately, a much faster, much lighter check runs continuously (not
# restricted to the window) purely to catch the queue opening quickly —
# see pollers.check_pokemon_center_queue_only, which uses a HEAD request
# instead of a full page fetch specifically so this can run often without
# costing much bandwidth per check. There's no true push/webhook API for
# this available from Pokémon Center, so frequent-but-light polling is
# the closest available to "actively listening." The interval is
# configurable on the Settings page (config.pokemon_center_fast_check_seconds),
# clamped to a floor so it can never be set low enough to become genuinely
# excessive.
#
# Whether a "queue is live" alert fires once per opening (the default) or
# repeats while it stays open depends on config.pokemon_center_repeat_alerts_enabled().
# Either way, this only needs to know "was it live last time I checked,"
# tracked here rather than in the database — a state flip is a cheap,
# in-memory thing, and this doesn't need to survive a restart (a restart
# mid-queue would just mean one possible extra "first" alert, an
# acceptable tradeoff for not needing a DB round-trip on every check).
_queue_was_live = {}  # product_retailer_id -> bool
_last_polled = {}  # product_retailer_id -> unix ts
_last_queue_checked = {}  # product_retailer_id -> unix ts
_stop_flag = False

# Raw statuses a poller returns when a retailer's anti-bot layer (rather than
# a transient network blip) is the reason a check didn't succeed. Getting one
# of these repeatedly in a row backs a retailer off exponentially instead of
# continuing to hit it at the normal interval, which is itself part of what
# makes a block worse/longer. Resets to normal cadence the moment a poll
# comes back clean again.
BLOCK_STATUSES = {"CAPTCHA_REQUIRED", "BLOCKED_BY_ANTIBOT", "RATE_LIMITED", "BLOCKED_OR_KEY_INVALID"}
BACKOFF_MAX_MULTIPLIER = 8
_consecutive_blocks = {}  # product_retailer_id -> int

# Caps how many requests to the *same* retailer type run at once, and adds
# a small random delay before each one so a batch of due checks doesn't
# all land on the wire in the same instant. Different retailers still run
# fully concurrently with each other — this only throttles within one.
RETAILER_CONCURRENCY = 3
JITTER_MAX_SECONDS = 2.0
_retailer_semaphores = {}  # retailer type -> asyncio.Semaphore


def _semaphore_for(retailer: str) -> asyncio.Semaphore:
    sem = _retailer_semaphores.get(retailer)
    if sem is None:
        sem = asyncio.Semaphore(RETAILER_CONCURRENCY)
        _retailer_semaphores[retailer] = sem
    return sem


def pokemon_center_window_open() -> bool:
    now = datetime.now(PST)
    return (
        now.weekday() in POKEMON_CENTER_ALLOWED_DAYS
        and POKEMON_CENTER_START_HOUR <= now.hour < POKEMON_CENTER_END_HOUR
    )


def should_poll_now(retailer_row: dict) -> bool:
    retailer = retailer_row["retailer"]
    if retailer == "pokemon_center":
        interval = POLL_INTERVALS["pokemon_center"] if pokemon_center_window_open() \
            else POKEMON_CENTER_OFF_WINDOW_INTERVAL
    else:
        interval = POLL_INTERVALS.get(retailer, 180)

    blocks = _consecutive_blocks.get(retailer_row["id"], 0)
    if blocks:
        interval *= min(2 ** blocks, BACKOFF_MAX_MULTIPLIER)

    last = _last_polled.get(retailer_row["id"], 0)
    return (time.time() - last) >= interval


async def should_check_queue_fast_now(retailer_row: dict) -> bool:
    if retailer_row["retailer"] != "pokemon_center":
        return False
    interval = await config.pokemon_center_fast_check_seconds()
    last = _last_queue_checked.get(retailer_row["id"], 0)
    return (time.time() - last) >= interval


def _channels_for(retailer_row: dict):
    raw = retailer_row.get("notify_channel", "") or ""
    return [c.strip() for c in raw.split(",") if c.strip()]


async def _send_queue_alert(retailer_row: dict):
    msg = notifier.queue_open_message(retailer_row, retailer_row.get("product_url") or "")
    for channel in _channels_for(retailer_row):
        await notifier.dispatch(msg, channel)
    await db.record_alert(retailer_row["product_id"], msg, product_retailer_id=retailer_row["id"])


async def _handle_queue_status(retailer_row: dict, queue_live: bool):
    """Shared by both the fast queue-only path and the full check's own
    queue detection, so state tracking and alert behavior stay consistent
    regardless of which one is running at any given moment.

    Default behavior: exactly one alert per opening — the moment
    queue_live flips from False to True. No further alerts while it
    stays live, only a new one if it closes (queue_live goes back to
    False) and then opens again later. If the user has turned on repeat
    alerts, additional alerts fire roughly every
    config.pokemon_center_repeat_alert_seconds() for as long as it
    remains live, instead of just the one."""
    retailer_id = retailer_row["id"]
    was_live = _queue_was_live.get(retailer_id, False)
    _queue_was_live[retailer_id] = queue_live

    if not queue_live:
        return  # nothing to alert on; state is now recorded as "not live"

    if not was_live:
        await _send_queue_alert(retailer_row)  # fresh opening — always alert immediately
        return

    if await config.pokemon_center_repeat_alerts_enabled():
        last_alert = await db.last_alert_time_for_retailer(retailer_id)
        interval = await config.pokemon_center_repeat_alert_seconds()
        if last_alert is None or (time.time() - last_alert) >= interval:
            await _send_queue_alert(retailer_row)


async def check_queue_fast(retailer_row: dict):
    """The lightweight, frequent path — only ever checks for the queue,
    never touches stock/price, so it stays cheap enough to run often."""
    _last_queue_checked[retailer_row["id"]] = time.time()
    url = notifier.resolve_product_url(retailer_row)
    if not url:
        return
    try:
        result = await pollers.check_pokemon_center_queue_only(url)
    except Exception as e:
        print(f"[scheduler] fast queue check failed for retailer_id={retailer_row['id']}:", repr(e))
        return
    queue_live = bool(result.get("queue_live"))
    if queue_live:
        await db.log_status(retailer_row["id"], in_stock=False, price=None, over_msrp_pct=None,
                             ignored_over_price=False, raw_status="QUEUE_LIVE")
    await _handle_queue_status(retailer_row, queue_live)


async def poll_one(retailer_row: dict):
    """retailer_row comes from db.list_retailers_for_polling() — a
    product_retailers row annotated with its parent product's fields
    (msrp, max_pct_over_msrp, notify_channel, name, etc)."""
    _last_polled[retailer_row["id"]] = time.time()
    fn = pollers.POLLERS.get(retailer_row["retailer"])
    if not fn:
        return

    async with _semaphore_for(retailer_row["retailer"]):
        await asyncio.sleep(random.uniform(0, JITTER_MAX_SECONDS))  # nosec B311 - request-timing jitter, not security-sensitive
        try:
            result = await fn(retailer_row["identifier"])
        except Exception as e:
            # The dashboard only ever shows a masked, generic label for this
            # (see display.status_label) — the actual exception goes to the
            # console/systemd journal here, and into error_detail below,
            # which the API responses (e.g. /api/items) include verbatim, so
            # it's inspectable via a browser's Network tab without ever
            # appearing in the rendered page itself.
            print(f"[scheduler] {retailer_row['retailer']} poll failed for "
                  f"retailer_id={retailer_row['id']}:", repr(e))
            await db.log_status(retailer_row["id"], in_stock=False, price=None, over_msrp_pct=None,
                                 ignored_over_price=False, raw_status=f"ERROR: {e}",
                                 error_detail=f"{type(e).__name__}: {e}")
            return

    error_detail = result.get("error_detail")
    if error_detail:
        print(f"[scheduler] {retailer_row['retailer']} retailer_id={retailer_row['id']} "
              f"returned {result.get('raw_status')}:", error_detail)

    if result.get("raw_status") in BLOCK_STATUSES:
        _consecutive_blocks[retailer_row["id"]] = _consecutive_blocks.get(retailer_row["id"], 0) + 1
    else:
        _consecutive_blocks[retailer_row["id"]] = 0

    price = result.get("price")
    over_pct = None
    ignored = False
    if price and retailer_row.get("msrp"):
        over_pct = ((price - retailer_row["msrp"]) / retailer_row["msrp"]) * 100
        if over_pct > retailer_row.get("max_pct_over_msrp", 0):
            ignored = True

    await db.log_status(
        retailer_row["id"], in_stock=result["in_stock"], price=price,
        over_msrp_pct=over_pct, ignored_over_price=ignored,
        raw_status=result.get("raw_status", ""),
        error_detail=error_detail,
    )

    if result["in_stock"] and not ignored:
        # only alert on a state *change* into stock, so we don't spam every poll —
        # deliberately scoped per retailer, not per product, so a second
        # retailer going in stock later still alerts even if this one
        # already did
        last_alert = await db.last_alert_time_for_retailer(retailer_row["id"])
        was_already_alerted_recently = last_alert is not None and (time.time() - last_alert) < 1800
        if not was_already_alerted_recently:
            msg = notifier.restock_message(retailer_row, price, retailer_row.get("product_url") or "")
            for channel in _channels_for(retailer_row):
                await notifier.dispatch(msg, channel)
            await db.record_alert(retailer_row["product_id"], msg, product_retailer_id=retailer_row["id"])

    if retailer_row["retailer"] == "pokemon_center":
        await _handle_queue_status(retailer_row, result.get("raw_status") == "QUEUE_LIVE")


async def poll_loop_iteration():
    retailers = await db.list_retailers_for_polling(active_only=True)
    due = [r for r in retailers if should_poll_now(r)]
    if due:
        await asyncio.gather(*(poll_one(r) for r in due))


async def queue_fast_check_loop_iteration():
    retailers = await db.list_retailers_for_polling(active_only=True)
    due = [r for r in retailers if await should_check_queue_fast_now(r)]
    if due:
        await asyncio.gather(*(check_queue_fast(r) for r in due))


_last_signal_check = 0
SIGNAL_CHECK_INTERVAL = 900  # 15 min

_last_alert_purge = 0
ALERT_PURGE_INTERVAL = 24 * 3600  # once a day is plenty for a 7-day retention window


async def _purge_loop_iteration():
    global _last_alert_purge
    if time.time() - _last_alert_purge < ALERT_PURGE_INTERVAL:
        return
    _last_alert_purge = time.time()
    await db.purge_old_alerts(older_than_days=7)


async def signal_loop_iteration():
    global _last_signal_check
    if time.time() - _last_signal_check < SIGNAL_CHECK_INTERVAL:
        return
    _last_signal_check = time.time()
    products = await db.list_products(active_only=True)
    games = {p["game"] for p in products}
    if not games:
        return
    try:
        hits = await signals.poll_all_signals(games)
    except Exception as e:
        print("[signals] error:", e)
        return
    for hit in hits:
        if await db.signal_already_seen(hit["url"]):
            continue
        await db.add_drop_signal(hit["source"], hit.get("retailer_guess"), hit["title"], hit["url"],
                                  kind=hit.get("kind", "chatter"))
        await notifier.send_discord(notifier.drop_signal_message(hit))


async def run_forever():
    global _stop_flag
    while not _stop_flag:
        try:
            await poll_loop_iteration()
            await queue_fast_check_loop_iteration()
            await signal_loop_iteration()
            await _purge_loop_iteration()
        except Exception as e:
            print("[scheduler] loop error:", e)
        # 5s, not 15s — the fast queue-check floor is 10s, so the tick
        # rate needs to be fine-grained enough to actually honor that
        # without waiting up to an extra 15s past the configured interval.
        await asyncio.sleep(5)


def start():
    """Schedules the polling loop on the running event loop — call from
    an async context (app.py's startup event)."""
    return asyncio.create_task(run_forever())


def stop():
    global _stop_flag
    _stop_flag = True
