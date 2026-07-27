"""
Retailer pollers.

IMPORTANT SCOPE NOTE (read this before extending):
Every function here does exactly one thing: fetch a public page/endpoint and
read back stock + price. None of these functions add to cart, log in, hold a
session, or submit any action on a retailer's site. That line is intentional —
see PROJECT_LOG.md for why. If you're future-Claude or future-Ryan extending
this file, keep new pollers read-only.

Each poller returns a dict:
    {"in_stock": bool, "price": float | None, "raw_status": str}
or raises on a hard failure (caller handles logging/backoff).
"""
import os
import re
import json
import requests
import config

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}
TIMEOUT = 12


def check_target(tcin: str):
    """Target's public redsky aggregation endpoint. `tcin` is the numeric id
    in the product URL, e.g. target.com/p/-/A-1011209279 -> tcin=1011209279."""
    url = (
        "https://redsky.target.com/redsky_aggregations/v1/web/pdp_client_v1"
        f"?key=9f36aeafbe60771e321a7cc95a78140772ab3e96&tcin={tcin}"
        "&pricing_store_id=3991&is_bot=false"
    )
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    product = data["data"]["product"]
    price = product.get("price", {}).get("current_retail")
    avail = (
        product.get("fulfillment", {})
        .get("shipping_options", {})
        .get("availability_status", "UNKNOWN")
    )
    in_stock = avail == "IN_STOCK"
    return {"in_stock": in_stock, "price": price, "raw_status": avail}


def check_walmart(product_url: str):
    """Scrapes the __NEXT_DATA__ JSON blob embedded in a Walmart product page."""
    r = requests.get(product_url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        r.text, re.DOTALL,
    )
    if not match:
        return {"in_stock": False, "price": None, "raw_status": "PARSE_FAILED"}
    blob = json.loads(match.group(1))
    try:
        item = blob["props"]["pageProps"]["initialData"]["data"]["product"]
        avail = item.get("availabilityStatus", "UNKNOWN")
        price = item.get("priceInfo", {}).get("currentPrice", {}).get("price")
        in_stock = avail in ("IN_STOCK", "AVAILABLE")
        return {"in_stock": in_stock, "price": price, "raw_status": avail}
    except (KeyError, TypeError):
        return {"in_stock": False, "price": None, "raw_status": "PARSE_FAILED"}


def check_bestbuy(sku: str):
    """Uses Best Buy's official public Products API. Needs a free API key from
    developer.bestbuy.com — set it on the /settings page, or BESTBUY_API_KEY
    in .env."""
    api_key = config.get("bestbuy_api_key")
    if not api_key:
        return {"in_stock": False, "price": None, "raw_status": "NO_API_KEY"}
    url = (
        f"https://api.bestbuy.com/v1/products(sku={sku})"
        f"?apiKey={api_key}&format=json&show=sku,name,salePrice,onlineAvailability"
    )
    r = requests.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    products = data.get("products", [])
    if not products:
        return {"in_stock": False, "price": None, "raw_status": "NOT_FOUND"}
    p = products[0]
    in_stock = bool(p.get("onlineAvailability"))
    return {"in_stock": in_stock, "price": p.get("salePrice"), "raw_status": str(in_stock)}


def check_bn(product_url: str):
    """Barnes & Noble has no public API; scrape for stock text on the page."""
    r = requests.get(product_url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    text = r.text
    sold_out = bool(re.search(r"(sold out|currently unavailable|out of stock)", text, re.I))
    price_match = re.search(r'"price"\s*:\s*"?([\d.]+)"?', text)
    price = float(price_match.group(1)) if price_match else None
    return {"in_stock": not sold_out, "price": price, "raw_status": "SOLD_OUT" if sold_out else "AVAILABLE"}


def check_pokemon_center(product_url: str):
    """Checks the Pokémon Center product page. During hot drops this site puts
    you behind a Queue-it wait room before you ever see stock state — this
    function reports that state too, so an alert can fire as soon as the queue
    opens rather than only once items are confirmed in stock."""
    r = requests.get(product_url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
    r.raise_for_status()
    text = r.text
    if "queue-it" in r.url or "queue.pokemoncenter.com" in r.url:
        return {"in_stock": False, "price": None, "raw_status": "QUEUE_LIVE"}
    sold_out = bool(re.search(r"(sold out|out of stock)", text, re.I))
    add_to_cart = bool(re.search(r"add to cart", text, re.I))
    price_match = re.search(r'"price"\s*:\s*"?([\d.]+)"?', text)
    price = float(price_match.group(1)) if price_match else None
    in_stock = add_to_cart and not sold_out
    return {"in_stock": in_stock, "price": price, "raw_status": "SOLD_OUT" if sold_out else "AVAILABLE"}


def check_lgs_shopify(shop_and_handle: str):
    """Generic poller for any Shopify storefront. `shop_and_handle` is
    "shopdomain.com/products/product-handle". Shopify exposes a public
    /products.json endpoint per-handle that's clean, fast, and not
    bot-defended the way big-box retailers are."""
    domain, _, handle = shop_and_handle.partition("/products/")
    domain = domain.rstrip("/")
    if not domain.startswith("http"):
        domain = "https://" + domain
    url = f"{domain}/products/{handle}.json"
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    product = data.get("product", {})
    variants = product.get("variants", [])
    if not variants:
        return {"in_stock": False, "price": None, "raw_status": "NOT_FOUND"}
    in_stock = any(v.get("available") for v in variants)
    price = float(variants[0]["price"]) if variants[0].get("price") else None
    return {"in_stock": in_stock, "price": price, "raw_status": "AVAILABLE" if in_stock else "SOLD_OUT"}


def check_lgs_generic(product_url: str):
    """Universal fallback for LGS sites on WooCommerce, BigCommerce, Square,
    or any custom platform without a clean structured endpoint. Lower
    reliability than the Shopify poller — pure text heuristics — but works
    for basically any storefront that renders stock state as visible text."""
    r = requests.get(product_url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    text = r.text
    sold_out = bool(re.search(r"(sold out|out of stock|currently unavailable|notify me when available)",
                               text, re.I))
    has_add_to_cart = bool(re.search(r"add[\s\-]?to[\s\-]?cart", text, re.I))
    price_match = re.search(r'(?:"price"\s*:\s*"?|\$)\s*([\d]+\.\d{2})', text)
    price = float(price_match.group(1)) if price_match else None
    in_stock = has_add_to_cart and not sold_out
    return {"in_stock": in_stock, "price": price, "raw_status": "SOLD_OUT" if sold_out else "AVAILABLE"}


def verify_shopify_store(domain: str):
    """Store-verifier used by the dashboard's 'check my LGS' tool. Confirms
    a domain is Shopify-backed (has a public /products.json) before a user
    wastes time trying to configure it as an lgs_shopify entry."""
    domain = domain.strip().rstrip("/")
    if not domain.startswith("http"):
        domain = "https://" + domain
    try:
        r = requests.get(f"{domain}/products.json?limit=1", headers=HEADERS, timeout=TIMEOUT)
        if r.status_code == 200 and "products" in r.json():
            return {"is_shopify": True, "sample_product_count": len(r.json()["products"])}
    except (requests.RequestException, ValueError):
        pass
    return {"is_shopify": False}


POLLERS = {
    "target": check_target,
    "walmart": check_walmart,
    "bestbuy": check_bestbuy,
    "bn": check_bn,
    "pokemon_center": check_pokemon_center,
    "lgs_shopify": check_lgs_shopify,
    "lgs_generic": check_lgs_generic,
}
