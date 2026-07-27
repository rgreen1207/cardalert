"""
Retailer pollers.

IMPORTANT SCOPE NOTE (read this before extending):
Every function here does exactly one thing: fetch a public page/endpoint and
read back stock + price. None of these functions add to cart, log in, hold a
session, or submit any action on a retailer's site. That line is intentional.
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
    # Distinguish "Target actively rejected this request" from "the
    # response was fine but didn't have the shape we expected" — these
    # are genuinely different situations and were previously both
    # collapsed into the same generic "Error checking stock." A 403/429
    # here usually means the hardcoded redsky API key below has been
    # rotated or rate-limited by Target and needs updating, not that any
    # particular product is broken.
    if r.status_code in (401, 403):
        return {"in_stock": False, "price": None, "raw_status": "BLOCKED_OR_KEY_INVALID",
                "error_detail": f"HTTP {r.status_code} from Target: {r.text[:300]}"}
    if r.status_code == 429:
        return {"in_stock": False, "price": None, "raw_status": "RATE_LIMITED",
                "error_detail": f"HTTP 429 from Target: {r.text[:300]}"}
    r.raise_for_status()
    try:
        data = r.json()
    except ValueError:
        # Target returned a 2xx with a body that isn't valid JSON — e.g. an
        # HTML block/interstitial page instead of the expected API response.
        return {"in_stock": False, "price": None, "raw_status": "UNEXPECTED_RESPONSE",
                "error_detail": f"Non-JSON response body: {r.text[:300]}"}
    # .get() rather than direct indexing: Target's API can legitimately
    # return a response missing "product" (delisted items, some
    # restricted/age-gated items, occasional API quirks) — that's a real,
    # reportable state, not a bug in this poller, so it should surface as
    # "not found" rather than raising and getting logged as a generic
    # "Error checking stock."
    product = data.get("data", {}).get("product")
    if not product:
        return {"in_stock": False, "price": None, "raw_status": "NOT_FOUND"}
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
    developer.bestbuy.com. Set it on the /settings page, or BESTBUY_API_KEY
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
    you behind a Queue-it wait room before you ever see stock state. This
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
    reliability than the Shopify poller (pure text heuristics), but works
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


def check_amazon(identifier: str):
    """Amazon. Only counts as in-stock when the listing is actually
    'Ships from and sold by Amazon.com', not a third-party marketplace
    seller. Third-party listings are where most of the price-gouging on
    hot TCG products happens, so those are deliberately excluded rather
    than alerted on.

    `identifier` can be a bare 10-character ASIN or a full product URL,
    either way we normalize to a canonical /dp/ URL for the actual request.

    Caveat, more than any other poller here: Amazon fights scraping harder
    than any other retailer on this list and changes page structure often.
    Treat this one as the most likely to need re-tuning over time."""
    asin_match = re.fullmatch(r"[A-Z0-9]{10}", identifier.strip())
    if asin_match:
        asin = identifier.strip()
    else:
        url_match = re.search(r"/(?:dp|gp/product|ASIN)/([A-Z0-9]{10})", identifier)
        if not url_match:
            return {"in_stock": False, "price": None, "raw_status": "INVALID_IDENTIFIER"}
        asin = url_match.group(1)

    url = f"https://www.amazon.com/dp/{asin}"
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    text = r.text

    sold_by_amazon = bool(re.search(r"ships from and sold by amazon(\.com)?", text, re.I))
    third_party_seller = bool(re.search(r"sold by(?!\s*amazon)[^<]{1,60}", text, re.I)) and not sold_by_amazon
    sold_out = bool(re.search(r"(currently unavailable|out of stock)", text, re.I))
    has_buybox = bool(re.search(r"add-to-cart-button|addToCart", text, re.I))

    price = None
    price_match = re.search(r'"apexPriceToPay"[^}]*?"amount"\s*:\s*([\d.]+)', text)
    if not price_match:
        price_match = re.search(r'class="a-price-whole">([\d,]+)<', text)
    if price_match:
        try:
            price = float(price_match.group(1).replace(",", ""))
        except ValueError:
            price = None

    if third_party_seller and not sold_by_amazon:
        return {"in_stock": False, "price": price, "raw_status": "THIRD_PARTY_SELLER_ONLY"}
    if sold_out or not has_buybox:
        return {"in_stock": False, "price": price, "raw_status": "SOLD_OUT"}
    in_stock = sold_by_amazon and has_buybox and not sold_out
    return {"in_stock": in_stock, "price": price, "raw_status": "AVAILABLE" if in_stock else "UNKNOWN"}


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
    "amazon": check_amazon,
    "lgs_shopify": check_lgs_shopify,
    "lgs_generic": check_lgs_generic,
}
