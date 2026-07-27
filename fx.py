"""
Currency conversion for display purposes.

Every retailer this app watches is a US site, so every price it ever polls
or stores is genuinely in USD. That never changes based on the currency
setting. What the currency setting controls is purely display: converting
those USD numbers to another currency when showing them, and converting a
typed-in "Max price" back to USD before storing it, so the actual
over-price comparison logic (which runs against the retailer's real USD
price) stays correct regardless of what currency the person prefers to
read in.

Rates come from the Frankfurter API (frankfurter.app), free and keyless,
cached for 24 hours in the settings table so this isn't a network call on
every page load. If the fetch fails and there's no usable cache yet, this
falls back to a rate of 1.0 (i.e., treats the target currency as if it
were USD) rather than crashing or showing nothing, and reports that
degraded state so the UI can say so.
"""
import json
import time
import requests
import db

CACHE_TTL_SECONDS = 24 * 3600
FETCH_TIMEOUT = 8


def _load_cache():
    raw = db.get_setting("fx_rates_cache")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


def _save_cache(rates: dict):
    db.set_setting("fx_rates_cache", json.dumps({"rates": rates, "fetched_at": time.time()}))


def _fetch_rates() -> dict:
    """USD -> {currency: rate} for every currency this app supports."""
    targets = "EUR,GBP,JPY,CAD,AUD,NZD"
    url = f"https://api.frankfurter.app/latest?from=USD&to={targets}"
    r = requests.get(url, timeout=FETCH_TIMEOUT)
    r.raise_for_status()
    data = r.json()
    rates = data.get("rates", {})
    rates["USD"] = 1.0
    return rates


def get_rate(currency: str) -> dict:
    """Returns {"rate": float, "stale": bool}. `stale` is True when this
    is a cached or fallback value rather than a fresh fetch, so the UI can
    show a small "rates may be approximate" note when it matters."""
    if currency == "USD":
        return {"rate": 1.0, "stale": False}

    cache = _load_cache()
    now = time.time()
    if cache and (now - cache.get("fetched_at", 0)) < CACHE_TTL_SECONDS:
        rate = cache["rates"].get(currency)
        if rate:
            return {"rate": rate, "stale": False}

    try:
        rates = _fetch_rates()
        _save_cache(rates)
        rate = rates.get(currency)
        if rate:
            return {"rate": rate, "stale": False}
    except requests.RequestException:
        pass

    # Network failed, or the currency wasn't in the response. Fall back to
    # the last cache we have even if it's stale, rather than nothing.
    if cache and cache.get("rates", {}).get(currency):
        return {"rate": cache["rates"][currency], "stale": True}

    return {"rate": 1.0, "stale": True}


def usd_to_display(amount, currency: str):
    if amount is None:
        return None
    return amount * get_rate(currency)["rate"]


def display_to_usd(amount, currency: str):
    if amount is None:
        return None
    rate = get_rate(currency)["rate"]
    if rate == 0:
        return amount
    return amount / rate
