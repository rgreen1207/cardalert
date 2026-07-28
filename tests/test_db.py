import asyncio
import time
import sqlite3
import os
import db


async def test_add_product_with_retailers():
    pid = await db.add_product_with_retailers(
        "Test SPC", "pokemon", 2, 119.99, 15, "discord,ntfy",
        [{"retailer": "target", "identifier": "123", "product_url": ""},
         {"retailer": "amazon", "identifier": "B0D7QJXK9P", "product_url": ""}],
    )
    products = await db.list_products()
    assert len(products) == 1
    product = products[0]
    assert product["id"] == pid
    assert product["name"] == "Test SPC"
    assert product["remaining_qty"] == 2
    assert len(product["retailers"]) == 2
    assert {r["retailer"] for r in product["retailers"]} == {"target", "amazon"}


async def test_add_retailer_to_existing_product():
    pid = await db.add_product("Item", "pokemon", 1, 10, 0, "")
    await db.add_retailer(pid, "target", "123", "")
    await db.add_retailer(pid, "walmart", "https://walmart.com/ip/456", "")
    product = await db.get_product_with_retailers(pid)
    assert len(product["retailers"]) == 2


async def test_remove_retailer_leaves_product_and_other_retailers_intact():
    pid = await db.add_product("Item", "pokemon", 1, 10, 0, "")
    r1 = await db.add_retailer(pid, "target", "123", "")
    r2 = await db.add_retailer(pid, "amazon", "456", "")
    await db.remove_retailer(r1)
    product = await db.get_product_with_retailers(pid)
    assert len(product["retailers"]) == 1
    assert product["retailers"][0]["id"] == r2


async def test_list_retailers_for_polling_flattens_across_products():
    p1 = await db.add_product("Item 1", "pokemon", 1, 10, 0, "")
    await db.add_retailer(p1, "target", "1", "")
    await db.add_retailer(p1, "amazon", "2", "")
    p2 = await db.add_product("Item 2", "mtg", 1, 20, 0, "")
    await db.add_retailer(p2, "walmart", "3", "")
    rows = await db.list_retailers_for_polling()
    assert len(rows) == 3
    assert all("name" in r and "msrp" in r for r in rows)  # joined product fields present


async def test_list_retailers_for_polling_respects_active_only():
    pid = await db.add_product("Item", "pokemon", 1, 10, 0, "")
    await db.add_retailer(pid, "target", "1", "")
    await db.set_product_active(pid, False)
    assert await db.list_retailers_for_polling(active_only=True) == []
    assert len(await db.list_retailers_for_polling(active_only=False)) == 1


async def test_update_remaining_deactivates_at_zero():
    pid = await db.add_product("Item", "pokemon", 1, 10, 0, "")
    await db.update_remaining(pid, 0)
    product = await db.get_product(pid)
    assert product["remaining_qty"] == 0
    assert product["active"] == 0


async def test_set_product_active_pause_resume():
    pid = await db.add_product("Item", "pokemon", 1, 10, 0, "")
    await db.set_product_active(pid, False)
    assert (await db.get_product(pid))["active"] == 0
    await db.set_product_active(pid, True)
    assert (await db.get_product(pid))["active"] == 1


async def test_delete_product_removes_retailers_and_related_rows():
    pid = await db.add_product("Item", "pokemon", 1, 10, 0, "")
    rid = await db.add_retailer(pid, "target", "123", "")
    await db.log_status(rid, in_stock=True, price=15.0, over_msrp_pct=50, ignored_over_price=True, raw_status="AVAILABLE")
    await db.record_alert(pid, "test alert", product_retailer_id=rid)
    await db.delete_product(pid)
    assert await db.list_products() == []
    assert await db.get_retailer(rid) is None
    assert await db.latest_status(rid) is None
    assert await db.recent_alerts() == []


async def test_latest_status_returns_most_recent():
    pid = await db.add_product("Item", "pokemon", 1, 10, 0, "")
    rid = await db.add_retailer(pid, "target", "123", "")
    await db.log_status(rid, in_stock=False, price=None, over_msrp_pct=None, ignored_over_price=False, raw_status="SOLD_OUT")
    await db.log_status(rid, in_stock=True, price=12.0, over_msrp_pct=20, ignored_over_price=False, raw_status="AVAILABLE")
    latest = await db.latest_status(rid)
    assert latest["raw_status"] == "AVAILABLE"
    assert latest["price"] == 12.0


