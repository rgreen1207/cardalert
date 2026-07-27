"""
Notification channels.

Cost model, spelled out because it matters for this project's promise of
"zero cost to launch or support":
- Discord webhook: free, no account needed beyond one you already have.
- ntfy: free, no signup required at all (ntfy.sh is public + open-source,
  self-hostable too). This is the recommended default push channel.
- SMS: uses the END USER's own Twilio account (their SID/token/number in
  their own .env). Twilio charges THEM fractions of a cent per text plus
  ~$1/mo for a number — nobody centralizes this, nobody but the end user
  ever sees a bill for it.
"""
import os
import requests

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")          # e.g. "cardalert-yourname-x92" (pick something unguessable)
NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh")

TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER", "")
TWILIO_TO_NUMBER = os.environ.get("TWILIO_TO_NUMBER", "")

PUSHOVER_USER_KEY = os.environ.get("PUSHOVER_USER_KEY", "")
PUSHOVER_APP_TOKEN = os.environ.get("PUSHOVER_APP_TOKEN", "")


def send_discord(message: str):
    if not DISCORD_WEBHOOK_URL:
        return
    try:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": message}, timeout=8)
    except requests.RequestException as e:
        print("[notifier] Discord send failed:", e)


def send_ntfy(message: str, title: str = "Card Alert"):
    if not NTFY_TOPIC:
        return
    try:
        requests.post(
            f"{NTFY_SERVER}/{NTFY_TOPIC}",
            data=message.encode("utf-8"),
            headers={"Title": title, "Priority": "high"},
            timeout=8,
        )
    except requests.RequestException as e:
        print("[notifier] ntfy send failed:", e)


def send_sms(message: str):
    if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER, TWILIO_TO_NUMBER]):
        return
    try:
        requests.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Messages.json",
            auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
            data={"From": TWILIO_FROM_NUMBER, "To": TWILIO_TO_NUMBER, "Body": message[:1500]},
            timeout=8,
        )
    except requests.RequestException as e:
        print("[notifier] SMS send failed:", e)


def send_pushover(message: str, title: str = "Card Alert"):
    if not all([PUSHOVER_USER_KEY, PUSHOVER_APP_TOKEN]):
        return
    try:
        requests.post(
            "https://api.pushover.net/1/messages.json",
            data={
                "token": PUSHOVER_APP_TOKEN,
                "user": PUSHOVER_USER_KEY,
                "title": title,
                "message": message,
                "priority": 1,  # high priority, bypasses quiet hours only if user set that up
            },
            timeout=8,
        )
    except requests.RequestException as e:
        print("[notifier] Pushover send failed:", e)


def dispatch(message: str, channel: str = "discord"):
    """channel: dashboard | discord | ntfy | pushover | sms. 'dashboard' is a
    no-op here — the dashboard already shows alerts_sent on every page load."""
    if channel == "discord":
        send_discord(message)
    elif channel == "ntfy":
        send_ntfy(message)
    elif channel == "pushover":
        send_pushover(message)
    elif channel == "sms":
        send_sms(message)
    # "dashboard" -> nothing to do, it's read from the DB on page load


def restock_message(item: dict, price, url):
    price_str = f"${price:.2f}" if price else "unknown"
    return f"🟢 {item['name']} is IN STOCK at {item['retailer']}\nPrice: {price_str}\n{url}"


def queue_open_message(item: dict, url):
    return f"🟡 {item['name']} queue just went LIVE at {item['retailer']}\n{url}"


def drop_signal_message(signal: dict):
    kind = signal.get("kind", "chatter")
    label = "Restock forecast" if kind == "forecast" else "Possible restock chatter"
    return f"👀 {label}: {signal['title']}\n{signal['url']}"
