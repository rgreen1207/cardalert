"""
Feature-tier gating.

Design intent: this file is intentionally readable and public — hiding the
check doesn't meaningfully stop anyone determined to bypass it, and an
open, honest gate is more trustworthy than an obfuscated one. What makes
paying worthwhile isn't secrecy, it's that the paid tier's real value
(the auto-updater keeping pollers working as retailers change their sites,
new pollers landing first, pattern analytics that compounds over time) is
much harder to get value from off a static cloned snapshot.

Wiring to Gumroad (once you've created a product there):
    1. Create a product on Gumroad, enable license keys.
    2. Set GUMROAD_PRODUCT_ID in .env.
    3. User enters their license key in the dashboard settings page.
    4. verify_license() below calls Gumroad's public license-verification
       endpoint (https://api.gumroad.com/v2/licenses/verify) — no SDK needed,
       it's a plain POST. Response tells you if the key is valid + how many
       times it's been activated (Gumroad tracks this for you).

Until a key is configured, everything runs in FREE_TIER mode.
"""
import os
import time
import requests

GUMROAD_PRODUCT_ID = os.environ.get("GUMROAD_PRODUCT_ID", "")
LICENSE_KEY = os.environ.get("CARDALERT_LICENSE_KEY", "")

FREE_TIER_RETAILER_LIMIT = 2
FREE_TIER_ALLOWED_CHANNELS = {"dashboard"}

_cache = {"valid": False, "checked_at": 0}
CACHE_TTL = 3600  # re-check hourly, not on every request


def is_pro() -> bool:
    if not GUMROAD_PRODUCT_ID or not LICENSE_KEY:
        return False
    now = time.time()
    if now - _cache["checked_at"] < CACHE_TTL:
        return _cache["valid"]
    try:
        r = requests.post(
            "https://api.gumroad.com/v2/licenses/verify",
            data={"product_id": GUMROAD_PRODUCT_ID, "license_key": LICENSE_KEY},
            timeout=8,
        )
        data = r.json()
        valid = bool(data.get("success"))
    except requests.RequestException:
        # Network hiccup shouldn't lock a paying user out — trust the last
        # good check for a while, only downgrade after repeated failures.
        valid = _cache["valid"]
    _cache.update(valid=valid, checked_at=now)
    return valid


def enforce_retailer_limit(current_active_retailers: set) -> bool:
    """Returns True if adding one more distinct retailer is allowed."""
    if is_pro():
        return True
    return len(current_active_retailers) < FREE_TIER_RETAILER_LIMIT


def channel_allowed(channel: str) -> bool:
    if is_pro():
        return True
    return channel in FREE_TIER_ALLOWED_CHANNELS


def feature_allowed(feature: str) -> bool:
    """feature in {"pattern_analytics", "forecast_signals", "lgs_generic", "sms", "ntfy", "pushover", "discord"}"""
    if is_pro():
        return True
    return False
