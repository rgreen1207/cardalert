"""
SQLite data layer.

Data model: a `product` is the thing you're chasing (a name, a game, a
target quantity, a max price). Each product can have one or more
`product_retailers` attached to it, one row per retailer you want it
checked at (Target, Amazon, a local shop, etc). Polling and alerting both
happen at the product_retailer level, so if you've attached both Target
and Amazon to the same product, each is checked and alerted on
independently, one going in stock doesn't affect the other.
"""
import sqlite3
import time
import os
from contextlib import contextmanager

DB_PATH = "watchdata.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    game TEXT NOT NULL DEFAULT 'pokemon',
    target_qty INTEGER NOT NULL DEFAULT 1,
    remaining_qty INTEGER NOT NULL DEFAULT 1,
    msrp REAL,
    max_pct_over_msrp REAL NOT NULL DEFAULT 0,
    notify_channel TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS product_retailers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id),
    retailer TEXT NOT NULL,
    identifier TEXT NOT NULL,
    product_url TEXT
);

CREATE TABLE IF NOT EXISTS status_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_retailer_id INTEGER NOT NULL,
    ts REAL NOT NULL,
    in_stock INTEGER NOT NULL,
    price REAL,
    over_msrp_pct REAL,
    ignored_over_price INTEGER NOT NULL DEFAULT 0,
    raw_status TEXT
);

