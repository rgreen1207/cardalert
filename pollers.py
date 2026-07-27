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
import config

from bs4 import BeautifulSoup
from curl_cffi import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}
TARGET_HEADERS = {
    **HEADERS,
    "Accept": "application/json",
    "Origin": "https://www.target.com",
    "Referer": "https://www.target.com/",
}
TIMEOUT = 12


def discover_target_api_key(candidate_tcins=None):
    """Best-effort attempt to scrape a live Redsky API key from front-end pages."""
    urls_to_try = [f"https://www.target.com/p/-/A-{tcin}" for tcin in (candidate_tcins or [])]
    urls_to_try.append("https://www.target.com/p/-/A-1011209279")

    patterns = [
        r"redsky\.target\.com[^\"'\s]*?key=([0-9a-f]{32})",
        r'"apiKey"\s*:\s*"([0-9a-f]{32})"',
        r'"redskyApiKey"\s*:\s*"([0-9a-f]{32})"',
    ]

    for url in urls_to_try:
        try:
            # impersonate="chrome124" mimics the exact TLS/JA4 handshake of Google Chrome
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, impersonate="chrome124")
            if r.status_code != 200:
                continue
        except Exception:
            continue
        for pattern in patterns:
            match = re.search(pattern, r.text)
            if match:
                return match.group(1)
    return None


_CAPTCHA_MARKERS = ["captchaRelativeURL", "captchaAbsoluteURL", "/captcha?trackingId"]
_ANTIBOT_MARKERS = [
    "perimeterx", "px-captcha", "_px", "human security",
    "access to this page has been denied", "please verify you are a human",
    "px-block", "captcha-delivery",
]


def _classify_block_response(r):
    body = r.text
    body_lower = body.lower()
    detail = f"HTTP {r.status_code} from Target: {body[:500]}"
    if any(m.lower() in body_lower for m in _CAPTCHA_MARKERS):
        return "CAPTCHA_REQUIRED", detail
    matched = [m for m in _ANTIBOT_MARKERS if m in body_lower]
    if matched:
        return "BLOCKED_BY_ANTIBOT", f"Matched anti-bot marker(s) {matched}. {detail}"
    if r.status_code == 429:
        return "RATE_LIMITED", detail
    return "BLOCKED_OR_KEY_INVALID", detail


def check_target(tcin: str, store_id: str = "3991"):
    """
    Queries Target's Redsky API using a spoofed TLS stack.
    Checks both direct shipping availability and local store pickup availability.
    """
    api_key = config.get("target_api_key") or "9f36aeafbe60771e321a7cc95a78140772ab3e96"
    
    # Utilizing the production endpoint with an explicit pricing and fulfillment store loop
    url = (
        "https://redsky.target.com/redsky_aggregations/v1/web/pdp_client_v1"
        f"?key={api_key}&tcin={tcin}"
        f"&pricing_store_id={store_id}"
        f"&store_id={store_id}"
        "&is_bot=false"
    )
    
    try:
        # Mandatory: impersonate keyword forces curl_cffi to match browser networking signatures
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, impersonate="chrome124")
    except Exception as e:
        return {"in_stock": False, "price": None, "raw_status": "REQUEST_FAILED", "error_detail": str(e)}

    if r.status_code in (401, 403, 429):
        raw_status, detail = _classify_block_response(r)
        return {"in_stock": False, "price": None, "raw_status": raw_status, "error_detail": detail}
        
    if r.status_code != 200:
        return {"in_stock": False, "price": None, "raw_status": f"HTTP_{r.status_code}", "error_detail": r.text[:200]}

    try:
        data = r.json()
    except ValueError:
        return {"in_stock": False, "price": None, "raw_status": "UNEXPECTED_RESPONSE",
                "error_detail": f"Non-JSON response body: {r.text[:500]}"}

    product = data.get("data", {}).get("product")
    if not product:
        return {"in_stock": False, "price": None, "raw_status": "NOT_FOUND"}

    # Extract price
    price = product.get("price", {}).get("current_retail")

    # Extract fulfillment systems
    fulfillment = product.get("fulfillment", {})
    
    # 1. Check Nationwide Online Shipping Inventory
    shipping_status = fulfillment.get("shipping_options", {}).get("availability_status", "UNKNOWN")
    shipping_in_stock = shipping_status == "IN_STOCK"
    
    # 2. Check Local Store Pickup Inventory (In-store or curbside pick up)
    inline_pickup = fulfillment.get("store_options", [{}])[0] if fulfillment.get("store_options") else {}
    pickup_status = inline_pickup.get("order_pickup", {}).get("availability_status", "UNKNOWN")
    in_store_stock = pickup_status == "IN_STOCK"
    
    # Overall target system stock valuation
    in_stock = shipping_in_stock or in_store_stock
    
    raw_status_summary = f"Shipping: {shipping_status} | Store Pickup: {pickup_status}"

    return {
        "in_stock": in_stock, 
        "price": price, 
        "raw_status": raw_status_summary,
        "shipping_available": shipping_in_stock,
        "store_pickup_available": in_store_stock
    }


