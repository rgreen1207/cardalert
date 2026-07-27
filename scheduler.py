"""
Background polling loop. Runs in its own thread, started from app.py.

Polling happens per (product, retailer) pairing, not per product — a
product with both Target and Amazon attached gets each checked and
alerted on independently, on its own schedule. If Target goes in stock
and alerts, that doesn't suppress a later, separate alert when Amazon
also goes in stock; the two are unrelated events even though they're
both about the same product.

Poll intervals per retailer (seconds), tuned to be far under any threshold
that looks like scraping abuse. Adjust freely in POLL_INTERVALS.
"""
import time
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

import db
import pollers
import notifier
import signals

PST = ZoneInfo("America/Los_Angeles")

POLL_INTERVALS = {
    "target": 90,
    "walmart": 120,
    "bestbuy": 120,
    "bn": 300,
    "amazon": 150,
    "lgs_shopify": 180,
    "pokemon_center": 600,   # used inside the primary window; see POKEMON_CENTER_OFF_WINDOW_INTERVAL for outside it
}

# Pokémon Center: poll every 10 minutes Mon-Thu 8am-1pm PST (when restocks
# and queues most often happen), and less frequently the rest of the time
# so a queue opening outside that window still gets caught rather than
# never checked at all — "always alert when the queue is live" needs
# polling to never fully stop, just slow down.
POKEMON_CENTER_ALLOWED_DAYS = {0, 1, 2, 3}  # Monday=0 ... Thursday=3
POKEMON_CENTER_START_HOUR = 8
POKEMON_CENTER_END_HOUR = 13
POKEMON_CENTER_OFF_WINDOW_INTERVAL = 1800  # 30 min outside the primary window

_last_polled = {}  # product_retailer_id -> unix ts
_stop_flag = threading.Event()


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
    last = _last_polled.get(retailer_row["id"], 0)
    return (time.time() - last) >= interval


def _channels_for(retailer_row: dict):
    raw = retailer_row.get("notify_channel", "") or ""
    return [c.strip() for c in raw.split(",") if c.strip()]


def poll_one(retailer_row: dict):
    """retailer_row comes from db.list_retailers_for_polling() — a
    product_retailers row annotated with its parent product's fields
    (msrp, max_pct_over_msrp, notify_channel, name, etc)."""
    _last_polled[retailer_row["id"]] = time.time()
    fn = pollers.POLLERS.get(retailer_row["retailer"])
    if not fn:
        return
    try:
        result = fn(retailer_row["identifier"])
    except Exception as e:
        db.log_status(retailer_row["id"], in_stock=False, price=None, over_msrp_pct=None,
                      ignored_over_price=False, raw_status=f"ERROR: {e}")
        return

    price = result.get("price")
    over_pct = None
    ignored = False
    if price and retailer_row.get("msrp"):
        over_pct = ((price - retailer_row["msrp"]) / retailer_row["msrp"]) * 100
        if over_pct > retailer_row.get("max_pct_over_msrp", 0):
            ignored = True

    db.log_status(
        retailer_row["id"], in_stock=result["in_stock"], price=price,
        over_msrp_pct=over_pct, ignored_over_price=ignored,
        raw_status=result.get("raw_status", ""),
    )

    if result["in_stock"] and not ignored:
        # only alert on a state *change* into stock, so we don't spam every poll —
        # deliberately scoped per retailer, not per product, so a second
        # retailer going in stock later still alerts even if this one
        # already did
        last_alert = db.last_alert_time_for_retailer(retailer_row["id"])
        was_already_alerted_recently = last_alert is not None and (time.time() - last_alert) < 1800
        if not was_already_alerted_recently:
            msg = notifier.restock_message(retailer_row, price, retailer_row.get("product_url") or "")
            for channel in _channels_for(retailer_row):
                notifier.dispatch(msg, channel)
            db.record_alert(retailer_row["product_id"], msg, product_retailer_id=retailer_row["id"])

    if result.get("raw_status") == "QUEUE_LIVE":
        msg = notifier.queue_open_message(retailer_row, retailer_row.get("product_url") or "")
        for channel in _channels_for(retailer_row):
            notifier.dispatch(msg, channel)
        db.record_alert(retailer_row["product_id"], msg, product_retailer_id=retailer_row["id"])


def poll_loop_iteration():
    for retailer_row in db.list_retailers_for_polling(active_only=True):
        if should_poll_now(retailer_row):
            poll_one(retailer_row)


_last_signal_check = 0
SIGNAL_CHECK_INTERVAL = 900  # 15 min

_last_alert_purge = 0
ALERT_PURGE_INTERVAL = 24 * 3600  # once a day is plenty for a 7-day retention window


def _purge_loop_iteration():
    global _last_alert_purge
    if time.time() - _last_alert_purge < ALERT_PURGE_INTERVAL:
        return
    _last_alert_purge = time.time()
    db.purge_old_alerts(older_than_days=7)


def signal_loop_iteration():
    global _last_signal_check
    if time.time() - _last_signal_check < SIGNAL_CHECK_INTERVAL:
        return
    _last_signal_check = time.time()
    games = {p["game"] for p in db.list_products(active_only=True)}
    if not games:
        return
    try:
        hits = signals.poll_all_signals(games)
    except Exception as e:
        print("[signals] error:", e)
        return
    for hit in hits:
        if db.signal_already_seen(hit["url"]):
            continue
        db.add_drop_signal(hit["source"], hit.get("retailer_guess"), hit["title"], hit["url"],
                            kind=hit.get("kind", "chatter"))
        notifier.send_discord(notifier.drop_signal_message(hit))


def run_forever():
    while not _stop_flag.is_set():
        try:
            poll_loop_iteration()
            signal_loop_iteration()
            _purge_loop_iteration()
        except Exception as e:
            print("[scheduler] loop error:", e)
        time.sleep(15)


def start_background_thread():
    t = threading.Thread(target=run_forever, daemon=True)
    t.start()
    return t


def stop():
    _stop_flag.set()
