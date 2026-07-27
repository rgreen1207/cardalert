"""
Centralized configuration.

Two sources, checked in this order:
1. The `settings` table in the DB, written by the setup wizard (/setup) or
   the settings page (/settings), no restart or file editing required.
2. Environment variables (from .env), still supported for anyone who wants
   to configure via file instead of the web UI (e.g. scripted deployments).

DB settings win if both are set, since they're the more recently-touched,
UI-driven source of truth.
"""
import os
import db

# setting_key -> (env_var_name, default)
_KEYS = {
    "discord_webhook_url": ("DISCORD_WEBHOOK_URL", ""),
    "ntfy_topic": ("NTFY_TOPIC", ""),
    "ntfy_server": ("NTFY_SERVER", "https://ntfy.sh"),
    "pushover_user_key": ("PUSHOVER_USER_KEY", ""),
    "pushover_app_token": ("PUSHOVER_APP_TOKEN", ""),
    "twilio_account_sid": ("TWILIO_ACCOUNT_SID", ""),
    "twilio_auth_token": ("TWILIO_AUTH_TOKEN", ""),
    "twilio_from_number": ("TWILIO_FROM_NUMBER", ""),
    "twilio_to_number": ("TWILIO_TO_NUMBER", ""),
    "bestbuy_api_key": ("BESTBUY_API_KEY", ""),
    "currency": ("CARDALERT_CURRENCY", "USD"),
    "discord_mention_users": ("DISCORD_MENTION_USERS", ""),  # comma-separated user IDs
    "discord_mention_roles": ("DISCORD_MENTION_ROLES", ""),  # comma-separated role IDs
    "target_api_key": ("TARGET_API_KEY", ""),
    "pokemon_center_fast_check_seconds": ("POKEMON_CENTER_FAST_CHECK_SECONDS", "15"),
}

CURRENCY_SYMBOLS = {
    "USD": "$", "CAD": "$", "AUD": "$", "NZD": "$",
    "EUR": "€", "GBP": "£", "JPY": "¥",
}


def currency_symbol() -> str:
    return CURRENCY_SYMBOLS.get(get("currency"), "$")


def get(key: str) -> str:
    if key not in _KEYS:
        raise KeyError(f"Unknown config key: {key}")
    env_name, default = _KEYS[key]
    db_value = db.get_setting(key)
    if db_value is not None and db_value != "":
        return db_value
    return os.environ.get(env_name, default)


def set(key: str, value: str):
    if key not in _KEYS:
        raise KeyError(f"Unknown config key: {key}")
    # Strips whitespace so a copy-pasted webhook URL/token with a trailing
    # space or newline (common from mobile clipboards) doesn't silently
    # break requests that use it later.
    db.set_setting(key, (value or "").strip())


def all_values() -> dict:
    return {k: get(k) for k in _KEYS}


POKEMON_CENTER_FAST_CHECK_FLOOR_SECONDS = 10


def pokemon_center_fast_check_seconds() -> int:
    """Clamped to a floor so this can never be set low enough to become
    genuinely excessive polling, regardless of what ends up in .env or
    the settings table."""
    raw = get("pokemon_center_fast_check_seconds")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 15
    return max(value, POKEMON_CENTER_FAST_CHECK_FLOOR_SECONDS)


# --- Dashboard password (stored as salted hash, never plaintext, DB-only) ---
import hashlib
import secrets as _secrets


def set_dashboard_password(plaintext: str):
    if not plaintext:
        db.set_setting("dashboard_password_hash", "")
        db.set_setting("dashboard_password_salt", "")
        return
    salt = _secrets.token_hex(16)
    digest = hashlib.sha256((salt + plaintext).encode()).hexdigest()
    db.set_setting("dashboard_password_salt", salt)
    db.set_setting("dashboard_password_hash", digest)


def check_dashboard_password(plaintext: str) -> bool:
    salt = db.get_setting("dashboard_password_salt", "")
    stored_hash = db.get_setting("dashboard_password_hash", "")
    if not stored_hash:
        return False
    digest = hashlib.sha256((salt + plaintext).encode()).hexdigest()
    return _secrets.compare_digest(digest, stored_hash)


def dashboard_password_is_set() -> bool:
    return bool(db.get_setting("dashboard_password_hash", ""))


def is_setup_complete() -> bool:
    return db.get_setting("setup_complete") == "1"


def mark_setup_complete():
    db.set_setting("setup_complete", "1")