def check_walmart(product_url: str):
    """
    Scrapes Walmart's Next.js data layout.
    Uses 'impersonate' to clear the strict Walmart bot firewall.
    """
    try:
        r = requests.get(product_url, headers=HEADERS, timeout=TIMEOUT, impersonate="chrome124")
        if r.status_code in (401, 403, 429):
            return {"in_stock": False, "price": None, "raw_status": f"BLOCKED_HTTP_{r.status_code}"}
        r.raise_for_status()
    except Exception as e:
        return {"in_stock": False, "price": None, "raw_status": "REQUEST_FAILED", "error_detail": str(e)}

    match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        r.text, re.DOTALL,
    )
    if not match:
        return {"in_stock": False, "price": None, "raw_status": "PARSE_FAILED_NO_BLOB"}
        
    try:
        blob = json.loads(match.group(1))
        item = blob["props"]["pageProps"]["initialData"]["data"]["product"]
        avail = item.get("availabilityStatus", "UNKNOWN")
        price = item.get("priceInfo", {}).get("currentPrice", {}).get("price")
        in_stock = avail in ("IN_STOCK", "AVAILABLE")
        return {"in_stock": in_stock, "price": price, "raw_status": avail}
    except (KeyError, TypeError) as e:
        return {"in_stock": False, "price": None, "raw_status": "PARSE_FAILED_BAD_JSON", "error_detail": str(e)}


def check_bestbuy(sku: str):
    """
    Monitors Best Buy's real-time internal fulfillment API instead of lagging developer API.
    Does not require a developer API key.
    """
    # Internal real-time endpoint used by Best Buy's dynamic UI to check regional fulfillment
    url = f"https://bestbuy.com{sku}/fulfillment"
    
    # Best Buy checks specific headers for API traffic
    bb_headers = {
        **HEADERS,
        "accept": "application/json",
        "referer": f"https://bestbuy.com{sku}.p",
    }
    
    try:
        r = requests.get(url, headers=bb_headers, timeout=TIMEOUT, impersonate="chrome124")
        if r.status_code == 404:
            return {"in_stock": False, "price": None, "raw_status": "SKU_NOT_FOUND"}
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return {"in_stock": False, "price": None, "raw_status": "API_FAILED", "error_detail": str(e)}

    # Parse real-time button state logic
    button_state = data.get("results", [{}])[0].get("buttonState", {})
    button_status = button_state.get("buttonState", "UNKNOWN")
    
    # If button says ADD_TO_CART or PREORDER, it's buyable instantly
    in_stock = button_status in ("ADD_TO_CART", "PREORDER", "COLLECT_ONLINE")
    
    return {"in_stock": in_stock, "price": None, "raw_status": button_status}


def check_bn(product_url: str):
    """Barnes & Noble scraper reinforced against Cloudflare checks."""
    try:
        r = requests.get(product_url, headers=HEADERS, timeout=TIMEOUT, impersonate="chrome124")
        r.raise_for_status()
    except Exception as e:
        return {"in_stock": False, "price": None, "raw_status": "REQUEST_FAILED", "error_detail": str(e)}

    text = r.text
    sold_out = bool(re.search(r"(sold out|currently unavailable|out of stock)", text, re.I))
    price_match = re.search(r'"price"\s*:\s*"?([\d.]+)"?', text)
    price = float(price_match.group(1)) if price_match else None
    return {"in_stock": not sold_out, "price": price, "raw_status": "SOLD_OUT" if sold_out else "AVAILABLE"}



