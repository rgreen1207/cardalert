"""
Shared fixtures.

Two things every test in this suite relies on:
1. A fresh, isolated SQLite file per test (via `db.DB_PATH` monkeypatch) —
   no test should ever touch a real watchdata.db or leak state to another
   test.
2. The background scheduler thread never actually starts during tests —
   it polls real retailer URLs on a timer, which has no place running
   during a test suite (slow, flaky, and makes outbound requests to sites
   we don't control). `scheduler.start_background_thread` is stubbed to a
   no-op everywhere. Individual poller functions are tested directly with
   mocked HTTP responses instead — see test_pollers.py.
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db
import config
import scheduler


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test_watchdata.db")
    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.init_db()
    yield db_path


@pytest.fixture(autouse=True)
def no_background_polling(monkeypatch):
    monkeypatch.setattr(scheduler, "start_background_thread", lambda: None)


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    import app as app_module
    with TestClient(app_module.app) as c:
        yield c


class FakeResponse:
    """Minimal stand-in for requests.Response, used across poller tests."""

    def __init__(self, text="", status_code=200, json_data=None, url=""):
        self.text = text
        self.status_code = status_code
        self._json_data = json_data
        self.url = url or "https://example.com/fake"

    def json(self):
        if self._json_data is None:
            raise ValueError("No JSON body on this fake response")
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"{self.status_code} error")


@pytest.fixture
def fake_response():
    return FakeResponse
