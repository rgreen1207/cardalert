from datetime import datetime
from zoneinfo import ZoneInfo
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


def test_should_poll_now_pokemon_center_respects_window(monkeypatch):
    monkeypatch.setattr(scheduler, "pokemon_center_window_open", lambda: False)
    item = {"id": 1000, "retailer": "pokemon_center"}
    assert scheduler.should_poll_now(item) is False
