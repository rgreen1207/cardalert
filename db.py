"""
SQLite data layer for the restock watch dashboard.
Single file DB, no ORM needed at this scale.
"""
import sqlite3
import time
from contextlib import contextmanager

DB_PATH = "watchdata.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS watchlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    game TEXT NOT NULL DEFAULT 'pokemon',   -- pokemon | mtg | yugioh | onepiece | other
    retailer TEXT NOT NULL,          -- target | walmart | bestbuy | bn | pokemon_center | lgs_shopify | lgs_generic
    identifier TEXT NOT NULL,        -- TCIN / SKU / product URL / handle, depends on retailer
    product_url TEXT,
    target_qty INTEGER NOT NULL DEFAULT 1,
    remaining_qty INTEGER NOT NULL DEFAULT 1,
    msrp REAL,
    max_pct_over_msrp REAL NOT NULL DEFAULT 0,   -- e.g. 20 = ignore if >20% over MSRP
    notify_channel TEXT NOT NULL DEFAULT 'dashboard',  -- dashboard | discord | ntfy | pushover | sms
    active INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS status_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    watchlist_id INTEGER NOT NULL,
    ts REAL NOT NULL,
    in_stock INTEGER NOT NULL,
    price REAL,
    over_msrp_pct REAL,
    ignored_over_price INTEGER NOT NULL DEFAULT 0,
    raw_status TEXT,
    FOREIGN KEY(watchlist_id) REFERENCES watchlist(id)
);

CREATE TABLE IF NOT EXISTS alerts_sent (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    watchlist_id INTEGER NOT NULL,
    ts REAL NOT NULL,
    message TEXT NOT NULL,
    FOREIGN KEY(watchlist_id) REFERENCES watchlist(id)
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS drop_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    source TEXT NOT NULL,
    retailer_guess TEXT,
    kind TEXT NOT NULL DEFAULT 'chatter',   -- chatter | forecast
    title TEXT NOT NULL,
    url TEXT
);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


CURRENT_SCHEMA_VERSION = 2


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        row = conn.execute("SELECT version FROM schema_version").fetchone()
        if row is None:
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (CURRENT_SCHEMA_VERSION,))
        _run_migrations(conn)


def _run_migrations(conn):
    """Simple numbered migrations. Add a new elif block + bump
    CURRENT_SCHEMA_VERSION when the schema changes — never edit the SCHEMA
    string in a way that breaks existing installs' data."""
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    version = row["version"] if row else 0
    if version < 2:
        cols = [c["name"] for c in conn.execute("PRAGMA table_info(watchlist)").fetchall()]
        if "game" not in cols:
            conn.execute("ALTER TABLE watchlist ADD COLUMN game TEXT NOT NULL DEFAULT 'pokemon'")
        if "notify_channel" not in cols:
            conn.execute("ALTER TABLE watchlist ADD COLUMN notify_channel TEXT NOT NULL DEFAULT 'dashboard'")
        signal_cols = [c["name"] for c in conn.execute("PRAGMA table_info(drop_signals)").fetchall()]
        if "kind" not in signal_cols:
            conn.execute("ALTER TABLE drop_signals ADD COLUMN kind TEXT NOT NULL DEFAULT 'chatter'")
        conn.execute("UPDATE schema_version SET version = 2")


