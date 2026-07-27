from datetime import datetime
from zoneinfo import ZoneInfo
import time
import scheduler


def test_channels_for_splits_csv():
    item = {"notify_channel": "discord,ntfy"}
    assert scheduler._channels_for(item) == ["discord", "ntfy"]


def test_channels_for_handles_empty():
    assert scheduler._channels_for({"notify_channel": ""}) == []
    assert scheduler._channels_for({}) == []


def test_channels_for_strips_whitespace():
    item = {"notify_channel": "discord, ntfy , pushover"}
    assert scheduler._channels_for(item) == ["discord", "ntfy", "pushover"]


def test_pokemon_center_window_open_during_allowed_time(monkeypatch):
    # Tuesday 10am PST — inside Mon-Thu 8am-1pm window
    fake_now = datetime(2026, 7, 28, 10, 0, tzinfo=ZoneInfo("America/Los_Angeles"))

    class FakeDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fake_now

    monkeypatch.setattr(scheduler, "datetime", FakeDatetime)
    assert scheduler.pokemon_center_window_open() is True


def test_pokemon_center_window_closed_on_friday(monkeypatch):
    # Friday — outside Mon-Thu window entirely
    fake_now = datetime(2026, 7, 31, 10, 0, tzinfo=ZoneInfo("America/Los_Angeles"))

    class FakeDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fake_now

    monkeypatch.setattr(scheduler, "datetime", FakeDatetime)
    assert scheduler.pokemon_center_window_open() is False


def test_pokemon_center_window_closed_outside_hours(monkeypatch):
    # Tuesday 6pm PST — right day, wrong hour
    fake_now = datetime(2026, 7, 28, 18, 0, tzinfo=ZoneInfo("America/Los_Angeles"))

    class FakeDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fake_now

    monkeypatch.setattr(scheduler, "datetime", FakeDatetime)
    assert scheduler.pokemon_center_window_open() is False


def test_should_poll_now_respects_interval():
    item = {"id": 999, "retailer": "target"}
    # never polled before -> should poll
    assert scheduler.should_poll_now(item) is True
    scheduler._last_polled[999] = __import__("time").time()
    # just polled -> should not poll again immediately
    assert scheduler.should_poll_now(item) is False


def test_should_poll_now_pokemon_center_uses_faster_interval_inside_window(monkeypatch):
    monkeypatch.setattr(scheduler, "pokemon_center_window_open", lambda: True)
    item = {"id": 1000, "retailer": "pokemon_center"}
    scheduler._last_polled[1000] = time.time() - 601  # just over the in-window 10-min interval
    assert scheduler.should_poll_now(item) is True
    scheduler._last_polled[1000] = time.time() - 100  # well under it
    assert scheduler.should_poll_now(item) is False


def test_should_poll_now_pokemon_center_never_fully_blocked_outside_window(monkeypatch):
    """Regression guard: 'always alert when the queue is live' requires
    polling to never fully stop outside the primary window — it used to
    return False outright, meaning a queue opening outside Mon-Thu
    8am-1pm PST could never be detected at all. Now polls at a slower
    (30 min) cadence instead of not polling."""
    monkeypatch.setattr(scheduler, "pokemon_center_window_open", lambda: False)
    item = {"id": 1001, "retailer": "pokemon_center"}
    scheduler._last_polled[1001] = time.time() - 1801  # just over the off-window 30-min interval
    assert scheduler.should_poll_now(item) is True
    scheduler._last_polled[1001] = time.time() - 100  # well under it — too soon
    assert scheduler.should_poll_now(item) is False


