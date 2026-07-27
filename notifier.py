"""
Notification channels. Credentials come from config.py, which checks the
settings page/wizard's DB values first, then .env. Editing a webhook or
key in the web UI takes effect on the very next poll cycle, no restart.

Cost model, unchanged from before:
- Discord: free. ntfy: free, no signup. Pushover: one-time ~$5/platform,
  paid to Pushover by the end user. SMS: end user's own Twilio account.
Card Alert never centralizes or bills for any of these.
"""
import requests
import config
import display


def send_discord(message: str) -> dict:
    """Returns {"ok": bool, "status": int|None, "detail": str|None}. The
    detail field carries Discord's actual error response when a send
    fails, since "it didn't work" with no further information is nearly
    impossible to debug for something like a webhook that looks right but
    has a typo, was regenerated, or points at a deleted channel.

    Applies the configured @mention prefix here, not in each caller, so
    every Discord message (restock alerts, queue-open alerts, restock
    chatter) gets it consistently without every call site needing to
    remember to add it."""
    url = config.get("discord_webhook_url").strip()
    if not url:
        return {"ok": False, "status": None, "detail": "No Discord webhook URL saved."}
    full_message = discord_mention_prefix() + message
    try:
        r = requests.post(url, json={"content": full_message}, timeout=8)
        if r.status_code < 300:
            return {"ok": True, "status": r.status_code, "detail": None}
        return {"ok": False, "status": r.status_code, "detail": r.text[:300]}
    except requests.RequestException as e:
        return {"ok": False, "status": None, "detail": f"{type(e).__name__}: could not reach Discord."}


def discord_mention_prefix() -> str:
    """Builds the "<@id>" or "<@&id>" prefix from the Settings page's
    mention fields, or an empty string if mentions are off."""
    mention_type = config.get("discord_mention_type")
    mention_id = config.get("discord_mention_id").strip()
    if not mention_id or mention_type not in ("user", "role"):
        return ""
    if mention_type == "role":
        return f"<@&{mention_id}> "
    return f"<@{mention_id}> "


def send_ntfy(message: str, title: str = "Card Alert"):
    topic = config.get("ntfy_topic").strip()
    if not topic:
        return
    server = (config.get("ntfy_server") or "https://ntfy.sh").strip()
    try:
        requests.post(
            f"{server}/{topic}",
            data=message.encode("utf-8"),
            headers={"Title": title, "Priority": "high"},
            timeout=8,
        )
    except requests.RequestException as e:
        print("[notifier] ntfy send failed:", type(e).__name__)


def send_pushover(message: str, title: str = "Card Alert"):
    user_key = config.get("pushover_user_key").strip()
    app_token = config.get("pushover_app_token").strip()
    if not all([user_key, app_token]):
        return
    try:
        requests.post(
            "https://api.pushover.net/1/messages.json",
            data={"token": app_token, "user": user_key, "title": title,
                  "message": message, "priority": 1},
            timeout=8,
        )
    except requests.RequestException as e:
        print("[notifier] Pushover send failed:", type(e).__name__)


def send_sms(message: str):
    sid = config.get("twilio_account_sid").strip()
    token = config.get("twilio_auth_token").strip()
    from_number = config.get("twilio_from_number").strip()
    to_number = config.get("twilio_to_number").strip()
    if not all([sid, token, from_number, to_number]):
        return
    try:
        requests.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
            auth=(sid, token),
            data={"From": from_number, "To": to_number, "Body": message[:1500]},
            timeout=8,
        )
    except requests.RequestException as e:
        print("[notifier] SMS send failed:", type(e).__name__)


def dispatch(message: str, channel: str = "discord"):
    """channel: dashboard | discord | ntfy | pushover | sms. Discord
    messages get the configured @mention prefix automatically inside
    send_discord; other channels don't support Discord-style mentions so
    they're left plain."""
    if channel == "discord":
        send_discord(message)
    elif channel == "ntfy":
        send_ntfy(message)
    elif channel == "pushover":
        send_pushover(message)
    elif channel == "sms":
        send_sms(message)
    # "dashboard" -> nothing to do, alerts_sent is read from the DB on page load


def resolve_product_url(item: dict) -> str:
    """Every alert should carry a real link to the product, but the
    "Product URL" field on the add-item form is easy to leave blank for
    retailer types where the Identifier field already IS a URL (walmart,
    bn, pokemon_center, lgs_generic), which meant alerts for those items
    could go out with no link at all. This resolves a usable URL either
    way: the explicit product_url if one was given, otherwise the best
    link this app can construct from the retailer + identifier alone."""
    explicit = (item.get("product_url") or "").strip()
    if explicit:
        return explicit

    retailer = item.get("retailer", "")
    identifier = (item.get("identifier") or "").strip()
    if not identifier:
        return ""

    if retailer == "target":
        return f"https://www.target.com/p/-/A-{identifier}"
    if retailer == "amazon":
        if identifier.startswith("http"):
            return identifier
        return f"https://www.amazon.com/dp/{identifier}"
    if retailer == "bestbuy":
        return f"https://www.bestbuy.com/site/searchpage.jsp?st={identifier}"
    if retailer == "lgs_shopify":
        domain = identifier.split("/products/")[0].rstrip("/")
        if not domain.startswith("http"):
            domain = "https://" + domain
        return f"{domain}/products/{identifier.split('/products/')[-1]}" if "/products/" in identifier else domain
    # walmart, bn, pokemon_center, lgs_generic: the identifier IS the URL
    if identifier.startswith("http"):
        return identifier
    return ""


def restock_message(item: dict, price, url):
    price_str = f"${price:.2f}" if price else "unknown"
    retailer_name = display.retailer_name(item.get("retailer", ""))
    link = url or resolve_product_url(item)
    return f"🟢 {item['name']} is IN STOCK at {retailer_name}\nPrice: {price_str}\n{link}"


def queue_open_message(item: dict, url):
    retailer_name = display.retailer_name(item.get("retailer", ""))
    link = url or resolve_product_url(item)
    return f"🟡 {item['name']} queue just went LIVE at {retailer_name}\n{link}"


def drop_signal_message(signal: dict):
    kind = signal.get("kind", "chatter")
    label = "Restock forecast" if kind == "forecast" else "Possible restock chatter"
    return f"👀 {label}: {signal['title']}\n{signal['url']}"
