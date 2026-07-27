from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import db
import scheduler
import config
from templating import templates
from view_helpers import enrich_product, with_display_prices, common_context, format_timestamp

router = APIRouter()


@router.get("/")
def dashboard(request: Request):
    ctx = common_context(request, "dashboard")
    currency = ctx["currency"]
    products = [with_display_prices(enrich_product(p), currency) for p in db.list_products()]
    db.purge_old_alerts(older_than_days=7)
    alerts = db.recent_alerts(limit=20)
    for a in alerts:
        a["when"] = format_timestamp(a["ts"])
    signals = db.recent_drop_signals(limit=15)
    pc_window_open = scheduler.pokemon_center_window_open()
    ctx.update(products=products, alerts=alerts, signals=signals, pc_window_open=pc_window_open)
    return templates.TemplateResponse("dashboard.html", ctx)


@router.get("/retailers/{product_retailer_id}/pattern")
def retailer_pattern(product_retailer_id: int):
    pattern = db.restock_pattern(product_retailer_id)
    if not pattern:
        return JSONResponse({"error": "not enough history yet"}, status_code=404)
    return pattern
