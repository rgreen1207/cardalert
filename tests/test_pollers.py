import pytest
import pollers


# --- Amazon: the important one — first-party vs third-party seller filtering ---

def test_amazon_first_party_in_stock(monkeypatch, fake_response):
    html = '<div id="add-to-cart-button">Add to Cart</div> Ships from and sold by Amazon.com'
    monkeypatch.setattr(pollers.requests, "get", lambda *a, **k: fake_response(text=html))
    result = pollers.check_amazon("B0D7QJXK9P")
    assert result["in_stock"] is True
    assert result["raw_status"] == "AVAILABLE"


def test_amazon_third_party_seller_excluded(monkeypatch, fake_response):
    html = '<div id="add-to-cart-button">Add to Cart</div> Sold by ThirdPartyReseller Inc and Fulfilled by Amazon'
    monkeypatch.setattr(pollers.requests, "get", lambda *a, **k: fake_response(text=html))
    result = pollers.check_amazon("B0D7QJXK9P")
    assert result["in_stock"] is False
    assert result["raw_status"] == "THIRD_PARTY_SELLER_ONLY"


def test_amazon_sold_out(monkeypatch, fake_response):
    html = "Currently unavailable. We don't know when or if this item will be back in stock."
    monkeypatch.setattr(pollers.requests, "get", lambda *a, **k: fake_response(text=html))
    result = pollers.check_amazon("B0D7QJXK9P")
    assert result["in_stock"] is False
    assert result["raw_status"] == "SOLD_OUT"


def test_amazon_first_party_but_sold_out(monkeypatch, fake_response):
    html = "Ships from and sold by Amazon.com but Currently unavailable"
    monkeypatch.setattr(pollers.requests, "get", lambda *a, **k: fake_response(text=html))
    result = pollers.check_amazon("B0D7QJXK9P")
    assert result["in_stock"] is False
    assert result["raw_status"] == "SOLD_OUT"


def test_amazon_extracts_asin_from_various_url_shapes(monkeypatch, fake_response):
    monkeypatch.setattr(pollers.requests, "get", lambda *a, **k: fake_response(text="Ships from and sold by Amazon.com <div id=\"add-to-cart-button\">x</div>"))
    for identifier in [
        "B0D7QJXK9P",
        "https://www.amazon.com/dp/B0D7QJXK9P/ref=sr_1_1",
        "https://www.amazon.com/Some-Product-Name/dp/B0D7QJXK9P",
        "https://www.amazon.com/gp/product/B0D7QJXK9P",
    ]:
        result = pollers.check_amazon(identifier)
        assert result["raw_status"] == "AVAILABLE"


def test_amazon_invalid_identifier():
    result = pollers.check_amazon("not-a-valid-identifier")
    assert result["raw_status"] == "INVALID_IDENTIFIER"
    assert result["in_stock"] is False


# --- Target ---

def test_target_blocked_or_key_invalid_returns_distinct_status(monkeypatch, fake_response):
    """Follow-up regression guard: after fixing the missing-product-key
    crash, Target reportedly still showed 'Error checking stock.' This
    covers the other real failure mode — a 401/403 from Target itself,
    which most likely means the poller's hardcoded redsky API key has
    been rotated or blocked, not that any particular product is broken.
    This must surface as a distinct, diagnosable status, not get
    swallowed into a generic scheduler-level 'ERROR: ...'."""
    monkeypatch.setattr(pollers.requests, "get", lambda *a, **k: fake_response(status_code=403, text="Forbidden by Target"))
    result = pollers.check_target("1011209279")
    assert result["raw_status"] == "BLOCKED_OR_KEY_INVALID"
    assert result["in_stock"] is False
    assert "Forbidden by Target" in result["error_detail"]


def test_target_401_also_returns_blocked_status(monkeypatch, fake_response):
    monkeypatch.setattr(pollers.requests, "get", lambda *a, **k: fake_response(status_code=401))
    result = pollers.check_target("1011209279")
    assert result["raw_status"] == "BLOCKED_OR_KEY_INVALID"
    assert "error_detail" in result


def test_target_rate_limited_returns_distinct_status(monkeypatch, fake_response):
    monkeypatch.setattr(pollers.requests, "get", lambda *a, **k: fake_response(status_code=429, text="Too many requests"))
    result = pollers.check_target("1011209279")
    assert result["raw_status"] == "RATE_LIMITED"
    assert "Too many requests" in result["error_detail"]


def test_target_non_json_response_returns_distinct_status(monkeypatch):
    """A 200 response whose body isn't valid JSON (e.g. an HTML
    block/interstitial page instead of the expected API response) must
    also surface as something diagnosable, not a raw exception string."""
    class HtmlResponse:
        status_code = 200
        text = "<html>Access Denied - unusual traffic detected</html>"

        def raise_for_status(self):
            pass

        def json(self):
            import json
            raise json.JSONDecodeError("not json", "<html>blocked</html>", 0)

    import pollers as pollers_module
    import unittest.mock as mock
    with mock.patch.object(pollers_module.requests, "get", return_value=HtmlResponse()):
        result = pollers_module.check_target("1011209279")
    assert result["raw_status"] == "UNEXPECTED_RESPONSE"
    assert "unusual traffic" in result["error_detail"]


