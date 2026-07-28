"""
Shared fixtures.

Two things every test in this suite relies on:
1. A fresh, isolated SQLite file per test (via `db.DB_PATH` monkeypatch) —
   no test should ever touch a real watchdata.db or leak state to another
   test.
2. The background scheduler loop never actually starts during tests — it
   polls real retailer URLs on a timer, which has no place running during
   a test suite (slow, flaky, and makes outbound requests to sites we
   don't control). `scheduler.start` is stubbed to a no-op everywhere.
   Individual poller functions are tested directly with mocked HTTP
   responses instead — see test_pollers.py.
"""
import sys
import os
import httpx
import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db
import config
import scheduler
import pollers


@pytest_asyncio.fixture(autouse=True)
async def temp_db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test_watchdata.db")
    monkeypatch.setattr(db, "DB_PATH", db_path)
    await db.init_db()
    yield db_path


@pytest.fixture(autouse=True)
def no_background_polling(monkeypatch):
    monkeypatch.setattr(scheduler, "start", lambda: None)
    # Real runs add a small random delay before each request specifically to
    # avoid bursty, identically-timed hits on a retailer — worth having in
    # production, pure overhead in a test suite that runs the same path
    # dozens of times.
    monkeypatch.setattr(scheduler, "JITTER_MAX_SECONDS", 0)


@pytest.fixture(autouse=True)
def reset_scheduler_in_memory_state():
    """scheduler.py tracks a few things in plain module-level dicts
    (_queue_was_live, _last_polled, _last_queue_checked, _consecutive_blocks)
    rather than the database, since they don't need to survive a restart.
    Unlike the DB, which gets a fresh file per test via temp_db above,
    these dicts persist across tests by default — and since each test's
    fresh DB restarts its own AUTOINCREMENT ids from 1, a retailer_id of 1
    in one test can collide with a completely unrelated retailer_id of 1
    in a later test, leaking state between them. Clearing these before
    every test closes that gap."""
    scheduler._queue_was_live.clear()
    scheduler._last_polled.clear()
    scheduler._last_queue_checked.clear()
    scheduler._consecutive_blocks.clear()
    scheduler._retailer_semaphores.clear()
    yield


class MockAsyncSession:
    """Stand-in for curl_cffi.requests.AsyncSession, installed as
    pollers.AsyncSession for every test. Tests configure `.get_fn`/
    `.head_fn` to a plain callable(url, **kwargs) -> response-like object
    (or one that raises) — the same shape `pollers.requests.get`/`.head`
    mocks used before pollers.py went async. Use set_poller_get/
    set_poller_head below rather than touching this directly."""
    get_fn = None
    head_fn = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, **kwargs):
        return self.get_fn(url, **kwargs)

    async def head(self, url, **kwargs):
        return self.head_fn(url, **kwargs)


_mock_session = MockAsyncSession()


def set_poller_get(fn):
    _mock_session.get_fn = fn


def set_poller_head(fn):
    _mock_session.head_fn = fn


@pytest.fixture(autouse=True)
def _install_mock_async_session(monkeypatch):
    _mock_session.get_fn = None
    _mock_session.head_fn = None
    monkeypatch.setattr(pollers, "AsyncSession", lambda: _mock_session)
    yield


class MockHttpxClient:
    """Stand-in for httpx.AsyncClient, installed globally (fx.py,
    notifier.py, and signals.py all just `import httpx` and call
    `httpx.AsyncClient(...)`, so one patch on the httpx module covers all
    three). Tests configure `.get_fn`/`.post_fn` the same way as
    MockAsyncSession above — see set_httpx_get/set_httpx_post."""
    get_fn = None
    post_fn = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, **kwargs):
        return self.get_fn(url, **kwargs)

    async def post(self, url, **kwargs):
        return self.post_fn(url, **kwargs)


_mock_httpx_client = MockHttpxClient()


def set_httpx_get(fn):
    _mock_httpx_client.get_fn = fn


def set_httpx_post(fn):
    _mock_httpx_client.post_fn = fn


@pytest.fixture(autouse=True)
def _install_mock_httpx_client(monkeypatch):
    _mock_httpx_client.get_fn = None
    _mock_httpx_client.post_fn = None
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: _mock_httpx_client)
    yield


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
            raise httpx.HTTPError(f"{self.status_code} error")


@pytest.fixture
def fake_response():
    return FakeResponse
