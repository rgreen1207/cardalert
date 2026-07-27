from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from typing import Optional

import db
import scheduler
import pollers
import license as licensing

app = FastAPI(title="Card Alert")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


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