def test_target_missing_product_key_returns_not_found_instead_of_crashing(monkeypatch, fake_response):
    """Regression guard for a reported bug: the dashboard showed 'Error
    checking stock' for items that were actually just out of stock or
    otherwise unavailable in a way that gives Target's API a different
    response shape (delisted, restricted, etc). check_target previously
    used direct dict indexing (data["data"]["product"]), which raised an
    uncaught KeyError on any response missing that key, misreporting a
    legitimate state as a generic error."""
    monkeypatch.setattr(pollers.requests, "get", lambda *a, **k: fake_response(json_data={"data": {}}))
    result = pollers.check_target("1011209279")
    assert result["in_stock"] is False
    assert result["raw_status"] == "NOT_FOUND"


def test_target_completely_empty_response_does_not_crash(monkeypatch, fake_response):
    monkeypatch.setattr(pollers.requests, "get", lambda *a, **k: fake_response(json_data={}))
    result = pollers.check_target("1011209279")
    assert result["raw_status"] == "NOT_FOUND"


def test_target_uses_custom_api_key_when_configured(monkeypatch, fake_response):
    """If a user configures their own Target API key, it should be used
    in the actual request instead of the shared default — that's the
    whole point of letting them supply one."""
    import config
    config.set("target_api_key", "my-own-key-123")
    captured_url = {}

    def fake_get(url, headers=None, timeout=None):
        captured_url["url"] = url
        return fake_response(json_data={"data": {"product": {
            "price": {"current_retail": 10.0},
            "fulfillment": {"shipping_options": {"availability_status": "IN_STOCK"}},
        }}})

    monkeypatch.setattr(pollers.requests, "get", fake_get)
    pollers.check_target("1011209279")
    assert "key=my-own-key-123" in captured_url["url"]


def test_target_falls_back_to_shared_key_when_none_configured(monkeypatch, fake_response):
    import config
    config.set("target_api_key", "")
    captured_url = {}

    def fake_get(url, headers=None, timeout=None):
        captured_url["url"] = url
        return fake_response(json_data={"data": {"product": {
            "price": {"current_retail": 10.0},
            "fulfillment": {"shipping_options": {"availability_status": "IN_STOCK"}},
        }}})

    monkeypatch.setattr(pollers.requests, "get", fake_get)
    pollers.check_target("1011209279")
    assert "key=9f36aeafbe60771e321a7cc95a78140772ab3e96" in captured_url["url"]


def test_discover_target_api_key_finds_key_via_redsky_url_pattern(monkeypatch, fake_response):
    html = 'some page content <script>fetch("https://redsky.target.com/foo?key=abcdef0123456789abcdef0123456789&tcin=1")</script>'
    monkeypatch.setattr(pollers.requests, "get", lambda *a, **k: fake_response(text=html))
    key = pollers.discover_target_api_key()
    assert key == "abcdef0123456789abcdef0123456789"


def test_discover_target_api_key_finds_key_via_apikey_json_field(monkeypatch, fake_response):
    html = '<script>window.__CONFIG__ = {"apiKey":"11112222333344445555666677778888"};</script>'
    monkeypatch.setattr(pollers.requests, "get", lambda *a, **k: fake_response(text=html))
    key = pollers.discover_target_api_key()
    assert key == "11112222333344445555666677778888"


def test_discover_target_api_key_returns_none_when_not_found(monkeypatch, fake_response):
    monkeypatch.setattr(pollers.requests, "get", lambda *a, **k: fake_response(text="<html>nothing here</html>"))
    assert pollers.discover_target_api_key() is None


def test_discover_target_api_key_returns_none_on_network_error(monkeypatch):
    import requests

    def raise_error(*a, **k):
        raise requests.RequestException("connection failed")

    monkeypatch.setattr(pollers.requests, "get", raise_error)
    assert pollers.discover_target_api_key() is None


def test_check_pokemon_center_queue_only_detects_queue(monkeypatch, fake_response):
    monkeypatch.setattr(pollers.requests, "head",
                         lambda *a, **k: fake_response(url="https://cardalert.queue-it.net/somequeue"))
    result = pollers.check_pokemon_center_queue_only("https://www.pokemoncenter.com/product/x")
    assert result["queue_live"] is True


def test_check_pokemon_center_queue_only_no_queue(monkeypatch, fake_response):
    monkeypatch.setattr(pollers.requests, "head",
                         lambda *a, **k: fake_response(url="https://www.pokemoncenter.com/product/x"))
    result = pollers.check_pokemon_center_queue_only("https://www.pokemoncenter.com/product/x")
    assert result["queue_live"] is False


def test_check_pokemon_center_queue_only_falls_back_to_get_on_405(monkeypatch, fake_response):
    """Some servers reject HEAD on a given URL — must still detect the
    queue via a GET fallback rather than giving up."""
    monkeypatch.setattr(pollers.requests, "head", lambda *a, **k: fake_response(status_code=405))
    monkeypatch.setattr(pollers.requests, "get",
                         lambda *a, **k: fake_response(url="https://cardalert.queue-it.net/somequeue"))
    result = pollers.check_pokemon_center_queue_only("https://www.pokemoncenter.com/product/x")
    assert result["queue_live"] is True


