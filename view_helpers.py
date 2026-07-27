"""
Shared view-layer helpers used by every router. Kept separate from any one
router so dashboard/products/settings can all enrich products the same
way without importing each other.
"""
from datetime import datetime
from fastapi import Request

import db
import fx
import display
import config

DONATE_URL = "https://ko-fi.com/ryanthedev"
RETAILERS = ["target", "walmart", "bestbuy", "bn", "pokemon_center", "amazon", "lgs_shopify", "lgs_generic"]
GAMES = ["pokemon", "mtg", "yugioh", "onepiece", "other"]
PUSH_CHANNELS = ["discord", "ntfy", "pushover", "sms"]


def format_timestamp(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%b %d, %I:%M %p").replace(" 0", " ")


def enrich_product(product: dict) -> dict:
    """Adds display-ready fields to a product and each of its attached
    retailers: latest status per retailer, a parsed notify-channel list,
    and human-readable names throughout."""
    product["game_display"] = display.game_name(product.get("game", ""))
    product["notify_channels_list"] = [c for c in (product.get("notify_channel") or "").split(",") if c]
    for r in product.get("retailers", []):
        r["retailer_display"] = display.retailer_name(r.get("retailer", ""))
        status = db.latest_status(r["id"])
        if status:
            status["status_display"] = display.status_label(status.get("raw_status", ""))
        r["last_status"] = status
    return product


def with_display_prices(product: dict, currency: str) -> dict:
    """Adds display_msrp on the product and display_price on each
    retailer, converted from the stored USD values. The stored USD values
    themselves are never touched here, since the over-price comparison
    logic in scheduler.py depends on comparing like currencies against
    what retailers actually report (always USD)."""
    product["display_msrp"] = fx.usd_to_display(product.get("msrp"), currency)
    for r in product.get("retailers", []):
        status = r.get("last_status")
        if status and status.get("price") is not None:
            r["display_price"] = fx.usd_to_display(status["price"], currency)
        else:
            r["display_price"] = None
    return product


def best_status_for_product(product: dict) -> dict:
    """For summary views (the dashboard's single-row-per-product case):
    picks the most noteworthy status across all of a product's retailers —
    an in-stock, unignored hit beats everything else, so you never miss
    that at least one retailer has it, even if others are sold out."""
    retailers = product.get("retailers", [])
    for r in retailers:
        status = r.get("last_status")
        if status and status.get("in_stock") and not status.get("ignored_over_price"):
            return {"retailer": r, "status": status, "in_stock": True}
    if retailers:
        r = retailers[0]
        return {"retailer": r, "status": r.get("last_status"), "in_stock": False}
    return {"retailer": None, "status": None, "in_stock": False}


def common_context(request: Request, active_page: str) -> dict:
    currency = config.get("currency")
    rate_info = fx.get_rate(currency)
    return {
        "request": request,
        "active_page": active_page,
        "donate_url": DONATE_URL,
        "currency": currency,
        "currency_symbol": config.currency_symbol(),
        "fx_stale": rate_info["stale"] and currency != "USD",
    }


def display_maps() -> dict:
    """The retailer/game/channel name lookups every add/edit form needs."""
    return {
        "retailer_display": {r: display.retailer_name(r) for r in RETAILERS},
        "game_display": {g: display.game_name(g) for g in GAMES},
        "channel_display": {c: display.channel_name(c) for c in PUSH_CHANNELS},
    }
