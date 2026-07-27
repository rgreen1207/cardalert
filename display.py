"""
Internal keys like "bn" or "pokemon_center" are convenient as form values
and database columns, but nobody wants to read "bn" on a dashboard. This
module is the single place that maps those keys to the names people
actually recognize, so every template and message stays consistent
without each one inventing its own capitalization.
"""

RETAILER_NAMES = {
    "target": "Target",
    "walmart": "Walmart",
    "bestbuy": "Best Buy",
    "bn": "Barnes & Noble",
    "pokemon_center": "Pokémon Center",
    "amazon": "Amazon",
    "lgs_shopify": "Local Game Store",
    "lgs_generic": "Local Game Store",
}

GAME_NAMES = {
    "pokemon": "Pokémon",
    "mtg": "Magic: The Gathering",
    "yugioh": "Yu-Gi-Oh!",
    "onepiece": "One Piece",
    "other": "Other",
}

CHANNEL_NAMES = {
    "discord": "Discord",
    "ntfy": "ntfy",
    "pushover": "Pushover",
    "sms": "SMS",
    "dashboard": "Dashboard",
}


def channel_name(key: str) -> str:
    return CHANNEL_NAMES.get(key, key.capitalize())


STATUS_LABELS = {
    "IN_STOCK": "In stock",
    "AVAILABLE": "In stock",
    "SOLD_OUT": "Sold out",
    "QUEUE_LIVE": "Queue live",
    "THIRD_PARTY_SELLER_ONLY": "Third-party seller only",
    "NO_API_KEY": "No API key set",
    "INVALID_IDENTIFIER": "Invalid identifier",
    "NOT_FOUND": "Not found",
    "PARSE_FAILED": "Couldn't read page",
    "UNKNOWN": "Unknown",
    "BLOCKED_OR_KEY_INVALID": "Blocked by retailer",
    "RATE_LIMITED": "Rate limited, will retry",
    "UNEXPECTED_RESPONSE": "Unexpected response",
}


def status_label(raw: str) -> str:
    if not raw:
        return "—"
    if raw in STATUS_LABELS:
        return STATUS_LABELS[raw]
    if raw.startswith("ERROR:"):
        return "Error checking stock"
    return raw.replace("_", " ").title()


def retailer_name(key: str) -> str:
    return RETAILER_NAMES.get(key, key.replace("_", " ").title())


def game_name(key: str) -> str:
    return GAME_NAMES.get(key, key.replace("_", " ").title())
