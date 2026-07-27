import pytest
import config


def test_get_returns_default_when_unset(monkeypatch):
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    assert config.get("discord_webhook_url") == ""


def test_set_and_get_roundtrip():
    config.set("discord_webhook_url", "https://discord.com/api/webhooks/abc")
    assert config.get("discord_webhook_url") == "https://discord.com/api/webhooks/abc"


def test_db_setting_overrides_env(monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://env-value.example.com")
    assert config.get("discord_webhook_url") == "https://env-value.example.com"
    config.set("discord_webhook_url", "https://db-value.example.com")
    assert config.get("discord_webhook_url") == "https://db-value.example.com"


def test_unknown_key_raises():
    with pytest.raises(KeyError):
        config.get("not_a_real_setting")
    with pytest.raises(KeyError):
        config.set("not_a_real_setting", "value")


def test_currency_symbol_defaults_to_usd():
    assert config.get("currency") == "USD"
    assert config.currency_symbol() == "$"


def test_currency_symbol_updates_with_setting():
    config.set("currency", "GBP")
    assert config.currency_symbol() == "£"
    config.set("currency", "JPY")
    assert config.currency_symbol() == "¥"


def test_currency_symbol_unknown_currency_falls_back_to_dollar():
    config.set("currency", "XYZ")
    assert config.currency_symbol() == "$"


def test_setup_completion_flow():
    assert config.is_setup_complete() is False
    config.mark_setup_complete()
    assert config.is_setup_complete() is True


def test_dashboard_password_not_set_by_default():
    assert config.dashboard_password_is_set() is False
    assert config.check_dashboard_password("anything") is False


def test_dashboard_password_set_and_check():
    config.set_dashboard_password("hunter2")
    assert config.dashboard_password_is_set() is True
    assert config.check_dashboard_password("hunter2") is True
    assert config.check_dashboard_password("wrong") is False


def test_dashboard_password_never_stored_plaintext():
    config.set_dashboard_password("hunter2")
    import db
    all_settings_values = " ".join(db.all_settings().values())
    assert "hunter2" not in all_settings_values


def test_dashboard_password_cleared_with_empty_string():
    config.set_dashboard_password("hunter2")
    assert config.dashboard_password_is_set() is True
    config.set_dashboard_password("")
    assert config.dashboard_password_is_set() is False


def test_all_values_includes_every_known_key():
    values = config.all_values()
    for key in config._KEYS:
        assert key in values