CREATE TABLE IF NOT EXISTS alerts_sent (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    product_retailer_id INTEGER,
    ts REAL NOT NULL,
    message TEXT NOT NULL
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
    kind TEXT NOT NULL DEFAULT 'chatter',
    title TEXT NOT NULL,
    url TEXT
);
"""


@contextmanager
def get_conn():
    # timeout=10 makes SQLite wait up to 10s for a lock instead of raising
    # immediately — the scheduler's background thread writes to this DB
    # continuously (every poll logs a status row) while web requests read
    # and write concurrently, so some contention is normal, not a bug.
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
        _lock_down_wal_sidecar_files()


def _lock_down_wal_sidecar_files():
    # WAL mode creates -wal/-shm files alongside the main DB file. SQLite
    # creates them with the process's default umask, not matching the 600
    # we set on the main file — closing that gap here since they briefly
    # hold the same credential data during write activity.
    for suffix in ("-wal", "-shm"):
        path = DB_PATH + suffix
        if os.path.exists(path):
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass


CURRENT_SCHEMA_VERSION = 3


def init_db():
    with get_conn() as conn:
        # WAL mode lets readers and writers avoid blocking each other in
        # most cases — a much better fit here than the default rollback
        # journal, since the scheduler writes continuously in its own
        # thread while web requests read/write on theirs. This setting is
        # stored in the database file itself, so it only needs setting
        # once, but PRAGMA calls are cheap and idempotent, so no harm in
        # it running on every startup.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
        row = conn.execute("SELECT version FROM schema_version").fetchone()
        if row is None:
            # Distinguish a genuinely fresh DB from an old install that
            # predates the schema_version table entirely — the latter
            # needs to actually run the migration, not get stamped as
            # already current.
            tables = [r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()]
            starting_version = 0 if "watchlist" in tables else CURRENT_SCHEMA_VERSION
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (starting_version,))
        _run_migrations(conn)
    try:
        os.chmod(DB_PATH, 0o600)  # DB stores credentials via the settings table, owner-read-only
    except OSError:
        pass


def _run_migrations(conn):
    """Numbered migrations. Add a new block + bump CURRENT_SCHEMA_VERSION
    when the schema changes — never edit the SCHEMA string in a way that
    breaks existing installs' data."""
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    version = row["version"] if row else 0

    if version < 3:
        tables = [r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        if "watchlist" in tables:
            _migrate_watchlist_to_products(conn)
        conn.execute("UPDATE schema_version SET version = 3")


def _migrate_watchlist_to_products(conn):
    """One-time migration from the old single-retailer-per-item model.
    Each old watchlist row becomes one product with exactly one attached
    retailer, preserving the same id so anything referencing the old id
    (status_log, alerts_sent) can be remapped without guessing."""
    old_rows = conn.execute("SELECT * FROM watchlist").fetchall()

    # CREATE TABLE IF NOT EXISTS silently no-ops if status_log/alerts_sent
    # already exist with the OLD column set (watchlist_id, no
    # product_retailer_id/product_id) — add what's missing before trying
    # to write to those columns below.
    status_cols = [c["name"] for c in conn.execute("PRAGMA table_info(status_log)").fetchall()]
    if "product_retailer_id" not in status_cols:
        conn.execute("ALTER TABLE status_log ADD COLUMN product_retailer_id INTEGER")
    alert_cols = [c["name"] for c in conn.execute("PRAGMA table_info(alerts_sent)").fetchall()]
    if "product_id" not in alert_cols:
        conn.execute("ALTER TABLE alerts_sent ADD COLUMN product_id INTEGER")
    if "product_retailer_id" not in alert_cols:
        conn.execute("ALTER TABLE alerts_sent ADD COLUMN product_retailer_id INTEGER")

    if not old_rows:
        return

    retailer_id_map = {}  # old watchlist.id -> new product_retailers.id
    for r in old_rows:
        row_keys = r.keys()
        game = r["game"] if "game" in row_keys and r["game"] else "pokemon"
        notify_channel = r["notify_channel"] if "notify_channel" in row_keys and r["notify_channel"] else ""
        conn.execute(
            """INSERT INTO products
               (id, name, game, target_qty, remaining_qty, msrp,
                max_pct_over_msrp, notify_channel, active, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (r["id"], r["name"], game, r["target_qty"], r["remaining_qty"],
             r["msrp"], r["max_pct_over_msrp"], notify_channel,
             r["active"], r["created_at"]),
        )
        cur = conn.execute(
            "INSERT INTO product_retailers (product_id, retailer, identifier, product_url) "
            "VALUES (?, ?, ?, ?)",
            (r["id"], r["retailer"], r["identifier"], r["product_url"]),
        )
        retailer_id_map[r["id"]] = cur.lastrowid

    old_status_cols = [c["name"] for c in conn.execute("PRAGMA table_info(status_log)").fetchall()]
    if "watchlist_id" in old_status_cols:
        for old_id, new_retailer_id in retailer_id_map.items():
            conn.execute(
                "UPDATE status_log SET product_retailer_id = ? WHERE watchlist_id = ?",
                (new_retailer_id, old_id),
            )

    old_alert_cols = [c["name"] for c in conn.execute("PRAGMA table_info(alerts_sent)").fetchall()]
    if "watchlist_id" in old_alert_cols:
        for old_id, new_retailer_id in retailer_id_map.items():
            conn.execute(
                "UPDATE alerts_sent SET product_id = ?, product_retailer_id = ? WHERE watchlist_id = ?",
                (old_id, new_retailer_id, old_id),
            )

    conn.execute("ALTER TABLE watchlist RENAME TO watchlist_migrated_backup")


# --- Products ---

def add_product(name, game, target_qty, msrp, max_pct_over_msrp, notify_channel) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO products
               (name, game, target_qty, remaining_qty, msrp, max_pct_over_msrp,
                notify_channel, active, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)""",
            (name, game, target_qty, target_qty, msrp, max_pct_over_msrp,
             notify_channel, time.time()),
        )
        return cur.lastrowid


def add_product_with_retailers(name, game, target_qty, msrp, max_pct_over_msrp,
                                notify_channel, retailers: list) -> int:
    """retailers: list of {"retailer": ..., "identifier": ..., "product_url": ...}"""
    product_id = add_product(name, game, target_qty, msrp, max_pct_over_msrp, notify_channel)
    for r in retailers:
        add_retailer(product_id, r["retailer"], r["identifier"], r.get("product_url", ""))
    return product_id


def get_product(product_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        return dict(row) if row else None


def get_product_with_retailers(product_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        if not row:
            return None
        product = dict(row)
        product["retailers"] = _retailers_for_product(conn, product_id)
        return product


def list_products(active_only=False):
    with get_conn() as conn:
        q = "SELECT * FROM products"
        if active_only:
            q += " WHERE active = 1"
        q += " ORDER BY created_at DESC"
        products = [dict(r) for r in conn.execute(q).fetchall()]
        for p in products:
            p["retailers"] = _retailers_for_product(conn, p["id"])
        return products


def _retailers_for_product(conn, product_id):
    rows = conn.execute(
        "SELECT * FROM product_retailers WHERE product_id = ? ORDER BY id", (product_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def update_product(product_id, name, game, target_qty, msrp, max_pct_over_msrp, notify_channel):
    """Editing a product. If target_qty changes, preserves how many
    you've already logged as purchased rather than resetting the
    countdown — e.g. if you'd bought 1 of an old target of 2 and raise the
    target to 3, remaining becomes 2 (3 - 1 already bought), not 3."""
    existing = get_product(product_id)
    if not existing:
        return
    already_purchased = max(0, existing["target_qty"] - existing["remaining_qty"])
    new_remaining = max(0, target_qty - already_purchased)
    with get_conn() as conn:
        conn.execute(
            """UPDATE products SET name = ?, game = ?, target_qty = ?, remaining_qty = ?,
               msrp = ?, max_pct_over_msrp = ?, notify_channel = ?,
               active = CASE WHEN ? > 0 THEN 1 ELSE 0 END
               WHERE id = ?""",
            (name, game, target_qty, new_remaining, msrp, max_pct_over_msrp,
             notify_channel, new_remaining, product_id),
        )


def set_product_active(product_id, active: bool):
    with get_conn() as conn:
        conn.execute("UPDATE products SET active = ? WHERE id = ?", (1 if active else 0, product_id))


def update_remaining(product_id, remaining_qty):
    with get_conn() as conn:
        conn.execute("UPDATE products SET remaining_qty = ? WHERE id = ?", (remaining_qty, product_id))
        if remaining_qty <= 0:
            conn.execute("UPDATE products SET active = 0 WHERE id = ?", (product_id,))


def delete_product(product_id):
    with get_conn() as conn:
        retailer_ids = [r["id"] for r in conn.execute(
            "SELECT id FROM product_retailers WHERE product_id = ?", (product_id,)
        ).fetchall()]
        for rid in retailer_ids:
            conn.execute("DELETE FROM status_log WHERE product_retailer_id = ?", (rid,))
        conn.execute("DELETE FROM product_retailers WHERE product_id = ?", (product_id,))
        conn.execute("DELETE FROM alerts_sent WHERE product_id = ?", (product_id,))
        conn.execute("DELETE FROM products WHERE id = ?", (product_id,))


# --- Product retailers (the actual thing that gets polled) ---

def add_retailer(product_id, retailer, identifier, product_url="") -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO product_retailers (product_id, retailer, identifier, product_url) "
            "VALUES (?, ?, ?, ?)",
            (product_id, retailer, identifier, product_url),
        )
        return cur.lastrowid


def get_retailer(product_retailer_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM product_retailers WHERE id = ?", (product_retailer_id,)
        ).fetchone()
        return dict(row) if row else None


def remove_retailer(product_retailer_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM status_log WHERE product_retailer_id = ?", (product_retailer_id,))
        conn.execute("DELETE FROM product_retailers WHERE id = ?", (product_retailer_id,))


def list_retailers_for_polling(active_only=True):
    """Flat list of (product, retailer) pairings to poll, each annotated
    with its parent product's fields (msrp, max_pct_over_msrp,
    notify_channel, name, game, target_qty, remaining_qty, active) so the
    scheduler doesn't need a second lookup per row."""
    with get_conn() as conn:
        q = """
            SELECT product_retailers.id AS id,
                   product_retailers.product_id AS product_id,
                   product_retailers.retailer AS retailer,
                   product_retailers.identifier AS identifier,
                   product_retailers.product_url AS product_url,
                   products.name AS name,
                   products.game AS game,
                   products.target_qty AS target_qty,
                   products.remaining_qty AS remaining_qty,
                   products.msrp AS msrp,
                   products.max_pct_over_msrp AS max_pct_over_msrp,
                   products.notify_channel AS notify_channel,
                   products.active AS active
            FROM product_retailers
            JOIN products ON products.id = product_retailers.product_id
        """
        if active_only:
            q += " WHERE products.active = 1"
        return [dict(r) for r in conn.execute(q).fetchall()]


# --- Status log (per product_retailer) ---

def log_status(product_retailer_id, in_stock, price, over_msrp_pct, ignored_over_price, raw_status):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO status_log
               (product_retailer_id, ts, in_stock, price, over_msrp_pct, ignored_over_price, raw_status)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (product_retailer_id, time.time(), int(in_stock), price, over_msrp_pct,
             int(ignored_over_price), raw_status),
        )


def latest_status(product_retailer_id):
    with get_conn() as conn:
        r = conn.execute(
            "SELECT * FROM status_log WHERE product_retailer_id = ? ORDER BY ts DESC LIMIT 1",
            (product_retailer_id,),
        ).fetchone()
        return dict(r) if r else None


def restock_pattern(product_retailer_id):
    """Pro-tier feature note: there is no pro tier, this is free for
    everyone. Summarizes which day-of-week / hour this specific
    (product, retailer) pairing tends to restock, purely from this
    install's own historical polling data."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT ts FROM status_log
               WHERE product_retailer_id = ? AND in_stock = 1 AND ignored_over_price = 0
               ORDER BY ts ASC""",
            (product_retailer_id,),
        ).fetchall()
    if not rows:
        return None

    from datetime import datetime
    from zoneinfo import ZoneInfo
    from collections import Counter

    tz = ZoneInfo("America/Los_Angeles")
    day_counter = Counter()
    hour_counter = Counter()
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


# --- Alerts ---

def record_alert(product_id, message, product_retailer_id=None):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO alerts_sent (product_id, product_retailer_id, ts, message) VALUES (?, ?, ?, ?)",
            (product_id, product_retailer_id, time.time(), message),
        )


def recent_alerts(limit=50):
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT alerts_sent.*, products.name FROM alerts_sent
               JOIN products ON products.id = alerts_sent.product_id
               ORDER BY alerts_sent.ts DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def last_alert_time_for_retailer(product_retailer_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT ts FROM alerts_sent WHERE product_retailer_id = ? ORDER BY ts DESC LIMIT 1",
            (product_retailer_id,),
        ).fetchone()
        return row["ts"] if row else None


def purge_old_alerts(older_than_days=7):
    cutoff = time.time() - (older_than_days * 86400)
    with get_conn() as conn:
        conn.execute("DELETE FROM alerts_sent WHERE ts < ?", (cutoff,))


# --- Settings (key/value, unrelated to products) ---

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


# --- Drop signals (restock chatter/forecasts, unrelated to products) ---

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
