"""
Notification channels. Credentials come from config.py, which checks the
settings page/wizard's DB values first, then .env. Editing a webhook or
key in the web UI takes effect on the very next poll cycle, no restart.

Cost model, unchanged from before:
- Discord: free. ntfy: free, no signup. Pushover: one-time ~$5/platform,
  paid to Pushover by the end user. SMS: end user's own Twilio account.
Card Alert never centralizes or bills for any of these.
"""
import httpx
import config
import display


async def send_discord(message: str) -> dict:
    """Returns {"ok": bool, "status": int|None, "detail": str|None}. The
    detail field carries Discord's actual error response when a send
    fails, since "it didn't work" with no further information is nearly
    impossible to debug for something like a webhook that looks right but
    has a typo, was regenerated, or points at a deleted channel.

    Applies the configured @mention prefix here, not in each caller, so
    every Discord message (restock alerts, queue-open alerts, restock
    chatter) gets it consistently without every call site needing to
    remember to add it."""
    url = (await config.get("discord_webhook_url")).strip()
    if not url:
        return {"ok": False, "status": None, "detail": "No Discord webhook URL saved."}
    full_message = await discord_mention_prefix() + message
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.post(
                url,
                json={
                    "content": full_message,
                    # Without this, Discord can render "<@id>"/"<@&id>" as
                    # literal unlinked text instead of an actual ping —
                    # explicitly allowing both mention types is what makes
                    # the mention actually notify the user or role.
                    "allowed_mentions": {"parse": ["users", "roles"]},
                },
            )
        if r.status_code < 300:
            return {"ok": True, "status": r.status_code, "detail": None}
        return {"ok": False, "status": r.status_code, "detail": r.text[:300]}
    except httpx.HTTPError as e:
        return {"ok": False, "status": None, "detail": f"{type(e).__name__}: could not reach Discord."}


def _parse_mention_ids(raw: str) -> list:
    """Splits a comma-separated field into individual numeric Discord IDs,
    silently dropping anything non-numeric (e.g. stray whitespace, a
    trailing comma, or a username typed by mistake instead of the actual
    ID) rather than building a broken mention tag for it."""
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip().isdigit()]


async def discord_mention_prefix() -> str:
    """Builds a "<@id> <@id2> <@&roleId>" prefix from the Settings page's
    comma-separated user/role ID fields, or an empty string if none are
    set. Discord IDs are always purely numeric (a "snowflake") — any
    non-numeric entry (e.g. a username typed by mistake instead of the
    numeric ID from "Copy ID") is dropped rather than sent as a broken
    tag that could never resolve to a real mention anyway."""
    user_ids = _parse_mention_ids(await config.get("discord_mention_users"))
    role_ids = _parse_mention_ids(await config.get("discord_mention_roles"))
    tags = [f"<@{uid}>" for uid in user_ids] + [f"<@&{rid}>" for rid in role_ids]
    if not tags:
        return ""
    return " ".join(tags) + " "


async def send_ntfy(message: str, title: str = "Card Alert"):
    topic = (await config.get("ntfy_topic")).strip()
    if not topic:
        return
    server = ((await config.get("ntfy_server")) or "https://ntfy.sh").strip()
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            await client.post(
                f"{server}/{topic}",
                content=message.encode("utf-8"),
                headers={"Title": title, "Priority": "high"},
            )
    except httpx.HTTPError as e:
        print("[notifier] ntfy send failed:", type(e).__name__)


async def send_pushover(message: str, title: str = "Card Alert"):
    user_key = (await config.get("pushover_user_key")).strip()
    app_token = (await config.get("pushover_app_token")).strip()
    if not all([user_key, app_token]):
        return
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            await client.post(
                "https://api.pushover.net/1/messages.json",
                data={"token": app_token, "user": user_key, "title": title,
                      "message": message, "priority": 1},
            )
    except httpx.HTTPError as e:
        print("[notifier] Pushover send failed:", type(e).__name__)


async def send_sms(message: str):
    sid = (await config.get("twilio_account_sid")).strip()
    token = (await config.get("twilio_auth_token")).strip()
    from_number = (await config.get("twilio_from_number")).strip()
    to_number = (await config.get("twilio_to_number")).strip()
    if not all([sid, token, from_number, to_number]):
        return
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            await client.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
                auth=(sid, token),
                data={"From": from_number, "To": to_number, "Body": message[:1500]},
            )
    except httpx.HTTPError as e:
        print("[notifier] SMS send failed:", type(e).__name__)


async def dispatch(message: str, channel: str = "discord"):
    """channel: dashboard | discord | ntfy | pushover | sms. Discord
    messages get the configured @mention prefix automatically inside
    send_discord; other channels don't support Discord-style mentions so
    they're left plain."""
    if channel == "discord":
        await send_discord(message)
    elif channel == "ntfy":
        await send_ntfy(message)
    elif channel == "pushover":
        await send_pushover(message)
    elif channel == "sms":
        await send_sms(message)
    # "dashboard" -> nothing to do, alerts_sent is read from the DB on page load


def _strip_tracking(url: str) -> str:
    """Strips query string and fragment from a URL, keeping only
    scheme+host+path. Every retailer this app watches works fine with a
    bare product URL, and query strings are almost always tracking
    parameters (Amazon's ?ref=, ?tag=, ?th=, Target's affiliate params,
    etc.) that reveal nothing useful about the product and shouldn't be
    forwarded in an alert."""
    if not url:
        return url
    from urllib.parse import urlsplit, urlunsplit
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def resolve_product_url(item: dict) -> str:
    """Every alert should carry a real link to the product, but the
    "Product URL" field on the add-item form is easy to leave blank for
    retailer types where the Identifier field already IS a URL (walmart,
    bn, pokemon_center, lgs_generic), which meant alerts for those items
    could go out with no link at all. This resolves a usable URL either
    way: the explicit product_url if one was given, otherwise the best
    link this app can construct from the retailer + identifier alone.
    Every return path goes through _strip_tracking, since a pasted URL
    (in either the product_url field or the identifier field) commonly
    carries tracking query parameters that reveal nothing about the
    product and shouldn't be forwarded in an alert."""
    explicit = (item.get("product_url") or "").strip()
    if explicit:
        return _strip_tracking(explicit)

    retailer = item.get("retailer", "")
    identifier = (item.get("identifier") or "").strip()
    if not identifier:
        return ""

    if retailer == "target":
        return _strip_tracking(f"https://www.target.com/p/-/A-{identifier}")
    if retailer == "amazon":
        if identifier.startswith("http"):
            return _strip_tracking(identifier)
        return _strip_tracking(f"https://www.amazon.com/dp/{identifier}")
    if retailer == "bestbuy":
        # Not stripped: this is a search-results URL, and ?st=... is the
        # actual search query, not a tracking parameter — stripping it
        # would leave a useless bare search page with nothing to search.
        return f"https://www.bestbuy.com/site/searchpage.jsp?st={identifier}"
    if retailer == "lgs_shopify":
        domain = identifier.split("/products/")[0].rstrip("/")
        if not domain.startswith("http"):
            domain = "https://" + domain
        url = f"{domain}/products/{identifier.split('/products/')[-1]}" if "/products/" in identifier else domain
        return _strip_tracking(url)
    # walmart, bn, pokemon_center, lgs_generic: the identifier IS the URL
    if identifier.startswith("http"):
        return _strip_tracking(identifier)
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
