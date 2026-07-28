import httpx
import notifier
import config
from tests.conftest import set_httpx_post


async def test_send_discord_no_webhook_configured_is_noop():
    calls = []
    set_httpx_post(lambda *a, **k: calls.append((a, k)))
    result = await notifier.send_discord("test message")
    assert result["ok"] is False
    assert calls == []  # never even attempted a request


async def test_send_discord_success(fake_response):
    await config.set("discord_webhook_url", "https://discord.com/api/webhooks/fake")
    set_httpx_post(lambda *a, **k: fake_response(status_code=204))
    result = await notifier.send_discord("test message")
    assert result["ok"] is True
    assert result["status"] == 204


async def test_send_discord_strips_stray_whitespace_in_stored_url(fake_response):
    """Even if a webhook URL with trailing whitespace ends up stored
    (e.g. set directly via .env rather than through config.set, which
    already strips), send_discord itself must still tolerate it rather
    than passing a broken URL to requests."""
    import db
    await db.set_setting("discord_webhook_url", "https://discord.com/api/webhooks/fake\n")
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        return fake_response(status_code=204)

    set_httpx_post(fake_post)
    result = await notifier.send_discord("test message")
    assert result["ok"] is True
    assert captured["url"] == "https://discord.com/api/webhooks/fake"  # no trailing newline reached requests


async def test_send_discord_failure_status(fake_response):
    await config.set("discord_webhook_url", "https://discord.com/api/webhooks/fake")
    set_httpx_post(lambda *a, **k: fake_response(status_code=404, text="Unknown Webhook"))
    result = await notifier.send_discord("test message")
    assert result["ok"] is False
    assert result["status"] == 404
    assert "Unknown Webhook" in result["detail"]


async def test_send_discord_network_error():
    await config.set("discord_webhook_url", "https://discord.com/api/webhooks/fake")

    def raise_error(*a, **k):
        raise httpx.HTTPError("timeout")

    set_httpx_post(raise_error)
    result = await notifier.send_discord("test message")
    assert result["ok"] is False
    assert result["status"] is None


async def test_send_ntfy_noop_without_topic():
    calls = []
    set_httpx_post(lambda *a, **k: calls.append(1))
    await notifier.send_ntfy("test")
    assert calls == []


async def test_send_ntfy_fires_when_configured(fake_response):
    await config.set("ntfy_topic", "my-test-topic")
    calls = []
    set_httpx_post(lambda *a, **k: (calls.append((a, k)), fake_response())[1])
    await notifier.send_ntfy("test")
    assert len(calls) == 1


async def test_send_pushover_noop_without_credentials():
    calls = []
    set_httpx_post(lambda *a, **k: calls.append(1))
    await notifier.send_pushover("test")
    assert calls == []


async def test_send_sms_noop_without_all_credentials():
    await config.set("twilio_account_sid", "sid-only")  # missing the rest
    calls = []
    set_httpx_post(lambda *a, **k: calls.append(1))
    await notifier.send_sms("test")
    assert calls == []


async def test_dispatch_routes_to_correct_channel(monkeypatch):
    called_with = []

    async def fake_discord(msg):
        called_with.append(("discord", msg))

    async def fake_ntfy(msg):
        called_with.append(("ntfy", msg))

    async def fake_pushover(msg):
        called_with.append(("pushover", msg))

    async def fake_sms(msg):
        called_with.append(("sms", msg))

    monkeypatch.setattr(notifier, "send_discord", fake_discord)
    monkeypatch.setattr(notifier, "send_ntfy", fake_ntfy)
    monkeypatch.setattr(notifier, "send_pushover", fake_pushover)
    monkeypatch.setattr(notifier, "send_sms", fake_sms)

    await notifier.dispatch("hello", "discord")
    await notifier.dispatch("hello", "ntfy")
    await notifier.dispatch("hello", "pushover")
    await notifier.dispatch("hello", "sms")
    await notifier.dispatch("hello", "dashboard")  # should do nothing

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


def test_resolve_product_url_strips_tracking_params_from_amazon_url():
    """Regression guard for a reported bug: alert links (Amazon
    especially, but any retailer) should carry a clean product URL, not
    whatever tracking query string was pasted in."""
    item = {"retailer": "amazon", "identifier": "B0D7QJXK9P",
            "product_url": "https://www.amazon.com/dp/B0D7QJXK9P?ref=sr_1_1&tag=affiliate123&th=1"}
    result = notifier.resolve_product_url(item)
    assert result == "https://www.amazon.com/dp/B0D7QJXK9P"
    assert "ref=" not in result
    assert "tag=" not in result