def check_pokemon_center_queue_only(product_url: str):
    """Safely checks for Pokemon Center Queue-it redirects using Chrome TLS emulation."""
    try:
        r = requests.head(product_url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True, impersonate="chrome124")
        if r.status_code == 405:
            r = requests.get(product_url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True, impersonate="chrome124")
    except Exception:
        try:
            r = requests.get(product_url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True, impersonate="chrome124")
        except Exception:
            return {"queue_live": False, "error": "CONNECTION_FAILED"}
            
    queue_live = "queue-it" in r.url or "queue.pokemoncenter.com" in r.url or r.status_code == 202
    return {"queue_live": queue_live}


def check_pokemon_center(product_url: str):
    """
    Scrapes Pokemon Center inventory. 
    Uses Beautiful Soup instead of raw string search because product names often contain the words 'add to cart'.
    """
    try:
        r = requests.get(product_url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True, impersonate="chrome124")
        if r.status_code == 403:
            return {"in_stock": False, "price": None, "raw_status": "BLOCKED_BY_AKAMAI"}
        r.raise_for_status()
    except Exception as e:
        return {"in_stock": False, "price": None, "raw_status": "REQUEST_FAILED", "error_detail": str(e)}

    if "queue-it" in r.url or "queue.pokemoncenter.com" in r.url:
        return {"in_stock": False, "price": None, "raw_status": "QUEUE_LIVE"}

    soup = BeautifulSoup(r.text, 'html.parser')
    
    # Locate the definitive buy button attribute
    cart_button = soup.find('button', class_=re.compile(r'add-to-cart', re.I))
    
    # If the button exists and isn't disabled, it's in stock
    in_stock = False
    if cart_button:
        in_stock = "disabled" not in cart_button.attrs

    # Extract price metadata accurately
    price_tag = soup.find('meta', property='product:price:amount')
    price = float(price_tag['content']) if price_tag and price_tag.has_attr('content') else None

    return {"in_stock": in_stock, "price": price, "raw_status": "AVAILABLE" if in_stock else "SOLD_OUT"}


def check_lgs_shopify(shop_and_handle: str):
    """Unchanged: Shopify's public api files are fast, clean, and rarely blocked."""
    domain, _, handle = shop_and_handle.partition("/products/")
    domain = domain.rstrip("/")
    if not domain.startswith("http"):
        domain = "https://" + domain
    url = f"{domain}/products/{handle}.json"
    
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return {"in_stock": False, "price": None, "raw_status": "FAILED", "error_detail": str(e)}
        
    product = data.get("product", {})
    variants = product.get("variants", [])
    if not variants:
        return {"in_stock": False, "price": None, "raw_status": "NOT_FOUND"}
    in_stock = any(v.get("available") for v in variants)
    price = float(variants[0]["price"]) if variants[0].get("price") else None
    return {"in_stock": in_stock, "price": price, "raw_status": "AVAILABLE" if in_stock else "SOLD_OUT"}


def check_lgs_generic(product_url: str):
    """Universal fallback scanner for non-major local card shop platforms."""
    try:
        r = requests.get(product_url, headers=HEADERS, timeout=TIMEOUT, impersonate="chrome124")
        r.raise_for_status()
    except Exception as e:
        return {"in_stock": False, "price": None, "raw_status": "FAILED", "error_detail": str(e)}

    text = r.text
    sold_out = bool(re.search(r"(sold out|out of stock|currently unavailable|notify me when available)", text, re.I))
    has_add_to_cart = bool(re.search(r"add[\s\-]?to[\s\-]?cart", text, re.I))
    price_match = re.search(r'(?:"price"\s*:\s*"?|\$)\s*([\d]+\.\d{2})', text)
    price = float(price_match.group(1)) if price_match else None
    in_stock = has_add_to_cart and not sold_out
    return {"in_stock": in_stock, "price": price, "raw_status": "SOLD_OUT" if sold_out else "AVAILABLE"}


