"""
Feature-tier gating. See PROJECT_LOG.md for the reasoning on why this file
stays public/readable rather than obfuscated.

Credentials come from config.py (settings page or .env). Entering a license
key on the settings page takes effect within the hour (see CACHE_TTL) since
Gumroad verification is a network call we don't want to fire on every page
load.
"""
import time
import requests
import config

FREE_TIER_RETAILER_LIMIT = 2
FREE_TIER_ALLOWED_CHANNELS = {"dashboard"}

_cache = {"valid": False, "checked_at": 0}
CACHE_TTL = 3600


def is_pro() -> bool:
    product_id = config.get("gumroad_product_id")
    license_key = config.get("cardalert_license_key")
    if not product_id or not license_key:
        return False
    now = time.time()
    if now - _cache["checked_at"] < CACHE_TTL:
        return _cache["valid"]
    try:
        r = requests.post(
            "https://api.gumroad.com/v2/licenses/verify",
            data={"product_id": product_id, "license_key": license_key},
            timeout=8,
        )
        valid = bool(r.json().get("success"))
    except requests.RequestException:
        valid = _cache["valid"]  # network hiccup shouldn't lock out a paying user
    _cache.update(valid=valid, checked_at=now)
    return valid


def enforce_retailer_limit(current_active_retailers: set) -> bool:
    if is_pro():
        return True
    return len(current_active_retailers) < FREE_TIER_RETAILER_LIMIT


def channel_allowed(channel: str) -> bool:
    if is_pro():
        return True
    return channel in FREE_TIER_ALLOWED_CHANNELS


def feature_allowed(feature: str) -> bool:
    """feature in {"pattern_analytics", "forecast_signals", "lgs_generic", "sms", "ntfy", "pushover", "discord"}"""
    return is_pro()