def test_queue_live_dispatches_alert_and_records_it(monkeypatch):
    """End-to-end regression guard: this path had zero test coverage
    before, despite existing in the code. Confirms that when a poller
    reports raw_status QUEUE_LIVE, an alert actually dispatches to the
    retailer's configured channel(s) and gets recorded — this is the
    'always alert when the Pokémon Center queue is live' behavior."""
    import db
    import pollers
    import notifier

    pid = db.add_product("Charizard ETB", "pokemon", 1, 49.99, 0, "discord")
    db.add_retailer(pid, "pokemon_center", "https://pokemoncenter.com/product/x", "")
    retailer_row = db.list_retailers_for_polling()[0]

    dispatched = []
    monkeypatch.setitem(pollers.POLLERS, "pokemon_center",
                         lambda identifier: {"in_stock": False, "price": None, "raw_status": "QUEUE_LIVE"})
    monkeypatch.setattr(notifier, "dispatch", lambda msg, ch: dispatched.append((ch, msg)))

    scheduler.poll_one(retailer_row)

    assert dispatched == [("discord", dispatched[0][1])]
    assert "queue just went LIVE" in dispatched[0][1]
    alerts = db.recent_alerts()
    assert len(alerts) == 1
    assert "queue just went LIVE" in alerts[0]["message"]


def test_queue_live_fires_again_on_every_poll_while_still_live(monkeypatch):
    """'Always' means no suppression window for this alert type, unlike
    restock alerts which dedupe for 30 minutes — a queue that's still
    open on the next poll should alert again, not go silent."""
    import db
    import pollers
    import notifier

    pid = db.add_product("Charizard ETB", "pokemon", 1, 49.99, 0, "discord")
    db.add_retailer(pid, "pokemon_center", "https://pokemoncenter.com/product/x", "")
    retailer_row = db.list_retailers_for_polling()[0]

    dispatched = []
    monkeypatch.setitem(pollers.POLLERS, "pokemon_center",
                         lambda identifier: {"in_stock": False, "price": None, "raw_status": "QUEUE_LIVE"})
    monkeypatch.setattr(notifier, "dispatch", lambda msg, ch: dispatched.append((ch, msg)))

    scheduler.poll_one(retailer_row)
    scheduler.poll_one(retailer_row)
    scheduler.poll_one(retailer_row)

    assert len(dispatched) == 3
    assert len(db.recent_alerts()) == 3


def test_poll_one_logs_generic_exception_to_console_and_stores_error_detail(monkeypatch, capsys):
    """Regression guard: the actual error should reach console + the API
    (for inspection via a browser's Network tab), while the dashboard
    only ever shows a masked, generic label. Previously an unhandled
    exception during polling produced zero console output at all."""
    import db
    import pollers

    pid = db.add_product("Item", "pokemon", 1, 10, 0, "")
    db.add_retailer(pid, "target", "123", "")
    retailer_row = db.list_retailers_for_polling()[0]

    def raise_error(identifier):
        raise ConnectionError("connection reset by peer")

    monkeypatch.setitem(pollers.POLLERS, "target", raise_error)
    scheduler.poll_one(retailer_row)

    captured = capsys.readouterr()
    assert "connection reset by peer" in captured.out

    status = db.latest_status(retailer_row["id"])
    assert "connection reset by peer" in status["error_detail"]
    assert status["raw_status"].startswith("ERROR:")


def test_poll_one_logs_poller_provided_error_detail_to_console(monkeypatch, capsys):
    """Same guarantee, but for pollers that return a clean categorized
    status (e.g. Target's BLOCKED_OR_KEY_INVALID) instead of raising —
    the real HTTP detail behind that category should still reach the
    console and get stored, not just the generic category."""
    import db
    import pollers

    pid = db.add_product("Item", "pokemon", 1, 10, 0, "")
    db.add_retailer(pid, "target", "123", "")
    retailer_row = db.list_retailers_for_polling()[0]

    monkeypatch.setitem(pollers.POLLERS, "target", lambda identifier: {
        "in_stock": False, "price": None, "raw_status": "BLOCKED_OR_KEY_INVALID",
        "error_detail": "HTTP 403 from Target: Forbidden by WAF rule 12345",
    })
    scheduler.poll_one(retailer_row)

    captured = capsys.readouterr()
    assert "Forbidden by WAF rule 12345" in captured.out

    status = db.latest_status(retailer_row["id"])
    assert status["error_detail"] == "HTTP 403 from Target: Forbidden by WAF rule 12345"
    assert status["raw_status"] == "BLOCKED_OR_KEY_INVALID"