def add_item(name, game, retailer, identifier, product_url, target_qty, msrp,
             max_pct_over_msrp, notify_channel="dashboard"):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO watchlist
               (name, game, retailer, identifier, product_url, target_qty, remaining_qty,
                msrp, max_pct_over_msrp, notify_channel, active, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)""",
            (name, game, retailer, identifier, product_url, target_qty, target_qty,
             msrp, max_pct_over_msrp, notify_channel, time.time()),
        )


def list_items(active_only=False):
    with get_conn() as conn:
        q = "SELECT * FROM watchlist"
        if active_only:
            q += " WHERE active = 1"
        q += " ORDER BY created_at DESC"
        return [dict(r) for r in conn.execute(q).fetchall()]


def get_item(item_id):
    with get_conn() as conn:
        r = conn.execute("SELECT * FROM watchlist WHERE id = ?", (item_id,)).fetchone()
        return dict(r) if r else None


def update_remaining(item_id, remaining_qty):
    with get_conn() as conn:
        conn.execute("UPDATE watchlist SET remaining_qty = ? WHERE id = ?", (remaining_qty, item_id))
        if remaining_qty <= 0:
            conn.execute("UPDATE watchlist SET active = 0 WHERE id = ?", (item_id,))


def set_active(item_id, active: bool):
    with get_conn() as conn:
        conn.execute("UPDATE watchlist SET active = ? WHERE id = ?", (1 if active else 0, item_id))


def delete_item(item_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM watchlist WHERE id = ?", (item_id,))
        conn.execute("DELETE FROM status_log WHERE watchlist_id = ?", (item_id,))
        conn.execute("DELETE FROM alerts_sent WHERE watchlist_id = ?", (item_id,))


def log_status(watchlist_id, in_stock, price, over_msrp_pct, ignored_over_price, raw_status):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO status_log
               (watchlist_id, ts, in_stock, price, over_msrp_pct, ignored_over_price, raw_status)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (watchlist_id, time.time(), int(in_stock), price, over_msrp_pct,
             int(ignored_over_price), raw_status),
        )


def latest_status(watchlist_id):
    with get_conn() as conn:
        r = conn.execute(
            "SELECT * FROM status_log WHERE watchlist_id = ? ORDER BY ts DESC LIMIT 1",
            (watchlist_id,),
        ).fetchone()
        return dict(r) if r else None


def recent_alerts(limit=50):
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT alerts_sent.*, watchlist.name FROM alerts_sent
               JOIN watchlist ON watchlist.id = alerts_sent.watchlist_id
               ORDER BY alerts_sent.ts DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def record_alert(watchlist_id, message):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO alerts_sent (watchlist_id, ts, message) VALUES (?, ?, ?)",
            (watchlist_id, time.time(), message),
        )


def add_drop_signal(source, retailer_guess, title, url, kind="chatter"):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO drop_signals (ts, source, retailer_guess, kind, title, url) VALUES (?, ?, ?, ?, ?, ?)",
            (time.time(), source, retailer_guess, kind, title, url),
        )


def signal_already_seen(url):
    with get_conn() as conn:
        row = conn.execute("SELECT id FROM drop_signals WHERE url = ?", (url,)).fetchone()
        return row is not None


def recent_drop_signals(limit=25):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM drop_signals ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_setting(key, default=None):
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key, value):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def all_settings():
    with get_conn() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        return {r["key"]: r["value"] for r in rows}


def restock_pattern(item_id):
    """Pro-tier feature: summarize which day-of-week / hour this item's
    restocks tend to happen, purely from this install's own historical
    polling data — no third-party data involved."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT ts FROM status_log
               WHERE watchlist_id = ? AND in_stock = 1 AND ignored_over_price = 0
               ORDER BY ts ASC""",
            (item_id,),
        ).fetchall()
    if not rows:
        return None

    from datetime import datetime
    from zoneinfo import ZoneInfo
    from collections import Counter

    tz = ZoneInfo("America/Los_Angeles")
    day_counter = Counter()
    hour_counter = Counter()
    # collapse consecutive in-stock polls into single "restock events" so a
    # 40-minute sellout isn't counted 20 times just because we polled often
    last_ts = None
    events = []
    for r in rows:
        ts = r["ts"]
        if last_ts is None or (ts - last_ts) > 3600:
            events.append(ts)
        last_ts = ts

    for ts in events:
        dt = datetime.fromtimestamp(ts, tz)
        day_counter[dt.strftime("%A")] += 1
        hour_counter[dt.hour] += 1

    total = len(events)
    top_days = day_counter.most_common(3)
    top_hours = hour_counter.most_common(3)
    return {
        "total_events": total,
        "top_days": top_days,
        "top_hours": [(f"{h}:00-{h+1}:00 PT", c) for h, c in top_hours],
    }