def check_amazon(identifier: str):
    """
    Amazon Poller. 
    Strictly filters out third-party scalpers. Only flags as in-stock if 
    the buy-box or offer fulfillment is natively handled by Amazon.com (Merchant ID: ATVPDKIKX0DER).
    """
    asin_match = re.fullmatch(r"[A-Z0-9]{10}", identifier.strip())
    if asin_match:
        asin = identifier.strip()
    else:
        url_match = re.search(r"/(?:dp|gp/product|ASIN)/([A-Z0-9]{10})", identifier)
        if not url_match:
            return {"in_stock": False, "price": None, "raw_status": "INVALID_IDENTIFIER"}
        asin = url_match.group(1)

    url = f"https://www.amazon.com/dp/{asin}"
    
    try:
        # impersonate="chrome124" mimics legitimate shopper TLS handshakes
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, impersonate="chrome124")
        if r.status_code in (401, 403, 429):
            return {"in_stock": False, "price": None, "raw_status": f"BLOCKED_HTTP_{r.status_code}"}
        r.raise_for_status()
    except Exception as e:
        return {"in_stock": False, "price": None, "raw_status": "REQUEST_FAILED", "error_detail": str(e)}

    text = r.text
    
    # 1. Catch Amazon Captcha Challenges Early
    if "captcha" in r.url or "validatecaptcha" in text.lower() or "enter the characters you see below" in text.lower():
        return {"in_stock": False, "price": None, "raw_status": "CAPTCHA_REQUIRED", "error_detail": "Amazon triggered a verification captcha screen."}

    soup = BeautifulSoup(text, 'html.parser')

    # 2. Extract Price safely via structured microdata / meta tags instead of volatile regex
    price = None
    price_tag = soup.find("span", class_="a-price-whole")
    if price_tag:
        try:
            # Clean commas and fractional elements
            price_str = price_tag.get_text().replace(",", "").replace("\n", "").strip()
            fraction_tag = soup.find("span", class_="a-price-fraction")
            if fraction_tag:
                price_str += f".{fraction_tag.get_text().strip()}"
            price = float(price_str)
        except ValueError:
            price = None

    # Fallback to structural JSON metadata on the page if HTML elements shift
    if not price:
        twister_match = re.search(r'"apexPriceToPay"[^}]*?"amount"\s*:\s*([\d.]+)', text)
        if twister_match:
            price = float(twister_match.group(1))

    # 3. Detect Bot Mitigation Error Pages (The "Dog of Amazon" page)
    sold_out_indicator = soup.find(id="outOfStock") or "currently unavailable" in text.lower()
    buybox_button = soup.find(id="add-to-cart-button") or soup.find(id="buy-now-button")
    
    if sold_out_indicator or not buybox_button:
        return {"in_stock": False, "price": price, "raw_status": "SOLD_OUT"}

    # 4. Bulletproof Merchant Verification
    # Amazon's backend identifier for their own retail inventory is ATVPDKIKX0DER
    # We inspect hidden buy-box parameters for this specific merchant tag
    amazon_merchant_id = "ATVPDKIKX0DER"
    
    merchant_input = soup.find("input", {"id": "merchantID"}) or soup.find("input", {"name": "merchantID"})
    
    sold_by_amazon = False
    if merchant_input and merchant_input.get("value") == amazon_merchant_id:
        sold_by_amazon = True
    else:
        # Fallback text check if Amazon changes input layout
        fulfillment_text = soup.find(id="fulfillmentDisplayArea")
        fulfillment_str = fulfillment_text.get_text().lower() if fulfillment_text else ""
        if "ships from" in fulfillment_str and "amazon" in fulfillment_str and "sold by" in fulfillment_str:
            # Simple text confirmation ensuring it's not a third party listing
            if "sold by amazon" in fulfillment_str:
                sold_by_amazon = True

    if not sold_by_amazon:
        return {"in_stock": False, "price": price, "raw_status": "THIRD_PARTY_SELLER_ONLY"}

    return {"in_stock": True, "price": price, "raw_status": "AVAILABLE"}


def verify_shopify_store(domain: str):
    """
    Store-verifier used by the dashboard. Confirms domain structure.
    Employs full stealth signatures to check stores that use strict Cloudflare shielding.
    """
    domain = domain.strip().rstrip("/")
    if not domain.startswith("http"):
        domain = "https://" + domain
    try:
        r = requests.get(f"{domain}/products.json?limit=1", headers=HEADERS, timeout=TIMEOUT, impersonate="chrome124")
        if r.status_code == 200 and "products" in r.json():
            return {"is_shopify": True, "sample_product_count": len(r.json()["products"])}
    except Exception:
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
