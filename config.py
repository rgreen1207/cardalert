"""
Centralized configuration.

Two sources, checked in this order:
1. The `settings` table in the DB — written by the setup wizard (/setup) or
   the settings page (/settings), no restart or file editing required.
2. Environment variables (from .env) — still supported for anyone who wants
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
    "gumroad_product_id": ("GUMROAD_PRODUCT_ID", ""),
    "cardalert_license_key": ("CARDALERT_LICENSE_KEY", ""),
}


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
    db.set_setting(key, value or "")


def all_values() -> dict:
    return {k: get(k) for k in _KEYS}


def is_setup_complete() -> bool:
    return db.get_setting("setup_complete") == "1"


def mark_setup_complete():
    db.set_setting("setup_complete", "1")
