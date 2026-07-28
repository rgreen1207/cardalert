from typing import Optional, List

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

import db
import pollers
import config
import fx
from templating import templates
from view_helpers import (
    enrich_product, with_display_prices, common_context, display_maps,
    RETAILERS, GAMES, PUSH_CHANNELS,
)

router = APIRouter()


@router.get("/products")
async def products_page(request: Request):
    currency = await config.get("currency")
    products = [await with_display_prices(await enrich_product(p), currency) for p in await db.list_products()]
    ctx = await common_context(request, "products")
    ctx.update(products=products, retailers=RETAILERS, games=GAMES, push_channels=PUSH_CHANNELS)
    ctx.update(display_maps())
    return templates.TemplateResponse("products.html", ctx)


@router.post("/products/add")
async def add_product(
    name: str = Form(...),
    game: str = Form("pokemon"),
    target_qty: int = Form(1),
    msrp: Optional[float] = Form(None),
    max_pct_over_msrp: float = Form(0),
    notify_channels: List[str] = Form([]),
    retailer: List[str] = Form([]),
    identifier: List[str] = Form([]),
    product_url: List[str] = Form([]),
):
    currency = await config.get("currency")
    msrp_usd = await fx.display_to_usd(msrp, currency) if msrp is not None else None
    channels_csv = ",".join(notify_channels)
    retailer_rows = [
        {"retailer": r, "identifier": i, "product_url": u}
        for r, i, u in zip(retailer, identifier, product_url)
        if r and i
    ]
    await db.add_product_with_retailers(name, game, target_qty, msrp_usd, max_pct_over_msrp,
                                         channels_csv, retailer_rows)
    return RedirectResponse("/products", status_code=303)


@router.get("/products/{product_id}/edit")
async def edit_product_page(request: Request, product_id: int, saved: Optional[str] = None):
    product = await db.get_product_with_retailers(product_id)
    if not product:
        return RedirectResponse("/products", status_code=303)
    currency = await config.get("currency")
    product = await with_display_prices(await enrich_product(product), currency)
    ctx = await common_context(request, "products")
    ctx.update(product=product, retailers=RETAILERS, games=GAMES, push_channels=PUSH_CHANNELS,
               saved=saved)
    ctx.update(display_maps())
    return templates.TemplateResponse("edit_product.html", ctx)


@router.post("/products/{product_id}/edit")
async def edit_product_save(
    product_id: int,
    name: str = Form(...),
    game: str = Form("pokemon"),
    target_qty: int = Form(1),
    msrp: float = Form(...),
    max_pct_over_msrp: float = Form(0),
    notify_channels: List[str] = Form([]),
):
    currency = await config.get("currency")
    msrp_usd = await fx.display_to_usd(msrp, currency)
    channels_csv = ",".join(notify_channels)
    await db.update_product(product_id, name, game, target_qty, msrp_usd, max_pct_over_msrp, channels_csv)
    return RedirectResponse(f"/products/{product_id}/edit?saved=1", status_code=303)


@router.post("/products/{product_id}/retailers/add")
async def add_retailer_to_product(
    product_id: int,
    retailer: str = Form(...),
    identifier: str = Form(...),
    product_url: str = Form(""),
):
    await db.add_retailer(product_id, retailer, identifier, product_url)
    return RedirectResponse(f"/products/{product_id}/edit", status_code=303)


@router.post("/retailers/{product_retailer_id}/remove")
async def remove_retailer(product_retailer_id: int):
    row = await db.get_retailer(product_retailer_id)
    product_id = row["product_id"] if row else None
    await db.remove_retailer(product_retailer_id)
    if product_id:
        return RedirectResponse(f"/products/{product_id}/edit", status_code=303)
    return RedirectResponse("/products", status_code=303)


@router.post("/products/{product_id}/delete")
async def remove_product(product_id: int):
    await db.delete_product(product_id)
    return RedirectResponse("/products", status_code=303)


@router.post("/products/{product_id}/pause")
async def pause_product(product_id: int):
    await db.set_product_active(product_id, False)
    return RedirectResponse("/products", status_code=303)


@router.post("/products/{product_id}/resume")
async def resume_product(product_id: int):
    await db.set_product_active(product_id, True)
    return RedirectResponse("/products", status_code=303)


@router.post("/products/{product_id}/mark_purchased")
async def mark_purchased(product_id: int, qty: int = Form(1)):
    product = await db.get_product(product_id)
    if product:
        new_remaining = max(0, product["remaining_qty"] - qty)
        await db.update_remaining(product_id, new_remaining)
    return RedirectResponse("/products", status_code=303)


@router.post("/tools/verify-shopify")
async def verify_shopify(domain: str = Form(...)):
    return await pollers.verify_shopify_store(domain)