async def test_settings_get_set_roundtrip():
    assert await db.get_setting("nonexistent_key") is None
    assert await db.get_setting("nonexistent_key", "default") == "default"
    await db.set_setting("discord_webhook_url", "https://discord.com/api/webhooks/abc")
    assert await db.get_setting("discord_webhook_url") == "https://discord.com/api/webhooks/abc"
    await db.set_setting("discord_webhook_url", "https://discord.com/api/webhooks/xyz")
    assert await db.get_setting("discord_webhook_url") == "https://discord.com/api/webhooks/xyz"


async def test_all_settings():
    await db.set_setting("a", "1")
    await db.set_setting("b", "2")
    result = await db.all_settings()
    assert result["a"] == "1"
    assert result["b"] == "2"


async def test_signal_dedupe():
    await db.add_drop_signal("r/PokemonTCG", "Target", "Restock live now!", "https://reddit.com/x", kind="chatter")
    assert await db.signal_already_seen("https://reddit.com/x") is True
    assert await db.signal_already_seen("https://reddit.com/y") is False


async def test_restock_pattern_no_history_returns_none():
    pid = await db.add_product("Item", "pokemon", 1, 10, 0, "")
    rid = await db.add_retailer(pid, "target", "123", "")
    assert await db.restock_pattern(rid) is None


async def test_restock_pattern_collapses_consecutive_polls():
    pid = await db.add_product("Item", "pokemon", 1, 10, 0, "")
    rid = await db.add_retailer(pid, "target", "123", "")
    now = time.time()
    async with db.get_conn() as conn:
        for offset in (0, 300, 600):  # same event, 5 and 10 min apart
            await conn.execute(
                "INSERT INTO status_log (product_retailer_id, ts, in_stock, price, over_msrp_pct, ignored_over_price, raw_status) "
                "VALUES (?, ?, 1, 10.0, 0, 0, 'AVAILABLE')",
                (rid, now - 7200 + offset),
            )
        # A second, separate event ~110 minutes after the first cluster
        await conn.execute(
            "INSERT INTO status_log (product_retailer_id, ts, in_stock, price, over_msrp_pct, ignored_over_price, raw_status) "
            "VALUES (?, ?, 1, 10.0, 0, 0, 'AVAILABLE')",
            (rid, now),
        )
    pattern = await db.restock_pattern(rid)
    assert pattern is not None
    assert pattern["total_events"] == 2


async def test_restock_pattern_is_independent_per_retailer():
    """Two retailers on the same product should have independent
    patterns — this is the whole point of the multi-retailer model."""
    pid = await db.add_product("Item", "pokemon", 1, 10, 0, "")
    r_target = await db.add_retailer(pid, "target", "123", "")
    r_amazon = await db.add_retailer(pid, "amazon", "456", "")
    now = time.time()
    async with db.get_conn() as conn:
        await conn.execute(
            "INSERT INTO status_log (product_retailer_id, ts, in_stock, price, over_msrp_pct, ignored_over_price, raw_status) "
            "VALUES (?, ?, 1, 10.0, 0, 0, 'AVAILABLE')", (r_target, now),
        )
    assert await db.restock_pattern(r_target) is not None
    assert await db.restock_pattern(r_amazon) is None  # no history logged for this one


async def test_schema_migration_creates_new_tables():
    async with db.get_conn() as conn:
        cur = await conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r["name"] for r in await cur.fetchall()]
    assert "products" in tables
    assert "product_retailers" in tables


async def test_purge_old_alerts_removes_only_old_ones():
    pid = await db.add_product("Item", "pokemon", 1, 10, 0, "")
    now = time.time()
    async with db.get_conn() as conn:
        await conn.execute("INSERT INTO alerts_sent (product_id, ts, message) VALUES (?, ?, ?)",
                            (pid, now - (10 * 86400), "old alert"))
        await conn.execute("INSERT INTO alerts_sent (product_id, ts, message) VALUES (?, ?, ?)",
                            (pid, now - (2 * 86400), "recent alert"))
    await db.purge_old_alerts(older_than_days=7)
    messages = [a["message"] for a in await db.recent_alerts()]
    assert "recent alert" in messages
    assert "old alert" not in messages


