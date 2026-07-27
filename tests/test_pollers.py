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
