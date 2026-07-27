import time
import fx
import db


def test_usd_rate_is_always_one_no_network(monkeypatch):
    calls = []
    monkeypatch.setattr(fx.requests, "get", lambda *a, **k: calls.append(1))
    result = fx.get_rate("USD")
    assert result == {"rate": 1.0, "stale": False}
    assert calls == []  # never even tries to fetch for USD


def test_get_rate_fetches_and_caches(monkeypatch, fake_response):
    monkeypatch.setattr(fx.requests, "get", lambda *a, **k: fake_response(
        json_data={"rates": {"GBP": 0.78, "EUR": 0.91}}
    ))
    result = fx.get_rate("GBP")
    assert result == {"rate": 0.78, "stale": False}
    # confirm it actually cached something
    cached = db.get_setting("fx_rates_cache")
    assert cached is not None


def test_get_rate_uses_cache_within_ttl(monkeypatch, fake_response):
    call_count = {"n": 0}

    def fake_get(*a, **k):
        call_count["n"] += 1
        return fake_response(json_data={"rates": {"GBP": 0.78}})

    monkeypatch.setattr(fx.requests, "get", fake_get)
    fx.get_rate("GBP")
    fx.get_rate("GBP")
    fx.get_rate("GBP")
    assert call_count["n"] == 1  # only fetched once, rest served from cache


def test_get_rate_falls_back_to_stale_cache_on_network_failure(monkeypatch, fake_response):
    import requests

    monkeypatch.setattr(fx.requests, "get", lambda *a, **k: fake_response(
        json_data={"rates": {"GBP": 0.78}}
    ))
    fx.get_rate("GBP")  # populate cache

    def raise_error(*a, **k):
        raise requests.RequestException("network down")

    monkeypatch.setattr(fx.requests, "get", raise_error)
    # force cache to look expired
    cache = fx._load_cache()
    cache["fetched_at"] = time.time() - fx.CACHE_TTL_SECONDS - 1
    fx._save_cache(cache["rates"])
    db.set_setting("fx_rates_cache", __import__("json").dumps(
        {"rates": cache["rates"], "fetched_at": time.time() - fx.CACHE_TTL_SECONDS - 1}
    ))
    result = fx.get_rate("GBP")
    assert result["rate"] == 0.78
    assert result["stale"] is True


def test_get_rate_total_failure_falls_back_to_one(monkeypatch):
    import requests

    def raise_error(*a, **k):
        raise requests.RequestException("network down")

    monkeypatch.setattr(fx.requests, "get", raise_error)
    result = fx.get_rate("GBP")
    assert result["rate"] == 1.0
    assert result["stale"] is True


def test_usd_to_display_conversion(monkeypatch, fake_response):
    monkeypatch.setattr(fx.requests, "get", lambda *a, **k: fake_response(
        json_data={"rates": {"GBP": 0.80}}
    ))
    converted = fx.usd_to_display(100.0, "GBP")
    assert converted == 80.0


def test_usd_to_display_none_passthrough():
    assert fx.usd_to_display(None, "GBP") is None


def test_display_to_usd_conversion(monkeypatch, fake_response):
    monkeypatch.setattr(fx.requests, "get", lambda *a, **k: fake_response(
        json_data={"rates": {"GBP": 0.80}}
    ))
    usd = fx.display_to_usd(80.0, "GBP")
    assert usd == 100.0


def test_display_to_usd_none_passthrough():
    assert fx.display_to_usd(None, "GBP") is None


def test_roundtrip_conversion_is_consistent(monkeypatch, fake_response):
    monkeypatch.setattr(fx.requests, "get", lambda *a, **k: fake_response(
        json_data={"rates": {"EUR": 0.91}}
    ))
    original = 119.99
    converted = fx.usd_to_display(original, "EUR")
    back = fx.display_to_usd(converted, "EUR")
    assert abs(back - original) < 0.0001
