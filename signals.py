"""
Drop-signal aggregator.

There's no reliable way to *predict* a restock. Retailers don't publish
timing. The "weekly forecast" posts people find on Reddit are compiled from
public info: historical day/time clustering (Target skews Tue/Fri mornings,
etc.), official set street-dates announced by the game publishers, retailer
ad-cycle previews, and crowdsourced sightings extrapolated forward. None of
that requires anything we shouldn't touch. This module does the same thing,
generically, for free, using Reddit's public search JSON (no login, no API
key needed for read-only search).

Two signal types:
1. Real-time chatter: "just went live" posts, same as before.
2. Forecast posts: recurring "weekly restock forecast" threads that a
   subreddit's community already compiles; we just surface them on the
   dashboard as a heads-up, not treat them as gospel.
"""
import time
import requests

HEADERS = {"User-Agent": "cardalert-dashboard/1.0 (personal restock tracker)"}
TIMEOUT = 10

# Subreddits per game, extend freely. General deal-hunting subs are useful
# across every game, so they're included for all.
GAME_SUBREDDITS = {
    "pokemon": ["PokemonTCG", "PokeInvestments", "pkmntcgtrades", "PokemonDeals"],
    "mtg": ["magicTCG", "mtgfinance", "PokemonDeals"],
    "yugioh": ["yugioh", "PokemonDeals"],
    "onepiece": ["OnePieceTCG", "PokemonDeals"],
    "other": ["PokemonDeals"],
}

RETAILER_NAMES = {
    "target": "Target", "walmart": "Walmart", "bestbuy": "Best Buy",
    "bn": "Barnes Noble", "pokemon_center": "Pokemon Center",
}

CHATTER_KEYWORDS = ["restock", "in stock", "live now", "just dropped", "drop alert"]
FORECAST_KEYWORDS = ["forecast", "weekly restock", "this week", "upcoming restock"]


def search_reddit(subreddit: str, query: str, limit: int = 10, sort="new", t="day"):
    url = f"https://www.reddit.com/r/{subreddit}/search.json"
    params = {"q": query, "restrict_sr": 1, "sort": sort, "limit": limit, "t": t}
    r = requests.get(url, headers=HEADERS, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    posts = r.json().get("data", {}).get("children", [])
    results = []
    for p in posts:
        d = p.get("data", {})
        results.append({
            "title": d.get("title", ""),
            "url": "https://reddit.com" + d.get("permalink", ""),
            "created_utc": d.get("created_utc", 0),
            "selftext": d.get("selftext", "")[:500],
        })
    return results


def poll_chatter(games, cutoff_seconds=900):
    """Real-time 'it's live right now' chatter for the retailers currently
    on the user's watchlist, scoped to the games they're tracking."""
    now = time.time()
    subs = set()
    for g in games:
        subs.update(GAME_SUBREDDITS.get(g, GAME_SUBREDDITS["other"]))

    fresh_hits = []
    for sub in subs:
        for retailer in RETAILER_NAMES.values():
            try:
                posts = search_reddit(sub, retailer, limit=5)
            except requests.RequestException:
                continue
            for post in posts:
                age = now - post["created_utc"]
                if age > cutoff_seconds:
                    continue
                title_lower = post["title"].lower()
                if any(k in title_lower for k in CHATTER_KEYWORDS) or retailer.lower() in title_lower:
                    fresh_hits.append({**post, "source": f"r/{sub}", "retailer_guess": retailer,
                                        "kind": "chatter"})
    return fresh_hits


def poll_forecasts(games, cutoff_seconds=7 * 24 * 3600):
    """Recurring 'weekly restock forecast' threads. These are community
    roundups, not confirmed schedules. Surfaced as-is with a link, no
    parsing of specific claims, since retailers don't guarantee any of it."""
    now = time.time()
    subs = set()
    for g in games:
        subs.update(GAME_SUBREDDITS.get(g, GAME_SUBREDDITS["other"]))

    hits = []
    for sub in subs:
        try:
            posts = search_reddit(sub, "restock forecast", limit=8, sort="new", t="week")
        except requests.RequestException:
            continue
        for post in posts:
            age = now - post["created_utc"]
            if age > cutoff_seconds:
                continue
            title_lower = post["title"].lower()
            if any(k in title_lower for k in FORECAST_KEYWORDS):
                hits.append({**post, "source": f"r/{sub}", "kind": "forecast"})
    return hits


def poll_all_signals(games):
    return poll_chatter(games) + poll_forecasts(games)
