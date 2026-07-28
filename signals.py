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
import asyncio
import time
import httpx

HEADERS = {"User-Agent": "cardalert-dashboard/1.0 (personal restock tracker)"}
TIMEOUT = 10

# Caps how many Reddit searches run at once. This module fans out a search
# per (subreddit, retailer) pair, which can be dozens at once — a cap keeps
# that from turning into a burst of simultaneous requests to reddit.com.
_CONCURRENCY = 5

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
    "bn": "Barnes & Noble", "pokemon_center": "Pokemon Center",
    "amazon": "Amazon", "lgs_shopify": "Local Game Store", "lgs_generic": "Local Game Store",
}

CHATTER_KEYWORDS = ["restock", "in stock", "live now", "just dropped", "drop alert"]
FORECAST_KEYWORDS = ["forecast", "weekly restock", "this week", "upcoming restock"]


async def search_reddit(subreddit: str, query: str, limit: int = 10, sort="new", t="day"):
    url = f"https://www.reddit.com/r/{subreddit}/search.json"
    params = {"q": query, "restrict_sr": 1, "sort": sort, "limit": limit, "t": t}
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.get(url, headers=HEADERS, params=params)
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


async def poll_chatter(games, cutoff_seconds=900):
    """Real-time 'it's live right now' chatter for the retailers currently
    on the user's watchlist, scoped to the games they're tracking."""
    now = time.time()
    subs = set()
    for g in games:
        subs.update(GAME_SUBREDDITS.get(g, GAME_SUBREDDITS["other"]))

    semaphore = asyncio.Semaphore(_CONCURRENCY)

    async def _search_one(sub, retailer):
        async with semaphore:
            try:
                return sub, retailer, await search_reddit(sub, retailer, limit=5)
            except httpx.HTTPError:
                return sub, retailer, []

    tasks = [_search_one(sub, retailer) for sub in subs for retailer in set(RETAILER_NAMES.values())]
    results = await asyncio.gather(*tasks)

    fresh_hits = []
    for sub, retailer, posts in results:
        for post in posts:
            age = now - post["created_utc"]
            if age > cutoff_seconds:
                continue
            title_lower = post["title"].lower()
            if any(k in title_lower for k in CHATTER_KEYWORDS) or retailer.lower() in title_lower:
                fresh_hits.append({**post, "source": f"r/{sub}", "retailer_guess": retailer,
                                    "kind": "chatter"})
    return fresh_hits


async def poll_forecasts(games, cutoff_seconds=7 * 24 * 3600):
    """Recurring 'weekly restock forecast' threads. These are community
    roundups, not confirmed schedules. Surfaced as-is with a link, no
    parsing of specific claims, since retailers don't guarantee any of it."""
    now = time.time()
    subs = set()
    for g in games:
        subs.update(GAME_SUBREDDITS.get(g, GAME_SUBREDDITS["other"]))

    semaphore = asyncio.Semaphore(_CONCURRENCY)

    async def _search_one(sub):
        async with semaphore:
            try:
                return sub, await search_reddit(sub, "restock forecast", limit=8, sort="new", t="week")
            except httpx.HTTPError:
                return sub, []

    results = await asyncio.gather(*(_search_one(sub) for sub in subs))

    hits = []
    for sub, posts in results:
        for post in posts:
            age = now - post["created_utc"]
            if age > cutoff_seconds:
                continue
            title_lower = post["title"].lower()
            if any(k in title_lower for k in FORECAST_KEYWORDS):
                hits.append({**post, "source": f"r/{sub}", "kind": "forecast"})
    return hits


async def poll_all_signals(games):
    chatter, forecasts = await asyncio.gather(poll_chatter(games), poll_forecasts(games))
    return chatter + forecasts
