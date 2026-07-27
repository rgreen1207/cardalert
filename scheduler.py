"""
Background polling loop. Runs in its own thread, started from app.py.

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
    "pokemon_center": 600,   # only actually used inside the allowed window, see below
}

# Pokémon Center: only poll Mon-Thu 8am-1pm PST, every 10 minutes, per request.
POKEMON_CENTER_ALLOWED_DAYS = {0, 1, 2, 3}  # Monday=0 ... Thursday=3
POKEMON_CENTER_START_HOUR = 8
POKEMON_CENTER_END_HOUR = 13

_last_polled = {}  # item_id -> unix ts
_stop_flag = threading.Event()


def pokemon_center_window_open() -> bool:
    now = datetime.now(PST)
    return (
        now.weekday() in POKEMON_CENTER_ALLOWED_DAYS
        and POKEMON_CENTER_START_HOUR <= now.hour < POKEMON_CENTER_END_HOUR
    )


def should_poll_now(item: dict) -> bool:
    retailer = item["retailer"]
    if retailer == "pokemon_center" and not pokemon_center_window_open():
        return False
    interval = POLL_INTERVALS.get(retailer, 180)
    last = _last_polled.get(item["id"], 0)
    return (time.time() - last) >= interval


def _channels_for(item: dict):
    raw = item.get("notify_channel", "") or ""
    return [c.strip() for c in raw.split(",") if c.strip()]


def poll_one(item: dict):
    _last_polled[item["id"]] = time.time()
    fn = pollers.POLLERS.get(item["retailer"])
    if not fn:
        return
    try:
        result = fn(item["identifier"])
    except Exception as e:
        db.log_status(item["id"], in_stock=False, price=None, over_msrp_pct=None,
                      ignored_over_price=False, raw_status=f"ERROR: {e}")
        return

    price = result.get("price")
    over_pct = None
    ignored = False
    if price and item.get("msrp"):
        over_pct = ((price - item["msrp"]) / item["msrp"]) * 100
        if over_pct > item.get("max_pct_over_msrp", 0):
            ignored = True

    db.log_status(
        item["id"], in_stock=result["in_stock"], price=price,
        over_msrp_pct=over_pct, ignored_over_price=ignored,
        raw_status=result.get("raw_status", ""),
    )

    if result["in_stock"] and not ignored:
        # only alert on a state *change* into stock, so we don't spam every poll
        was_already_alerted_recently = False
        with db.get_conn() as conn:
            row = conn.execute(
                "SELECT ts FROM alerts_sent WHERE watchlist_id = ? ORDER BY ts DESC LIMIT 1",
                (item["id"],),
            ).fetchone()
            if row and (time.time() - row["ts"]) < 1800:
                was_already_alerted_recently = True
        if not was_already_alerted_recently:
            msg = notifier.restock_message(item, price, item.get("product_url") or "")
            for channel in _channels_for(item):
                notifier.dispatch(msg, channel)
            db.record_alert(item["id"], msg)

    if result.get("raw_status") == "QUEUE_LIVE":
        msg = notifier.queue_open_message(item, item.get("product_url") or "")
        for channel in _channels_for(item):
            notifier.dispatch(msg, channel)
        db.record_alert(item["id"], msg)


def poll_loop_iteration():
    for item in db.list_items(active_only=True):
        if should_poll_now(item):
            poll_one(item)


_last_signal_check = 0
SIGNAL_CHECK_INTERVAL = 900  # 15 min


def signal_loop_iteration():
    global _last_signal_check
    if time.time() - _last_signal_check < SIGNAL_CHECK_INTERVAL:
        return
    _last_signal_check = time.time()
    games = {i.get("game", "pokemon") for i in db.list_items(active_only=True)}
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
        except Exception as e:
            print("[scheduler] loop error:", e)
        time.sleep(15)


def start_background_thread():
    t = threading.Thread(target=run_forever, daemon=True)
    t.start()
    return t


def stop():
    _stop_flag.set()
