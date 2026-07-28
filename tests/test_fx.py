import time
import httpx
import fx
import db
from tests.conftest import set_httpx_get


async def test_usd_rate_is_always_one_no_network():
    calls = []
    set_httpx_get(lambda *a, **k: calls.append(1))
    result = await fx.get_rate("USD")
    assert result == {"rate": 1.0, "stale": False}
    assert calls == []  # never even tries to fetch for USD


async def test_get_rate_fetches_and_caches(fake_response):
    set_httpx_get(lambda *a, **k: fake_response(
        json_data={"rates": {"GBP": 0.78, "EUR": 0.91}}
    ))
    result = await fx.get_rate("GBP")
    assert result == {"rate": 0.78, "stale": False}
    # confirm it actually cached something
    cached = await db.get_setting("fx_rates_cache")
    assert cached is not None


async def test_get_rate_uses_cache_within_ttl(fake_response):
    call_count = {"n": 0}

    def fake_get(*a, **k):
        call_count["n"] += 1
        return fake_response(json_data={"rates": {"GBP": 0.78}})

    set_httpx_get(fake_get)
    await fx.get_rate("GBP")
    await fx.get_rate("GBP")
    await fx.get_rate("GBP")
    assert call_count["n"] == 1  # only fetched once, rest served from cache


async def test_get_rate_falls_back_to_stale_cache_on_network_failure(fake_response):
    set_httpx_get(lambda *a, **k: fake_response(
        json_data={"rates": {"GBP": 0.78}}
    ))
    await fx.get_rate("GBP")  # populate cache

    def raise_error(*a, **k):
        raise httpx.HTTPError("network down")

    set_httpx_get(raise_error)
    # force cache to look expired
    cache = await fx._load_cache()
    await db.set_setting("fx_rates_cache", __import__("json").dumps(
        {"rates": cache["rates"], "fetched_at": time.time() - fx.CACHE_TTL_SECONDS - 1}
    ))
    result = await fx.get_rate("GBP")
    assert result["rate"] == 0.78
    assert result["stale"] is True


async def test_get_rate_total_failure_falls_back_to_one():
    def raise_error(*a, **k):
        raise httpx.HTTPError("network down")

    set_httpx_get(raise_error)
    result = await fx.get_rate("GBP")
    assert result["rate"] == 1.0
    assert result["stale"] is True


async def test_get_rate_survives_malformed_non_json_response():
    """Regression guard for the reported bug: a 500 on /products. The
    exchange-rate API returning something that isn't valid JSON (rate
    limiting, a proxy error page, a network hiccup mid-response) must not
    crash — every page that shows a price calls this on every load
    whenever the currency isn't USD, so an uncaught exception here takes
    down the whole page, not just the currency conversion."""
    import json

    class MalformedResponse:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            raise json.JSONDecodeError("bad json", "not json", 0)

    set_httpx_get(lambda *a, **k: MalformedResponse())
    result = await fx.get_rate("GBP")  # must not raise
    assert result["rate"] == 1.0
    assert result["stale"] is True


async def test_get_rate_survives_unexpected_response_shape(fake_response):
    """A 200 with valid JSON but a shape the code doesn't expect (e.g. an
    error body instead of a rates object) must also degrade gracefully,
    not raise."""
    set_httpx_get(lambda *a, **k: fake_response(
        json_data={"error": "rate limited"}  # no "rates" key at all
    ))
    result = await fx.get_rate("GBP")
    assert result["rate"] == 1.0
    assert result["stale"] is True


async def test_usd_to_display_conversion(fake_response):
    set_httpx_get(lambda *a, **k: fake_response(
        json_data={"rates": {"GBP": 0.80}}
    ))
    converted = await fx.usd_to_display(100.0, "GBP")
    assert converted == 80.0


async def test_usd_to_display_none_passthrough():
    assert await fx.usd_to_display(None, "GBP") is None


async def test_display_to_usd_conversion(fake_response):
    set_httpx_get(lambda *a, **k: fake_response(
        json_data={"rates": {"GBP": 0.80}}
    ))
    usd = await fx.display_to_usd(80.0, "GBP")
    assert usd == 100.0


async def test_display_to_usd_none_passthrough():
    assert await fx.display_to_usd(None, "GBP") is None


async def test_roundtrip_conversion_is_consistent(fake_response):
    set_httpx_get(lambda *a, **k: fake_response(
        json_data={"rates": {"EUR": 0.91}}
    ))
    original = 119.99
    converted = await fx.usd_to_display(original, "EUR")
    back = await fx.display_to_usd(converted, "EUR")
    assert abs(back - original) < 0.0001
