import pytest
import config


async def test_get_returns_default_when_unset(monkeypatch):
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    assert await config.get("discord_webhook_url") == ""


async def test_set_and_get_roundtrip():
    await config.set("discord_webhook_url", "https://discord.com/api/webhooks/abc")
    assert await config.get("discord_webhook_url") == "https://discord.com/api/webhooks/abc"


async def test_set_strips_whitespace():
    """Regression guard: a webhook URL or token pasted with a trailing
    space or newline (common from mobile clipboards) must not silently
    break the request that uses it later."""
    await config.set("discord_webhook_url", "  https://discord.com/api/webhooks/abc\n")
    assert await config.get("discord_webhook_url") == "https://discord.com/api/webhooks/abc"


async def test_db_setting_overrides_env(monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://env-value.example.com")
    assert await config.get("discord_webhook_url") == "https://env-value.example.com"
    await config.set("discord_webhook_url", "https://db-value.example.com")
    assert await config.get("discord_webhook_url") == "https://db-value.example.com"


async def test_unknown_key_raises():
    with pytest.raises(KeyError):
        await config.get("not_a_real_setting")
    with pytest.raises(KeyError):
        await config.set("not_a_real_setting", "value")


async def test_currency_symbol_defaults_to_usd():
    assert await config.get("currency") == "USD"
    assert await config.currency_symbol() == "$"


async def test_currency_symbol_updates_with_setting():
    await config.set("currency", "GBP")
    assert await config.currency_symbol() == "£"
    await config.set("currency", "JPY")
    assert await config.currency_symbol() == "¥"


async def test_currency_symbol_unknown_currency_falls_back_to_dollar():
    await config.set("currency", "XYZ")
    assert await config.currency_symbol() == "$"


async def test_setup_completion_flow():
    assert await config.is_setup_complete() is False
    await config.mark_setup_complete()
    assert await config.is_setup_complete() is True


async def test_dashboard_password_not_set_by_default():
    assert await config.dashboard_password_is_set() is False
    assert await config.check_dashboard_password("anything") is False


async def test_dashboard_password_set_and_check():
    await config.set_dashboard_password("hunter2")
    assert await config.dashboard_password_is_set() is True
    assert await config.check_dashboard_password("hunter2") is True
    assert await config.check_dashboard_password("wrong") is False


async def test_dashboard_password_never_stored_plaintext():
    await config.set_dashboard_password("hunter2")
    import db
    all_settings_values = " ".join((await db.all_settings()).values())
    assert "hunter2" not in all_settings_values


async def test_dashboard_password_cleared_with_empty_string():
    await config.set_dashboard_password("hunter2")
    assert await config.dashboard_password_is_set() is True
    await config.set_dashboard_password("")
    assert await config.dashboard_password_is_set() is False


async def test_all_values_includes_every_known_key():
    values = await config.all_values()
    for key in config._KEYS:
        assert key in values


async def test_pokemon_center_fast_check_seconds_default():
    assert await config.pokemon_center_fast_check_seconds() == 15


async def test_pokemon_center_fast_check_seconds_respects_setting():
    await config.set("pokemon_center_fast_check_seconds", "30")
    assert await config.pokemon_center_fast_check_seconds() == 30


async def test_pokemon_center_fast_check_seconds_enforces_floor():
    """The actual safety requirement: this can never be set low enough
    to become genuinely excessive polling."""
    await config.set("pokemon_center_fast_check_seconds", "1")
    assert await config.pokemon_center_fast_check_seconds() == config.POKEMON_CENTER_FAST_CHECK_FLOOR_SECONDS


async def test_pokemon_center_fast_check_seconds_handles_garbage_gracefully():
    await config.set("pokemon_center_fast_check_seconds", "not-a-number")
    assert await config.pokemon_center_fast_check_seconds() >= config.POKEMON_CENTER_FAST_CHECK_FLOOR_SECONDS


async def test_pokemon_center_repeat_alerts_disabled_by_default():
    assert await config.pokemon_center_repeat_alerts_enabled() is False


async def test_pokemon_center_repeat_alerts_can_be_enabled():
    await config.set("pokemon_center_repeat_alerts", "1")
    assert await config.pokemon_center_repeat_alerts_enabled() is True


async def test_pokemon_center_repeat_alert_seconds_default():
    assert await config.pokemon_center_repeat_alert_seconds() == 90


async def test_pokemon_center_repeat_alert_seconds_respects_setting():
    await config.set("pokemon_center_repeat_alert_seconds", "120")
    assert await config.pokemon_center_repeat_alert_seconds() == 120


async def test_pokemon_center_repeat_alert_seconds_enforces_floor():
    await config.set("pokemon_center_repeat_alert_seconds", "1")
    assert await config.pokemon_center_repeat_alert_seconds() == config.POKEMON_CENTER_REPEAT_ALERT_FLOOR_SECONDS