async def test_purge_old_alerts_default_window_is_seven_days():
    pid = await db.add_product("Item", "pokemon", 1, 10, 0, "")
    now = time.time()
    async with db.get_conn() as conn:
        await conn.execute("INSERT INTO alerts_sent (product_id, ts, message) VALUES (?, ?, ?)",
                            (pid, now - (8 * 86400), "should be purged"))
    await db.purge_old_alerts()
    messages = [a["message"] for a in await db.recent_alerts()]
    assert "should be purged" not in messages


async def test_update_product_changes_fields():
    pid = await db.add_product("Original", "pokemon", 1, 10, 0, "discord")
    await db.update_product(pid, "Renamed", "mtg", 2, 25, 5, "ntfy,sms")
    product = await db.get_product(pid)
    assert product["name"] == "Renamed"
    assert product["game"] == "mtg"
    assert product["msrp"] == 25
    assert product["notify_channel"] == "ntfy,sms"


async def test_update_product_preserves_purchase_progress_when_target_increases():
    pid = await db.add_product("Item", "pokemon", 2, 10, 0, "")
    await db.update_remaining(pid, 1)  # bought 1 of 2
    await db.update_product(pid, "Item", "pokemon", 3, 10, 0, "")
    product = await db.get_product(pid)
    assert product["target_qty"] == 3
    assert product["remaining_qty"] == 2  # 3 - (already bought 1) = 2, not reset to 3


async def test_update_product_reactivates_if_remaining_becomes_positive():
    pid = await db.add_product("Item", "pokemon", 1, 10, 0, "")
    await db.update_remaining(pid, 0)  # fully purchased, auto-deactivated
    assert (await db.get_product(pid))["active"] == 0
    await db.update_product(pid, "Item", "pokemon", 3, 10, 0, "")
    product = await db.get_product(pid)
    assert product["remaining_qty"] == 2
    assert product["active"] == 1


async def test_db_file_permissions_are_owner_only():
    import stat
    import os as _os
    st = _os.stat(db.DB_PATH)
    mode = stat.S_IMODE(st.st_mode)
    assert mode == 0o600


async def test_wal_sidecar_files_are_locked_down_when_present():
    """WAL mode creates -wal/-shm files that briefly hold the same
    credential data as the main DB, but SQLite creates them with the
    process's default umask, not matching the main file's 600. Confirms
    that gap is closed whenever those files exist."""
    import stat as _stat
    pid = await db.add_product("Item", "pokemon", 1, 10, 0, "")
    rid = await db.add_retailer(pid, "target", "1", "")
    await db.log_status(rid, in_stock=True, price=10.0, over_msrp_pct=0, ignored_over_price=False, raw_status="AVAILABLE")
    for suffix in ("-wal", "-shm"):
        path = db.DB_PATH + suffix
        if os.path.exists(path):
            mode = _stat.S_IMODE(os.stat(path).st_mode)
            assert mode == 0o600, f"{path} has permissive mode {oct(mode)}"


async def test_wal_mode_is_enabled():
    """WAL mode lets readers (web requests) and the background scheduler's
    writes avoid blocking each other in most cases — the default rollback
    journal is a much worse fit for this app's actual access pattern."""
    async with db.get_conn() as conn:
        cur = await conn.execute("PRAGMA journal_mode")
        row = await cur.fetchone()
    assert row[0].lower() == "wal"


