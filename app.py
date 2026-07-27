import base64
from typing import Optional, List

from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.responses import Response

import db
import scheduler
import pollers
import notifier
import config

app = FastAPI(title="Card Alert")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

DONATE_URL = "https://ko-fi.com/ryanthedev"

_EXEMPT_FROM_SETUP_REDIRECT = {"/setup", "/setup/save", "/setup/skip"}


@app.middleware("http")
async def require_setup(request: Request, call_next):
    path = request.url.path
    if (
        not path.startswith("/static")
        and path not in _EXEMPT_FROM_SETUP_REDIRECT
        and not config.is_setup_complete()
    ):
        return RedirectResponse("/setup")
    return await call_next(request)


@app.middleware("http")
async def require_dashboard_password(request: Request, call_next):
    if not config.dashboard_password_is_set():
        return await call_next(request)
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Basic "):
        try:
            decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
            _, _, supplied_password = decoded.partition(":")
            if config.check_dashboard_password(supplied_password):
                return await call_next(request)
        except (ValueError, UnicodeDecodeError):
            pass  # malformed Authorization header, falls through to 401 below
    return Response(
        status_code=401,
        headers={"WWW-Authenticate": 'Basic realm="Card Alert"'},
        content="Password required.",
    )


@app.on_event("startup")
def startup():
    db.init_db()
    scheduler.start_background_thread()


def _enrich(item: dict) -> dict:
    item["last_status"] = db.latest_status(item["id"])
    item["notify_channels_list"] = [c for c in (item.get("notify_channel") or "").split(",") if c]
    return item


def _common_context(request: Request, active_page: str) -> dict:
    return {
        "request": request,
        "active_page": active_page,
        "donate_url": DONATE_URL,
        "currency_symbol": config.currency_symbol(),
    }


@app.get("/")
def dashboard(request: Request):
    items = [_enrich(i) for i in db.list_items()]
    alerts = db.recent_alerts(limit=20)
    signals = db.recent_drop_signals(limit=15)
    pc_window_open = scheduler.pokemon_center_window_open()
    ctx = _common_context(request, "dashboard")
    ctx.update(items=items, alerts=alerts, signals=signals, pc_window_open=pc_window_open)
    return templates.TemplateResponse("dashboard.html", ctx)


@app.get("/products")
def products_page(request: Request):
    items = [_enrich(i) for i in db.list_items()]
    ctx = _common_context(request, "products")
    ctx.update(
        items=items,
        retailers=["target", "walmart", "bestbuy", "bn", "pokemon_center", "amazon", "lgs_shopify", "lgs_generic"],
        games=["pokemon", "mtg", "yugioh", "onepiece", "other"],
        push_channels=["discord", "ntfy", "pushover", "sms"],
    )
    return templates.TemplateResponse("products.html", ctx)


@app.get("/setup")
def setup_wizard(request: Request):
    return templates.TemplateResponse("setup.html", {
        "request": request,
        "values": config.all_values(),
        "donate_url": DONATE_URL,
    })


@app.post("/setup/save")
def setup_save(
    discord_webhook_url: str = Form(""),
    ntfy_topic: str = Form(""),
    pushover_user_key: str = Form(""),
    pushover_app_token: str = Form(""),
    twilio_account_sid: str = Form(""),
    twilio_auth_token: str = Form(""),
    twilio_from_number: str = Form(""),
    twilio_to_number: str = Form(""),
    bestbuy_api_key: str = Form(""),
    dashboard_password: str = Form(""),
):
    for key, value in {
        "discord_webhook_url": discord_webhook_url,
        "ntfy_topic": ntfy_topic,
        "pushover_user_key": pushover_user_key,
        "pushover_app_token": pushover_app_token,
        "twilio_account_sid": twilio_account_sid,
        "twilio_auth_token": twilio_auth_token,
        "twilio_from_number": twilio_from_number,
        "twilio_to_number": twilio_to_number,
        "bestbuy_api_key": bestbuy_api_key,
    }.items():
        if value:
            config.set(key, value)
    if dashboard_password:
        config.set_dashboard_password(dashboard_password)
    config.mark_setup_complete()
    return RedirectResponse("/products", status_code=303)


