"""
Notification channels. Credentials come from config.py, which checks the
settings page/wizard's DB values first, then .env — so editing a webhook or
key in the web UI takes effect on the very next poll cycle, no restart.

Cost model, unchanged from before:
- Discord: free. ntfy: free, no signup. Pushover: one-time ~$5/platform,
  paid to Pushover by the end user. SMS: end user's own Twilio account.
Card Alert never centralizes or bills for any of these.
"""
import requests
import config


def send_discord(message: str):
    url = config.get("discord_webhook_url")
    if not url:
        return
    try:
        requests.post(url, json={"content": message}, timeout=8)
    except requests.RequestException as e:
        print("[notifier] Discord send failed:", e)


def send_ntfy(message: str, title: str = "Card Alert"):
    topic = config.get("ntfy_topic")
    if not topic:
        return
    server = config.get("ntfy_server") or "https://ntfy.sh"
    try:
        requests.post(
            f"{server}/{topic}",
            data=message.encode("utf-8"),
            headers={"Title": title, "Priority": "high"},
            timeout=8,
        )
    except requests.RequestException as e:
        print("[notifier] ntfy send failed:", e)


def send_pushover(message: str, title: str = "Card Alert"):
    user_key = config.get("pushover_user_key")
    app_token = config.get("pushover_app_token")
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
        print("[notifier] Pushover send failed:", e)


def send_sms(message: str):
    sid = config.get("twilio_account_sid")
    token = config.get("twilio_auth_token")
    from_number = config.get("twilio_from_number")
    to_number = config.get("twilio_to_number")
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
        print("[notifier] SMS send failed:", e)


def dispatch(message: str, channel: str = "discord"):
    """channel: dashboard | discord | ntfy | pushover | sms."""
    if channel == "discord":
        send_discord(message)
    elif channel == "ntfy":
        send_ntfy(message)
    elif channel == "pushover":
        send_pushover(message)
    elif channel == "sms":
        send_sms(message)
    # "dashboard" -> nothing to do, alerts_sent is read from the DB on page load


def restock_message(item: dict, price, url):
    price_str = f"${price:.2f}" if price else "unknown"
    return f"🟢 {item['name']} is IN STOCK at {item['retailer']}\nPrice: {price_str}\n{url}"


def queue_open_message(item: dict, url):
    return f"🟡 {item['name']} queue just went LIVE at {item['retailer']}\n{url}"


def drop_signal_message(signal: dict):
    kind = signal.get("kind", "chatter")
    label = "Restock forecast" if kind == "forecast" else "Possible restock chatter"
    return f"👀 {label}: {signal['title']}\n{signal['url']}"