async def test_concurrent_reads_and_writes_do_not_raise():
    """Regression guard for a reported bug: /products intermittently
    500ing. The scheduler writes to status_log continuously while web
    requests read/write concurrently — this simulates that exact pattern
    (concurrent status_log writes, product reads, and settings writes)
    across real OS threads (each running its own event loop) and confirms
    none of it raises 'database is locked' or any other error under real
    contention, not just a mocked one."""
    import threading

    pid = await db.add_product("Item", "pokemon", 1, 10, 0, "")
    rid = await db.add_retailer(pid, "target", "1", "")
    errors = []

    def writer():
        async def _run():
            for _ in range(100):
                try:
                    await db.log_status(rid, in_stock=True, price=10.0, over_msrp_pct=0,
                                         ignored_over_price=False, raw_status="AVAILABLE")
                except Exception as e:
                    errors.append(("writer", e))
        asyncio.run(_run())

    def reader():
        async def _run():
            for _ in range(100):
                try:
                    await db.list_products()
                    await db.latest_status(rid)
                except Exception as e:
                    errors.append(("reader", e))
        asyncio.run(_run())

    def settings_writer():
        async def _run():
            for i in range(100):
                try:
                    await db.set_setting("fx_rates_cache", f'{{"rates":{{"GBP":0.8}},"fetched_at":{i}}}')
                except Exception as e:
                    errors.append(("settings", e))
        asyncio.run(_run())

    threads = [threading.Thread(target=writer), threading.Thread(target=reader),
               threading.Thread(target=reader), threading.Thread(target=settings_writer)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []


async def test_migration_from_old_single_retailer_watchlist(tmp_path, monkeypatch):
    """The actual bug-prone path: an existing install with the OLD
    single-retailer-per-row schema needs its data preserved exactly when
    upgrading to the multi-retailer model — same product name/qty/msrp,
    same retailer attached, same status history, same alert history."""
    old_db_path = str(tmp_path / "old_style.db")
    monkeypatch.setattr(db, "DB_PATH", old_db_path)

    conn = sqlite3.connect(old_db_path)
    conn.execute("""
        CREATE TABLE watchlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            game TEXT NOT NULL DEFAULT 'pokemon',
            retailer TEXT NOT NULL,
            identifier TEXT NOT NULL,
            product_url TEXT,
            target_qty INTEGER NOT NULL DEFAULT 1,
            remaining_qty INTEGER NOT NULL DEFAULT 1,
            msrp REAL,
            max_pct_over_msrp REAL NOT NULL DEFAULT 0,
            notify_channel TEXT NOT NULL DEFAULT 'dashboard',
            active INTEGER NOT NULL DEFAULT 1,
            created_at REAL NOT NULL
        )
    """)
    conn.execute("CREATE TABLE status_log (id INTEGER PRIMARY KEY, watchlist_id INTEGER, ts REAL, "
                 "in_stock INTEGER, price REAL, over_msrp_pct REAL, ignored_over_price INTEGER, raw_status TEXT)")
    conn.execute("CREATE TABLE alerts_sent (id INTEGER PRIMARY KEY, watchlist_id INTEGER, ts REAL, message TEXT)")
    now = time.time()
    conn.execute(
        "INSERT INTO watchlist (id, name, game, retailer, identifier, product_url, target_qty, "
        "remaining_qty, msrp, max_pct_over_msrp, notify_channel, active, created_at) "
        "VALUES (1, 'Old Item', 'pokemon', 'target', '999', '', 2, 1, 50.0, 0, 'discord', 1, ?)",
        (now,),
    )
    conn.execute(
        "INSERT INTO status_log (watchlist_id, ts, in_stock, price, over_msrp_pct, ignored_over_price, raw_status) "
        "VALUES (1, ?, 1, 55.0, 10, 0, 'AVAILABLE')", (now,),
    )
    conn.execute("INSERT INTO alerts_sent (watchlist_id, ts, message) VALUES (1, ?, 'old alert message')", (now,))
    conn.commit()
    conn.close()

    await db.init_db()

    products = await db.list_products()
    assert len(products) == 1
    product = products[0]
    assert product["name"] == "Old Item"
    assert product["target_qty"] == 2
    assert product["remaining_qty"] == 1
    assert product["msrp"] == 50.0
    assert len(product["retailers"]) == 1
    retailer = product["retailers"][0]
    assert retailer["retailer"] == "target"
    assert retailer["identifier"] == "999"

    status = await db.latest_status(retailer["id"])
    assert status is not None
    assert status["raw_status"] == "AVAILABLE"
    assert status["price"] == 55.0

    alerts = await db.recent_alerts()
    assert len(alerts) == 1
    assert alerts[0]["message"] == "old alert message"


async def test_migration_is_idempotent(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(db, "DB_PATH", db_path)
    await db.init_db()
    await db.add_product_with_retailers("Item", "pokemon", 1, 10, 0, "", [{"retailer": "target", "identifier": "1"}])
    assert len(await db.list_products()) == 1
    await db.init_db()  # calling again should not duplicate or error
    assert len(await db.list_products()) == 1
