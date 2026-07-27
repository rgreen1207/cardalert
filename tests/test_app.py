import config


def test_first_request_redirects_to_setup(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert "/setup" in response.headers["location"]


def test_setup_skip_marks_complete_and_redirects(client):
    response = client.post("/setup/skip", follow_redirects=False)
    assert response.status_code == 303
    assert config.is_setup_complete() is True


def test_dashboard_accessible_after_setup(client):
    client.post("/setup/skip")
    response = client.get("/")
    assert response.status_code == 200


def test_all_main_pages_load_after_setup(client):
    client.post("/setup/skip")
    for path in ["/", "/products", "/settings", "/help"]:
        response = client.get(path)
        assert response.status_code == 200, f"{path} failed"


def test_no_pro_or_license_language_anywhere(client):
    """Regression guard: the paywall was fully removed — make sure it stays
    removed. If this test starts failing, someone reintroduced gating."""
    client.post("/setup/skip")
    for path in ["/", "/products", "/settings", "/help"]:
        html = client.get(path).text.lower()
        assert "gumroad" not in html
        assert "pro tier" not in html
        assert "pro-tier" not in html
        assert "license key" not in html


def _add_product(client, name="Item", game="pokemon", retailers=None, follow_redirects=True, **kwargs):
    """Helper matching the multi-retailer add form's field shape: retailer,
    identifier, and product_url are repeated fields (parallel lists), one
    triple per attached retailer."""
    retailers = retailers or [{"retailer": "target", "identifier": "123", "product_url": ""}]
    data = {
        "name": name, "game": game, "target_qty": kwargs.get("target_qty", 1),
        "msrp": kwargs.get("msrp", 49.99), "max_pct_over_msrp": kwargs.get("max_pct_over_msrp", 0),
        "retailer": [r["retailer"] for r in retailers],
        "identifier": [r["identifier"] for r in retailers],
        "product_url": [r.get("product_url", "") for r in retailers],
    }
    if "notify_channels" in kwargs:
        data["notify_channels"] = kwargs["notify_channels"]
    return client.post("/products/add", data=data, follow_redirects=follow_redirects)


def test_pattern_endpoint_never_gated_behind_a_tier(client):
    """Specifically guards against the exact bug report: clicking
    'pattern' returned a 'pattern analytics is a pro-tier feature'
    message. Pattern analytics has no gating at all, at any history
    level — the only valid non-200 response is 404 for insufficient
    history, never 403."""
    client.post("/setup/skip")
    _add_product(client)
    retailer_id = client.get("/api/items").json()[0]["retailers"][0]["id"]
    response = client.get(f"/retailers/{retailer_id}/pattern")
    assert response.status_code != 403
    body_text = str(response.json()).lower()
    assert "pro" not in body_text
    assert "tier" not in body_text


def test_donate_link_points_to_real_kofi_url_on_every_page(client):
    """Regression guard for the reported bug: donate links rendering with
    an empty or missing href just reload the current page instead of
    opening Ko-fi. Every page must render the real external URL with
    target="_blank", not a placeholder."""
    client.post("/setup/skip")
    for path in ["/", "/products", "/settings", "/help"]:
        html = client.get(path).text
        assert 'href="https://ko-fi.com/ryanthedev"' in html
        assert 'target="_blank"' in html
        assert 'href=""' not in html
        assert 'href="#"' not in html


def test_add_product_with_single_retailer(client):
    client.post("/setup/skip")
    response = _add_product(client, notify_channels=["discord"], follow_redirects=False)
    assert response.status_code == 303
    products = client.get("/api/items").json()
    assert len(products) == 1
    assert products[0]["notify_channel"] == "discord"
    assert len(products[0]["retailers"]) == 1
    assert products[0]["retailers"][0]["retailer"] == "target"


def test_add_product_with_multiple_retailers(client):
    """The actual feature request: one product, multiple retailers
    attached, each checked independently."""
    client.post("/setup/skip")
    _add_product(client, retailers=[
        {"retailer": "target", "identifier": "123", "product_url": ""},
        {"retailer": "amazon", "identifier": "B0D7QJXK9P", "product_url": ""},
        {"retailer": "walmart", "identifier": "https://walmart.com/ip/456", "product_url": ""},
    ])
    products = client.get("/api/items").json()
    assert len(products) == 1
    retailer_names = {r["retailer"] for r in products[0]["retailers"]}
    assert retailer_names == {"target", "amazon", "walmart"}


def test_add_product_with_no_channels_defaults_to_dashboard_only(client):
    client.post("/setup/skip")
    _add_product(client)
    products = client.get("/api/items").json()
    assert products[0]["notify_channel"] == ""
    assert products[0]["notify_channels_list"] == []


def test_mark_purchased_decrements_and_deactivates(client):
    client.post("/setup/skip")
    _add_product(client, target_qty=1)
    product_id = client.get("/api/items").json()[0]["id"]
    client.post(f"/products/{product_id}/mark_purchased", data={"qty": 1})
    products = client.get("/api/items").json()
    assert products[0]["remaining_qty"] == 0
    assert products[0]["active"] == 0


def test_pause_and_resume(client):
    client.post("/setup/skip")
    _add_product(client)
    product_id = client.get("/api/items").json()[0]["id"]
    client.post(f"/products/{product_id}/pause")
    assert client.get("/api/items").json()[0]["active"] == 0
    client.post(f"/products/{product_id}/resume")
    assert client.get("/api/items").json()[0]["active"] == 1


def test_delete_product_removes_it_and_its_retailers(client):
    client.post("/setup/skip")
    _add_product(client, retailers=[
        {"retailer": "target", "identifier": "1", "product_url": ""},
        {"retailer": "amazon", "identifier": "2", "product_url": ""},
    ])
    product_id = client.get("/api/items").json()[0]["id"]
    client.post(f"/products/{product_id}/delete")
    assert client.get("/api/items").json() == []


def test_add_retailer_to_existing_product(client):
    client.post("/setup/skip")
    _add_product(client)
    product_id = client.get("/api/items").json()[0]["id"]
    response = client.post(f"/products/{product_id}/retailers/add", data={
        "retailer": "amazon", "identifier": "B0D7QJXK9P", "product_url": "",
    }, follow_redirects=False)
    assert response.status_code == 303
    product = client.get("/api/items").json()[0]
    assert len(product["retailers"]) == 2
    assert {r["retailer"] for r in product["retailers"]} == {"target", "amazon"}


def test_remove_one_retailer_leaves_others_and_product_intact(client):
    client.post("/setup/skip")
    _add_product(client, retailers=[
        {"retailer": "target", "identifier": "1", "product_url": ""},
        {"retailer": "amazon", "identifier": "2", "product_url": ""},
    ])
    product = client.get("/api/items").json()[0]
    target_retailer_id = next(r["id"] for r in product["retailers"] if r["retailer"] == "target")
    response = client.post(f"/retailers/{target_retailer_id}/remove", follow_redirects=False)
    assert response.status_code == 303
    product_after = client.get("/api/items").json()[0]
    assert len(product_after["retailers"]) == 1
    assert product_after["retailers"][0]["retailer"] == "amazon"
    assert product_after["name"] == product["name"]  # product itself untouched


def test_settings_save_persists_currency(client):
    client.post("/setup/skip")
    response = client.post("/settings/save", data={"currency": "GBP"}, follow_redirects=False)
    assert response.status_code == 303
    assert config.get("currency") == "GBP"


def test_settings_save_sets_dashboard_password(client):
    client.post("/setup/skip")
    client.post("/settings/save", data={"currency": "USD", "dashboard_password": "hunter2"})
    assert config.dashboard_password_is_set() is True
    assert config.check_dashboard_password("hunter2") is True


def test_dashboard_password_blocks_access_until_authenticated(client):
    client.post("/setup/skip")
    client.post("/settings/save", data={"currency": "USD", "dashboard_password": "hunter2"})
    unauthenticated = client.get("/")
    assert unauthenticated.status_code == 401

    import base64
    creds = base64.b64encode(b"cardalert:hunter2").decode()
    authenticated = client.get("/", headers={"Authorization": f"Basic {creds}"})
    assert authenticated.status_code == 200

    wrong_creds = base64.b64encode(b"cardalert:wrongpassword").decode()
    rejected = client.get("/", headers={"Authorization": f"Basic {wrong_creds}"})
    assert rejected.status_code == 401


def test_discord_test_endpoint_no_webhook_configured(client):
    client.post("/setup/skip")
    response = client.post("/settings/test-discord")
    data = response.json()
    assert data["ok"] is False
    assert data["detail"]


def test_discord_test_endpoint_fires_when_configured(client, monkeypatch):
    client.post("/setup/skip")
    client.post("/settings/save", data={
        "currency": "USD",
        "discord_webhook_url": "https://discord.com/api/webhooks/fake",
    })
    import notifier
    monkeypatch.setattr(notifier, "send_discord", lambda msg: {"ok": True, "status": 204, "detail": None})
    response = client.post("/settings/test-discord")
    assert response.json()["ok"] is True


def test_verify_shopify_endpoint(client, monkeypatch, fake_response):
    client.post("/setup/skip")
    import pollers
    monkeypatch.setattr(pollers.requests, "get",
                         lambda *a, **k: fake_response(json_data={"products": [{"id": 1}]}))
    response = client.post("/tools/verify-shopify", data={"domain": "example.com"})
    assert response.json()["is_shopify"] is True


def test_pattern_endpoint_no_history(client):
    client.post("/setup/skip")
    _add_product(client)
    retailer_id = client.get("/api/items").json()[0]["retailers"][0]["id"]
    response = client.get(f"/retailers/{retailer_id}/pattern")
    assert response.status_code == 404


def test_amazon_retailer_available_in_products_form(client):
    client.post("/setup/skip")
    html = client.get("/products").text
    assert 'value="amazon"' in html


def test_check_update_endpoint(client, monkeypatch):
    client.post("/setup/skip")
    import updater
    monkeypatch.setattr(updater, "check_for_update", lambda: {
        "current": "v1.0.0", "latest": "v1.1.0", "update_available": True, "error": None,
    })
    response = client.get("/settings/check-update")
    data = response.json()
    assert data["update_available"] is True
    assert data["latest"] == "v1.1.0"


def test_apply_update_endpoint(client, monkeypatch):
    client.post("/setup/skip")
    import updater
    monkeypatch.setattr(updater, "apply_update", lambda: {
        "ok": True, "updated": True, "message": "Updated to v1.1.0. Restarting now.",
    })
    response = client.post("/settings/apply-update")
    data = response.json()
    assert data["ok"] is True
    assert data["updated"] is True


def test_settings_page_shows_current_version(client, monkeypatch):
    client.post("/setup/skip")
    import updater
    monkeypatch.setattr(updater, "current_ref", lambda: "v1.0.0")
    html = client.get("/settings").text
    assert "v1.0.0" in html


def test_edit_product_page_loads(client):
    client.post("/setup/skip")
    _add_product(client, name="Item")
    product_id = client.get("/api/items").json()[0]["id"]
    response = client.get(f"/products/{product_id}/edit")
    assert response.status_code == 200
    assert "Item" in response.text


def test_edit_product_page_for_missing_product_redirects(client):
    client.post("/setup/skip")
    response = client.get("/products/99999/edit", follow_redirects=False)
    assert response.status_code == 303


def test_edit_product_save_updates_product_level_fields(client):
    client.post("/setup/skip")
    _add_product(client, name="Original", notify_channels=["discord"])
    product_id = client.get("/api/items").json()[0]["id"]
    response = client.post(f"/products/{product_id}/edit", data={
        "name": "Renamed", "game": "mtg", "target_qty": 3,
        "msrp": 79.99, "max_pct_over_msrp": 10,
        "notify_channels": ["ntfy", "sms"],
    }, follow_redirects=False)
    assert response.status_code == 303
    product = client.get("/api/items").json()[0]
    assert product["name"] == "Renamed"
    assert product["game"] == "mtg"
    assert set(product["notify_channels_list"]) == {"ntfy", "sms"}
    # editing product-level fields must not touch the attached retailer
    assert product["retailers"][0]["retailer"] == "target"


def test_edit_product_converts_msrp_from_display_currency(client, monkeypatch):
    client.post("/setup/skip")
    client.post("/settings/save", data={"currency": "GBP"})
    import fx
    monkeypatch.setattr(fx, "get_rate", lambda currency: {"rate": 0.80, "stale": False})
    _add_product(client, msrp=80.0)
    product_id = client.get("/api/items").json()[0]["id"]
    client.post(f"/products/{product_id}/edit", data={
        "name": "Item", "game": "pokemon", "target_qty": 1,
        "msrp": 80.0, "max_pct_over_msrp": 0,
    })
    product = client.get("/api/items").json()[0]
    # 80 GBP entered, at rate 0.80 GBP-per-USD, should store as 100 USD
    assert abs(product["msrp"] - 100.0) < 0.01


def test_products_page_shows_display_currency_prices(client, monkeypatch):
    client.post("/setup/skip")
    client.post("/settings/save", data={"currency": "GBP"})
    import fx
    monkeypatch.setattr(fx, "get_rate", lambda currency: {"rate": 0.80, "stale": False})
    # Entered while currency is already GBP, so "100.0" here means 100 GBP.
    # It should store as 125 USD (100 / 0.80) and round-trip back to
    # exactly 100 GBP on display, not get double-converted.
    _add_product(client, msrp=100.0)
    product = client.get("/api/items").json()[0]
    assert abs(product["msrp"] - 125.0) < 0.01  # stored in USD
    html = client.get("/products").text
    assert "£100.00" in html  # displayed back in the currency it was entered in


def test_retailer_and_game_names_are_capitalized_on_products_page(client):
    client.post("/setup/skip")
    _add_product(client, game="pokemon", retailers=[
        {"retailer": "bestbuy", "identifier": "123", "product_url": ""},
    ])
    html = client.get("/products").text
    assert "Best Buy" in html
    assert "Pokémon" in html


def test_discord_mention_fields_save_and_load(client):
    client.post("/setup/skip")
    client.post("/settings/save", data={
        "currency": "USD", "discord_mention_type": "role", "discord_mention_id": "999888777",
    })
    import config
    assert config.get("discord_mention_type") == "role"
    assert config.get("discord_mention_id") == "999888777"


def test_products_page_never_500s_when_fx_fetch_returns_malformed_data(client, monkeypatch):
    """Direct regression test for the reported bug: a 500 on /products.
    Simulates the exchange-rate API returning something unparseable while
    currency is set to something other than USD (which is what triggers
    the network call on every page load)."""
    client.post("/setup/skip")
    client.post("/settings/save", data={"currency": "GBP"})
    import json
    import fx

    class MalformedResponse:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            raise json.JSONDecodeError("bad json", "not json", 0)

    monkeypatch.setattr(fx.requests, "get", lambda *a, **k: MalformedResponse())
    for path in ["/", "/products"]:
        response = client.get(path)
        assert response.status_code == 200


def test_ads_config_removed_cleanly(client):
    """Confirms the removed AdSense feature left no trace: no script
    tags, no leftover context keys causing template errors."""
    client.post("/setup/skip")
    for path in ["/", "/products", "/settings"]:
        html = client.get(path).text
        assert "adsense" not in html.lower()
        assert "adsbygoogle" not in html
