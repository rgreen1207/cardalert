import time
import db


def test_add_and_list_item():
    db.add_item("Test SPC", "pokemon", "target", "1011209279", "https://target.com/x",
                target_qty=2, msrp=119.99, max_pct_over_msrp=15, notify_channel="discord,ntfy")
    items = db.list_items()
    assert len(items) == 1
    item = items[0]
    assert item["name"] == "Test SPC"
    assert item["game"] == "pokemon"
    assert item["remaining_qty"] == 2  # starts equal to target_qty
    assert item["notify_channel"] == "discord,ntfy"
    assert item["active"] == 1


def test_update_remaining_deactivates_at_zero():
    db.add_item("Item", "pokemon", "target", "123", "", target_qty=1, msrp=10, max_pct_over_msrp=0)
    item_id = db.list_items()[0]["id"]
    db.update_remaining(item_id, 0)
    item = db.get_item(item_id)
    assert item["remaining_qty"] == 0
    assert item["active"] == 0  # hitting zero auto-deactivates


def test_set_active_pause_resume():
    db.add_item("Item", "pokemon", "target", "123", "", target_qty=1, msrp=10, max_pct_over_msrp=0)
    item_id = db.list_items()[0]["id"]
    db.set_active(item_id, False)
    assert db.get_item(item_id)["active"] == 0
    db.set_active(item_id, True)
    assert db.get_item(item_id)["active"] == 1


def test_delete_item_removes_related_rows():
    db.add_item("Item", "pokemon", "target", "123", "", target_qty=1, msrp=10, max_pct_over_msrp=0)
    item_id = db.list_items()[0]["id"]
    db.log_status(item_id, in_stock=True, price=15.0, over_msrp_pct=50, ignored_over_price=True, raw_status="AVAILABLE")
    db.record_alert(item_id, "test alert")
    db.delete_item(item_id)
    assert db.list_items() == []
    assert db.latest_status(item_id) is None
    assert db.recent_alerts() == []


def test_latest_status_returns_most_recent():
    db.add_item("Item", "pokemon", "target", "123", "", target_qty=1, msrp=10, max_pct_over_msrp=0)
    item_id = db.list_items()[0]["id"]
    db.log_status(item_id, in_stock=False, price=None, over_msrp_pct=None, ignored_over_price=False, raw_status="SOLD_OUT")
    db.log_status(item_id, in_stock=True, price=12.0, over_msrp_pct=20, ignored_over_price=False, raw_status="AVAILABLE")
    latest = db.latest_status(item_id)
    assert latest["raw_status"] == "AVAILABLE"
    assert latest["price"] == 12.0


def test_settings_get_set_roundtrip():
    assert db.get_setting("nonexistent_key") is None
    assert db.get_setting("nonexistent_key", "default") == "default"
    db.set_setting("discord_webhook_url", "https://discord.com/api/webhooks/abc")
    assert db.get_setting("discord_webhook_url") == "https://discord.com/api/webhooks/abc"
    # overwrite
    db.set_setting("discord_webhook_url", "https://discord.com/api/webhooks/xyz")
    assert db.get_setting("discord_webhook_url") == "https://discord.com/api/webhooks/xyz"


def test_all_settings():
    db.set_setting("a", "1")
    db.set_setting("b", "2")
    result = db.all_settings()
    assert result["a"] == "1"
    assert result["b"] == "2"


def test_signal_dedupe():
    db.add_drop_signal("r/PokemonTCG", "Target", "Restock live now!", "https://reddit.com/x", kind="chatter")
    assert db.signal_already_seen("https://reddit.com/x") is True
    assert db.signal_already_seen("https://reddit.com/y") is False


def test_restock_pattern_no_history_returns_none():
    db.add_item("Item", "pokemon", "target", "123", "", target_qty=1, msrp=10, max_pct_over_msrp=0)
    item_id = db.list_items()[0]["id"]
    assert db.restock_pattern(item_id) is None


def test_restock_pattern_collapses_consecutive_polls():
    db.add_item("Item", "pokemon", "target", "123", "", target_qty=1, msrp=10, max_pct_over_msrp=0)
    item_id = db.list_items()[0]["id"]
    # Simulate the same restock event being polled 3 times within an hour —
    # should collapse into a single event, not three.
    now = time.time()
    with db.get_conn() as conn:
        for offset in (0, 300, 600):  # same event, 5 and 10 min apart
            conn.execute(
                "INSERT INTO status_log (watchlist_id, ts, in_stock, price, over_msrp_pct, ignored_over_price, raw_status) "
                "VALUES (?, ?, 1, 10.0, 0, 0, 'AVAILABLE')",
                (item_id, now - 7200 + offset),
            )
        # A second, separate event: ~110 minutes after the last poll of the
        # first cluster, well past the 1-hour collapse window.
        conn.execute(
            "INSERT INTO status_log (watchlist_id, ts, in_stock, price, over_msrp_pct, ignored_over_price, raw_status) "
            "VALUES (?, ?, 1, 10.0, 0, 0, 'AVAILABLE')",
            (item_id, now),
        )
    pattern = db.restock_pattern(item_id)
    assert pattern is not None
    assert pattern["total_events"] == 2


def test_schema_migration_adds_game_and_notify_channel_columns():
    with db.get_conn() as conn:
        cols = [c["name"] for c in conn.execute("PRAGMA table_info(watchlist)").fetchall()]
    assert "game" in cols
    assert "notify_channel" in cols


def test_db_file_permissions_are_owner_only():
    import stat
    import os as _os
    st = _os.stat(db.DB_PATH)
    mode = stat.S_IMODE(st.st_mode)
    assert mode == 0o600
