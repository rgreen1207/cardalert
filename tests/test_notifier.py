import notifier
import config


def test_send_discord_no_webhook_configured_is_noop(monkeypatch):
    calls = []
    monkeypatch.setattr(notifier.requests, "post", lambda *a, **k: calls.append((a, k)))
    result = notifier.send_discord("test message")
    assert result["ok"] is False
    assert calls == []  # never even attempted a request


def test_send_discord_success(monkeypatch, fake_response):
    config.set("discord_webhook_url", "https://discord.com/api/webhooks/fake")
    monkeypatch.setattr(notifier.requests, "post", lambda *a, **k: fake_response(status_code=204))
    result = notifier.send_discord("test message")
    assert result["ok"] is True
    assert result["status"] == 204


def test_send_discord_failure_status(monkeypatch, fake_response):
    config.set("discord_webhook_url", "https://discord.com/api/webhooks/fake")
    monkeypatch.setattr(notifier.requests, "post", lambda *a, **k: fake_response(status_code=404, text="Unknown Webhook"))
    result = notifier.send_discord("test message")
    assert result["ok"] is False
    assert result["status"] == 404
    assert "Unknown Webhook" in result["detail"]


def test_send_discord_network_error(monkeypatch):
    import requests
    config.set("discord_webhook_url", "https://discord.com/api/webhooks/fake")

    def raise_error(*a, **k):
        raise requests.RequestException("timeout")

    monkeypatch.setattr(notifier.requests, "post", raise_error)
    result = notifier.send_discord("test message")
    assert result["ok"] is False
    assert result["status"] is None


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
    assert "Target" in msg  # display name, not raw "target"
    assert "119.99" in msg
    assert "https://target.com/x" in msg


def test_resolve_product_url_uses_explicit_url_first():
    item = {"retailer": "target", "identifier": "123", "product_url": "https://custom.example.com/x"}
    assert notifier.resolve_product_url(item) == "https://custom.example.com/x"


def test_resolve_product_url_constructs_target_link():
    item = {"retailer": "target", "identifier": "1011209279", "product_url": ""}
    assert notifier.resolve_product_url(item) == "https://www.target.com/p/-/A-1011209279"


def test_resolve_product_url_constructs_amazon_link_from_asin():
    item = {"retailer": "amazon", "identifier": "B0D7QJXK9P", "product_url": ""}
    assert notifier.resolve_product_url(item) == "https://www.amazon.com/dp/B0D7QJXK9P"


def test_resolve_product_url_amazon_passes_through_full_url():
    item = {"retailer": "amazon", "identifier": "https://www.amazon.com/dp/B0D7QJXK9P", "product_url": ""}
    assert notifier.resolve_product_url(item) == "https://www.amazon.com/dp/B0D7QJXK9P"


def test_resolve_product_url_constructs_bestbuy_search_link():
    item = {"retailer": "bestbuy", "identifier": "6418599", "product_url": ""}
    assert notifier.resolve_product_url(item) == "https://www.bestbuy.com/site/searchpage.jsp?st=6418599"


def test_resolve_product_url_walmart_uses_identifier_directly():
    # This is the actual bug: walmart/bn/pokemon_center/lgs_generic require
    # the identifier itself to be a full URL, so product_url is often left
    # blank. Alerts must still carry a working link.
    item = {"retailer": "walmart", "identifier": "https://www.walmart.com/ip/12345", "product_url": ""}
    assert notifier.resolve_product_url(item) == "https://www.walmart.com/ip/12345"


def test_resolve_product_url_lgs_shopify_reconstructs_full_url():
    item = {"retailer": "lgs_shopify", "identifier": "myshop.com/products/booster-box", "product_url": ""}
    assert notifier.resolve_product_url(item) == "https://myshop.com/products/booster-box"


def test_resolve_product_url_no_identifier_returns_empty():
    item = {"retailer": "target", "identifier": "", "product_url": ""}
    assert notifier.resolve_product_url(item) == ""


def test_restock_message_always_includes_a_link_even_without_explicit_product_url():
    item = {"name": "Booster Box", "retailer": "target", "identifier": "1011209279", "product_url": ""}
    msg = notifier.restock_message(item, 49.99, "")
    assert "target.com/p/-/A-1011209279" in msg


def test_discord_mention_prefix_empty_by_default():
    assert notifier.discord_mention_prefix() == ""


def test_discord_mention_prefix_user():
    config.set("discord_mention_type", "user")
    config.set("discord_mention_id", "123456789")
    assert notifier.discord_mention_prefix() == "<@123456789> "


def test_discord_mention_prefix_role():
    config.set("discord_mention_type", "role")
    config.set("discord_mention_id", "987654321")
    assert notifier.discord_mention_prefix() == "<@&987654321> "


def test_discord_mention_prefix_ignored_without_id():
    config.set("discord_mention_type", "user")
    config.set("discord_mention_id", "")
    assert notifier.discord_mention_prefix() == ""


def test_send_discord_includes_mention(monkeypatch, fake_response):
    config.set("discord_webhook_url", "https://discord.com/api/webhooks/fake")
    config.set("discord_mention_type", "role")
    config.set("discord_mention_id", "555")
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["content"] = json["content"]
        return fake_response(status_code=204)

    monkeypatch.setattr(notifier.requests, "post", fake_post)
    notifier.send_discord("Restock alert!")
    assert captured["content"].startswith("<@&555> ")
    assert "Restock alert!" in captured["content"]