@app.post("/setup/skip")
def setup_skip():
    config.mark_setup_complete()
    return RedirectResponse("/products", status_code=303)


@app.get("/settings")
def settings_page(request: Request, saved: Optional[str] = None):
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "active_page": "settings",
        "values": config.all_values(),
        "saved": saved,
        "donate_url": DONATE_URL,
        "currencies": list(config.CURRENCY_SYMBOLS.keys()),
    })


@app.post("/settings/save")
def settings_save(
    discord_webhook_url: str = Form(""),
    ntfy_topic: str = Form(""),
    pushover_user_key: str = Form(""),
    pushover_app_token: str = Form(""),
    twilio_account_sid: str = Form(""),
    twilio_auth_token: str = Form(""),
    twilio_from_number: str = Form(""),
    twilio_to_number: str = Form(""),
    bestbuy_api_key: str = Form(""),
    currency: str = Form("USD"),
    dashboard_password: str = Form(""),
):
    for key, value in {
        "discord_webhook_url": discord_webhook_url,
        "ntfy_topic": ntfy_topic,
        "pushover_user_key": pushover_user_key,
        "pushover_app_token": pushover_app_token,
        "twilio_account_sid": twilio_account_sid,
        "twilio_auth_token": twilio_auth_token,
        "twilio_from_number": twilio_from_number,
        "twilio_to_number": twilio_to_number,
        "bestbuy_api_key": bestbuy_api_key,
        "currency": currency,
    }.items():
        config.set(key, value)
    if dashboard_password:
        # blank field on the settings page means "leave unchanged." The
        # stored hash is never rendered back into the form to fill this in
        config.set_dashboard_password(dashboard_password)
    return RedirectResponse("/settings?saved=1", status_code=303)


@app.post("/settings/test-discord")
def test_discord():
    url = config.get("discord_webhook_url")
    if not url:
        return JSONResponse({"ok": False, "error": "No Discord webhook URL saved yet."})
    ok = notifier.send_discord("🔔 Test alert from Card Alert. If you see this, your Discord webhook works.")
    return JSONResponse({"ok": ok})


@app.get("/help")
def help_page(request: Request):
    ctx = _common_context(request, "help")
    return templates.TemplateResponse("help.html", ctx)


@app.post("/items/add")
def add_item(
    name: str = Form(...),
    game: str = Form("pokemon"),
    retailer: str = Form(...),
    identifier: str = Form(...),
    product_url: str = Form(""),
    target_qty: int = Form(1),
    msrp: Optional[float] = Form(None),
    max_pct_over_msrp: float = Form(0),
    notify_channels: List[str] = Form([]),
):
    channels_csv = ",".join(notify_channels)
    db.add_item(name, game, retailer, identifier, product_url, target_qty, msrp,
                max_pct_over_msrp, channels_csv)
    return RedirectResponse("/products", status_code=303)


@app.post("/items/{item_id}/delete")
def remove_item(item_id: int):
    db.delete_item(item_id)
    return RedirectResponse("/products", status_code=303)


@app.post("/items/{item_id}/pause")
def pause_item(item_id: int):
    db.set_active(item_id, False)
    return RedirectResponse("/products", status_code=303)


@app.post("/items/{item_id}/resume")
def resume_item(item_id: int):
    db.set_active(item_id, True)
    return RedirectResponse("/products", status_code=303)


@app.post("/items/{item_id}/mark_purchased")
def mark_purchased(item_id: int, qty: int = Form(1)):
    item = db.get_item(item_id)
    if item:
        new_remaining = max(0, item["remaining_qty"] - qty)
        db.update_remaining(item_id, new_remaining)
    return RedirectResponse("/products", status_code=303)


@app.get("/items/{item_id}/pattern")
def item_pattern(item_id: int):
    pattern = db.restock_pattern(item_id)
    if not pattern:
        return JSONResponse({"error": "not enough history yet"}, status_code=404)
    return pattern


@app.post("/tools/verify-shopify")
def verify_shopify(domain: str = Form(...)):
    return pollers.verify_shopify_store(domain)


@app.get("/api/items")
def api_items():
    return [_enrich(i) for i in db.list_items()]
