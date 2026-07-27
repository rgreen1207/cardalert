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
        assert "license key" not in html


def test_add_item_with_single_channel(client):
    client.post("/setup/skip")
    response = client.post("/items/add", data={
        "name": "Test Item", "game": "pokemon", "retailer": "target",
        "identifier": "123", "target_qty": 1, "msrp": 49.99, "max_pct_over_msrp": 0,
        "notify_channels": ["discord"],
    }, follow_redirects=False)
    assert response.status_code == 303
    items = client.get("/api/items").json()
    assert len(items) == 1
    assert items[0]["notify_channel"] == "discord"


def test_add_item_with_multiple_channels(client):
    client.post("/setup/skip")
    client.post("/items/add", data={
        "name": "Multi", "game": "pokemon", "retailer": "target",
        "identifier": "123", "target_qty": 1, "msrp": 49.99, "max_pct_over_msrp": 0,
        "notify_channels": ["discord", "ntfy"],
    })
    items = client.get("/api/items").json()
    assert items[0]["notify_channel"] == "discord,ntfy"
    assert set(items[0]["notify_channels_list"]) == {"discord", "ntfy"}


def test_add_item_with_no_channels_defaults_to_dashboard_only(client):
    client.post("/setup/skip")
    client.post("/items/add", data={
        "name": "Dashboard Only", "game": "pokemon", "retailer": "target",
        "identifier": "123", "target_qty": 1, "msrp": 49.99, "max_pct_over_msrp": 0,
    })
    items = client.get("/api/items").json()
    assert items[0]["notify_channel"] == ""
    assert items[0]["notify_channels_list"] == []


def test_mark_purchased_decrements_and_deactivates(client):
    client.post("/setup/skip")
    client.post("/items/add", data={
        "name": "Item", "game": "pokemon", "retailer": "target",
        "identifier": "123", "target_qty": 1, "msrp": 49.99, "max_pct_over_msrp": 0,
    })
    item_id = client.get("/api/items").json()[0]["id"]
    client.post(f"/items/{item_id}/mark_purchased", data={"qty": 1})
    items = client.get("/api/items").json()
    assert items[0]["remaining_qty"] == 0
    assert items[0]["active"] == 0


def test_pause_and_resume(client):
    client.post("/setup/skip")
    client.post("/items/add", data={
        "name": "Item", "game": "pokemon", "retailer": "target",
        "identifier": "123", "target_qty": 1, "msrp": 49.99, "max_pct_over_msrp": 0,
    })
    item_id = client.get("/api/items").json()[0]["id"]
    client.post(f"/items/{item_id}/pause")
    assert client.get("/api/items").json()[0]["active"] == 0
    client.post(f"/items/{item_id}/resume")
    assert client.get("/api/items").json()[0]["active"] == 1


def test_delete_item(client):
    client.post("/setup/skip")
    client.post("/items/add", data={
        "name": "Item", "game": "pokemon", "retailer": "target",
        "identifier": "123", "target_qty": 1, "msrp": 49.99, "max_pct_over_msrp": 0,
    })
    item_id = client.get("/api/items").json()[0]["id"]
    client.post(f"/items/{item_id}/delete")
    assert client.get("/api/items").json() == []


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
    assert "error" in data


def test_discord_test_endpoint_fires_when_configured(client, monkeypatch):
    client.post("/setup/skip")
    client.post("/settings/save", data={
        "currency": "USD",
        "discord_webhook_url": "https://discord.com/api/webhooks/fake",
    })
    import notifier
    monkeypatch.setattr(notifier, "send_discord", lambda msg: True)
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
    client.post("/items/add", data={
        "name": "Item", "game": "pokemon", "retailer": "target",
        "identifier": "123", "target_qty": 1, "msrp": 49.99, "max_pct_over_msrp": 0,
    })
    item_id = client.get("/api/items").json()[0]["id"]
    response = client.get(f"/items/{item_id}/pattern")
    assert response.status_code == 404


def test_amazon_retailer_available_in_products_form(client):
    client.post("/setup/skip")
    html = client.get("/products").text
    assert 'value="amazon"' in html
