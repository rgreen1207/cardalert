from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from typing import Optional

import db
import scheduler
import pollers
import license as licensing
import config

app = FastAPI(title="Card Alert")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

import base64

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
            pass  # malformed Authorization header — falls through to 401 below
    from starlette.responses import Response
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
    return item


@app.get("/")
def dashboard(request: Request):
    items = [_enrich(i) for i in db.list_items()]
    alerts = db.recent_alerts(limit=20)
    signals = db.recent_drop_signals(limit=15)
    pc_window_open = scheduler.pokemon_center_window_open()
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "active_page": "dashboard",
        "items": items,
        "alerts": alerts,
        "signals": signals,
        "pc_window_open": pc_window_open,
        "is_pro": licensing.is_pro(),
    })


@app.get("/products")
def products_page(request: Request, error: Optional[str] = None):
    items = [_enrich(i) for i in db.list_items()]
    active_retailers = {i["retailer"] for i in db.list_items(active_only=True)}
    return templates.TemplateResponse("products.html", {
        "request": request,
        "active_page": "products",
        "items": items,
        "retailers": ["target", "walmart", "bestbuy", "bn", "pokemon_center", "lgs_shopify", "lgs_generic"],
        "games": ["pokemon", "mtg", "yugioh", "onepiece", "other"],
        "channels": ["dashboard", "discord", "ntfy", "pushover", "sms"],
        "is_pro": licensing.is_pro(),
        "retailer_limit_reached": (not licensing.is_pro()) and len(active_retailers) >= licensing.FREE_TIER_RETAILER_LIMIT,
        "free_retailer_limit": licensing.FREE_TIER_RETAILER_LIMIT,
        "error": error,
    })


@app.get("/setup")
def setup_wizard(request: Request):
    return templates.TemplateResponse("setup.html", {
        "request": request,
        "values": config.all_values(),
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
        "is_pro": licensing.is_pro(),
        "saved": saved,
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
    gumroad_product_id: str = Form(""),
    cardalert_license_key: str = Form(""),
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
        "gumroad_product_id": gumroad_product_id,
        "cardalert_license_key": cardalert_license_key,
    }.items():
        config.set(key, value)
    if dashboard_password:
        # blank field on the settings page means "leave unchanged" — the
        # stored hash is never rendered back into the form to fill this in
        config.set_dashboard_password(dashboard_password)
    return RedirectResponse("/settings?saved=1", status_code=303)


@app.get("/help")
def help_page(request: Request):
    return templates.TemplateResponse("help.html", {"request": request, "active_page": "help"})


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
    notify_channel: str = Form("dashboard"),
):
    active_retailers = {i["retailer"] for i in db.list_items(active_only=True)}
    if retailer not in active_retailers and not licensing.enforce_retailer_limit(active_retailers):
        return RedirectResponse("/products?error=retailer_limit", status_code=303)
    if not licensing.channel_allowed(notify_channel):
        notify_channel = "dashboard"
    db.add_item(name, game, retailer, identifier, product_url, target_qty, msrp,
                max_pct_over_msrp, notify_channel)
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
    if not licensing.feature_allowed("pattern_analytics"):
        return JSONResponse({"error": "pattern analytics is a pro-tier feature"}, status_code=403)
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