def test_check_pokemon_center_queue_only_falls_back_to_get_on_network_error(monkeypatch, fake_response):
    import requests

    def raise_error(*a, **k):
        raise requests.RequestException("connection reset")

    monkeypatch.setattr(pollers.requests, "head", raise_error)
    monkeypatch.setattr(pollers.requests, "get",
                         lambda *a, **k: fake_response(url="https://www.pokemoncenter.com/product/x"))
    result = pollers.check_pokemon_center_queue_only("https://www.pokemoncenter.com/product/x")
    assert result["queue_live"] is False


def test_target_sends_browser_like_headers(monkeypatch, fake_response):
    """Regression guard: the request previously sent only a bare
    User-Agent, missing the Origin/Referer/Accept headers a real page
    load includes."""
    captured_headers = {}

    def fake_get(url, headers=None, timeout=None):
        captured_headers.update(headers or {})
        return fake_response(json_data={"data": {"product": {
            "price": {"current_retail": 10.0},
            "fulfillment": {"shipping_options": {"availability_status": "IN_STOCK"}},
        }}})

    monkeypatch.setattr(pollers.requests, "get", fake_get)
    pollers.check_target("1011209279")
    assert captured_headers.get("Origin") == "https://www.target.com"
    assert captured_headers.get("Accept") == "application/json"
    assert "Referer" in captured_headers


def test_target_in_stock(monkeypatch, fake_response):
    payload = {
        "data": {
            "product": {
                "price": {"current_retail": 24.99},
                "fulfillment": {"shipping_options": {"availability_status": "IN_STOCK"}},
            }
        }
    }
    monkeypatch.setattr(pollers.requests, "get", lambda *a, **k: fake_response(json_data=payload))
    result = pollers.check_target("1011209279")
    assert result["in_stock"] is True
    assert result["price"] == 24.99


def test_target_sold_out(monkeypatch, fake_response):
    payload = {
        "data": {
            "product": {
                "price": {"current_retail": 24.99},
                "fulfillment": {"shipping_options": {"availability_status": "OUT_OF_STOCK"}},
            }
        }
    }
    monkeypatch.setattr(pollers.requests, "get", lambda *a, **k: fake_response(json_data=payload))
    result = pollers.check_target("1011209279")
    assert result["in_stock"] is False


# --- Best Buy ---

def test_bestbuy_no_api_key_configured():
    result = pollers.check_bestbuy("6418599")
    assert result["raw_status"] == "NO_API_KEY"
    assert result["in_stock"] is False


def test_bestbuy_with_api_key(monkeypatch, fake_response):
    import config
    config.set("bestbuy_api_key", "fake-key")
    payload = {"products": [{"sku": "6418599", "salePrice": 19.99, "onlineAvailability": True}]}
    monkeypatch.setattr(pollers.requests, "get", lambda *a, **k: fake_response(json_data=payload))
    result = pollers.check_bestbuy("6418599")
    assert result["in_stock"] is True
    assert result["price"] == 19.99


# --- LGS generic fallback ---

def test_lgs_generic_in_stock(monkeypatch, fake_response):
    html = '<button>Add to Cart</button> <span class="price">$29.99</span>'
    monkeypatch.setattr(pollers.requests, "get", lambda *a, **k: fake_response(text=html))
    result = pollers.check_lgs_generic("https://example-lgs.com/product/x")
    assert result["in_stock"] is True
    assert result["price"] == 29.99


def test_lgs_generic_sold_out(monkeypatch, fake_response):
    html = '<div>Sold out</div>'
    monkeypatch.setattr(pollers.requests, "get", lambda *a, **k: fake_response(text=html))
    result = pollers.check_lgs_generic("https://example-lgs.com/product/x")
    assert result["in_stock"] is False
    assert result["raw_status"] == "SOLD_OUT"


# --- Shopify verifier ---

def test_verify_shopify_store_detects_shopify(monkeypatch, fake_response):
    payload = {"products": [{"id": 1}, {"id": 2}]}
    monkeypatch.setattr(pollers.requests, "get", lambda *a, **k: fake_response(json_data=payload, status_code=200))
    result = pollers.verify_shopify_store("mylocalshop.com")
    assert result["is_shopify"] is True


def test_verify_shopify_store_detects_non_shopify(monkeypatch, fake_response):
    monkeypatch.setattr(pollers.requests, "get", lambda *a, **k: fake_response(status_code=404))
    result = pollers.verify_shopify_store("notashopifystore.com")
    assert result["is_shopify"] is False


def test_verify_shopify_store_handles_connection_error(monkeypatch):
    import requests

    def raise_error(*a, **k):
        raise requests.RequestException("connection failed")

    monkeypatch.setattr(pollers.requests, "get", raise_error)
    result = pollers.verify_shopify_store("unreachable.com")
    assert result["is_shopify"] is False