def test_resolve_product_url_strips_tracking_params_from_identifier_url():
    """Same fix, but for retailers where the identifier field itself IS
    the URL (walmart, bn, pokemon_center, lgs_generic)."""
    item = {"retailer": "walmart", "identifier": "https://www.walmart.com/ip/12345?athbdg=L1200&adsRedirect=true",
            "product_url": ""}
    result = notifier.resolve_product_url(item)
    assert result == "https://www.walmart.com/ip/12345"
    assert "?" not in result


def test_resolve_product_url_strips_tracking_from_constructed_target_link():
    item = {"retailer": "target", "identifier": "1011209279", "product_url": ""}
    result = notifier.resolve_product_url(item)
    assert result == "https://www.target.com/p/-/A-1011209279"
    assert "?" not in result


def test_resolve_product_url_no_query_string_is_a_noop():
    item = {"retailer": "amazon", "identifier": "B0D7QJXK9P", "product_url": ""}
    result = notifier.resolve_product_url(item)
    assert result == "https://www.amazon.com/dp/B0D7QJXK9P"


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


async def test_discord_mention_prefix_empty_by_default():
    assert await notifier.discord_mention_prefix() == ""


async def test_discord_mention_prefix_single_user():
    await config.set("discord_mention_users", "123456789012345678")
    assert await notifier.discord_mention_prefix() == "<@123456789012345678> "


async def test_discord_mention_prefix_single_role():
    await config.set("discord_mention_roles", "987654321098765432")
    assert await notifier.discord_mention_prefix() == "<@&987654321098765432> "


async def test_discord_mention_prefix_multiple_users_comma_separated():
    """The actual feature request: multiple mentions, comma-separated."""
    await config.set("discord_mention_users", "111111111111111111, 222222222222222222")
    assert await notifier.discord_mention_prefix() == "<@111111111111111111> <@222222222222222222> "


async def test_discord_mention_prefix_multiple_users_and_roles_together():
    await config.set("discord_mention_users", "111111111111111111,222222222222222222")
    await config.set("discord_mention_roles", "333333333333333333")
    prefix = await notifier.discord_mention_prefix()
    assert "<@111111111111111111>" in prefix
    assert "<@222222222222222222>" in prefix
    assert "<@&333333333333333333>" in prefix


async def test_discord_mention_prefix_drops_non_numeric_entries_from_a_list():
    """One bad entry in a comma-separated list shouldn't break the
    others — each entry is validated independently."""
    await config.set("discord_mention_users", "111111111111111111,not_a_real_id,222222222222222222")
    prefix = await notifier.discord_mention_prefix()
    assert "<@111111111111111111>" in prefix
    assert "<@222222222222222222>" in prefix
    assert "not_a_real_id" not in prefix


async def test_discord_mention_prefix_ignored_without_id():
    await config.set("discord_mention_users", "")
    await config.set("discord_mention_roles", "")
    assert await notifier.discord_mention_prefix() == ""


async def test_discord_mention_prefix_rejects_non_numeric_id():
    await config.set("discord_mention_users", "some_username")
    assert await notifier.discord_mention_prefix() == ""


async def test_discord_mention_prefix_accepts_numeric_id():
    await config.set("discord_mention_users", "123456789012345678")
    assert await notifier.discord_mention_prefix() == "<@123456789012345678> "


async def test_send_discord_includes_allowed_mentions_field(fake_response):
    """Regression guard for the other real cause of the same bug report:
    without an explicit allowed_mentions field, Discord can render
    <@id>/<@&id> as literal unlinked text instead of an actual ping."""
    await config.set("discord_webhook_url", "https://discord.com/api/webhooks/fake")
    await config.set("discord_mention_roles", "555555555555555555")
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["payload"] = json
        return fake_response(status_code=204)

    set_httpx_post(fake_post)
    await notifier.send_discord("Restock alert!")
    assert captured["payload"]["allowed_mentions"] == {"parse": ["users", "roles"]}
    assert captured["payload"]["content"].startswith("<@&555555555555555555> ")
