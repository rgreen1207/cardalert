import notifier
import config


def test_send_discord_no_webhook_configured_is_noop(monkeypatch):
    calls = []
    monkeypatch.setattr(notifier.requests, "post", lambda *a, **k: calls.append((a, k)))
    result = notifier.send_discord("test message")
    assert result is False
    assert calls == []  # never even attempted a request


def test_send_discord_success(monkeypatch, fake_response):
    config.set("discord_webhook_url", "https://discord.com/api/webhooks/fake")
    monkeypatch.setattr(notifier.requests, "post", lambda *a, **k: fake_response(status_code=204))
    assert notifier.send_discord("test message") is True


def test_send_discord_failure_status(monkeypatch, fake_response):
    config.set("discord_webhook_url", "https://discord.com/api/webhooks/fake")
    monkeypatch.setattr(notifier.requests, "post", lambda *a, **k: fake_response(status_code=404))
    assert notifier.send_discord("test message") is False


def test_send_discord_network_error(monkeypatch):
    import requests
    config.set("discord_webhook_url", "https://discord.com/api/webhooks/fake")

    def raise_error(*a, **k):
        raise requests.RequestException("timeout")

    monkeypatch.setattr(notifier.requests, "post", raise_error)
    assert notifier.send_discord("test message") is False


def test_send_ntfy_noop_without_topic(monkeypatch):
    calls = []
    monkeypatch.setattr(notifier.requests, "post", lambda *a, **k: calls.append(1))
    notifier.send_ntfy("test")
    assert calls == []


def test_send_ntfy_fires_when_configured(monkeypatch, fake_response):
    config.set("ntfy_topic", "my-test-topic")
    calls = []
    monkeypatch.setattr(notifier.requests, "post", lambda *a, **k: (calls.append((a, k)), fake_response())[1])
    notifier.send_ntfy("test")
    assert len(calls) == 1


def test_send_pushover_noop_without_credentials(monkeypatch):
    calls = []
    monkeypatch.setattr(notifier.requests, "post", lambda *a, **k: calls.append(1))
    notifier.send_pushover("test")
    assert calls == []


def test_send_sms_noop_without_all_credentials(monkeypatch):
    config.set("twilio_account_sid", "sid-only")  # missing the rest
    calls = []
    monkeypatch.setattr(notifier.requests, "post", lambda *a, **k: calls.append(1))
    notifier.send_sms("test")
    assert calls == []


def test_dispatch_routes_to_correct_channel(monkeypatch):
    called_with = []
    monkeypatch.setattr(notifier, "send_discord", lambda msg: called_with.append(("discord", msg)))
    monkeypatch.setattr(notifier, "send_ntfy", lambda msg: called_with.append(("ntfy", msg)))
    monkeypatch.setattr(notifier, "send_pushover", lambda msg: called_with.append(("pushover", msg)))
    monkeypatch.setattr(notifier, "send_sms", lambda msg: called_with.append(("sms", msg)))

    notifier.dispatch("hello", "discord")
    notifier.dispatch("hello", "ntfy")
    notifier.dispatch("hello", "pushover")
    notifier.dispatch("hello", "sms")
    notifier.dispatch("hello", "dashboard")  # should do nothing

    assert ("discord", "hello") in called_with
    assert ("ntfy", "hello") in called_with
    assert ("pushover", "hello") in called_with
    assert ("sms", "hello") in called_with
    assert len(called_with) == 4  # dashboard channel triggered nothing


def test_restock_message_format():
    item = {"name": "Prismatic Evolutions SPC", "retailer": "target"}
    msg = notifier.restock_message(item, 119.99, "https://target.com/x")
    assert "Prismatic Evolutions SPC" in msg
    assert "target" in msg
    assert "119.99" in msg
    assert "https://target.com/x" in msg
