#!/usr/bin/env python3
"""
PKMN VAULT - Price Updater v3
- Session persistante (cookies reels)
- Warm-up home eBay avant recherche pour simuler une visite humaine
- Headers navigateur complets Chrome 120 (Sec-Fetch-*, sec-ch-ua, Referer)
- Retry exponentiel sur 503
- Fallback ebay.co.uk si .com bloque
- Conversion devise -> EUR automatique
"""

import json
import os
import random
import re
import statistics
import time
from datetime import datetime, timezone
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

# ═══════════════════════════════════════════════════════════════════
CARDS = [
    {"id": "charizard-v-ssv",   "query": "PSA 10 Charizard V 307 Shiny Star V Japanese"},
    {"id": "mentali-v-eh",      "query": "PSA 10 Espeon V 081 Eevee Heroes Japanese"},
    {"id": "dracaufeu-ex-151",  "query": "PSA 10 Charizard ex 201 Pokemon 151 Japanese"},
    {"id": "pikachu-ex-sv8",    "query": "PSA 10 Pikachu ex 132 Super Electric Breaker"},
    {"id": "umbreon-ex-sv8a",   "query": "PSA 10 Umbreon ex 217 Terastal Festival"},
]

PRICE_MIN = 50
PRICE_MAX = 8000
MAX_HISTORY = 11
MAX_RESULTS_PER_CARD = 30

DEFAULT_USD_TO_EUR = 0.92
DEFAULT_GBP_TO_EUR = 1.17

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8,"
        "application/signed-exchange;v=b3;q=0.7"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "max-age=0",
    "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}


def get_rate(currency: str) -> float:
    try:
        r = requests.get(
            f"https://api.exchangerate-api.com/v4/latest/{currency}",
            timeout=10,
        )
        rate = float(r.json()["rates"]["EUR"])
        print(f"Taux {currency}->EUR: {rate:.4f}")
        return rate
    except Exception as e:
        fallback = DEFAULT_USD_TO_EUR if currency == "USD" else DEFAULT_GBP_TO_EUR
        print(f"API taux {currency} indispo ({e}), fallback {fallback}")
        return fallback


def warm_up_session(session, base_url):
    print(f"Warm-up: GET {base_url}/ ...")
    try:
        r = session.get(base_url + "/", headers=BROWSER_HEADERS, timeout=30)
        print(f"  HTTP {r.status_code}, {len(r.content)} bytes, {len(session.cookies)} cookies")
        if r.status_code != 200:
            return False
        time.sleep(random.uniform(1.5, 3.0))
        search_url = base_url + "/sch/i.html?_nkw=pokemon"
        r = session.get(search_url, headers=BROWSER_HEADERS, timeout=30)
        print(f"  warmup search: HTTP {r.status_code}, {len(session.cookies)} cookies")
        return r.status_code == 200
    except requests.RequestException as e:
        print(f"  warmup ERREUR: {e}")
        return False


def parse_price(text):
    if not text:
        return None
    if " to " in text.lower() or " à " in text:
        return None
    cleaned = (
        text.replace("\xa0", " ")
        .replace(",", "")
        .replace("$", "")
        .replace("£", "")
        .replace("EUR", "")
    )
    m = re.search(r"(\d+(?:\.\d+)?)", cleaned)
    if not m:
        return None
    try:
        num = float(m.group(1))
        if PRICE_MIN <= num <= PRICE_MAX:
            return num
    except ValueError:
        pass
    return None


def fetch_sold_prices(session, base_url, query):
    url = (
        f"{base_url}/sch/i.html?"
        f"_from=R40&_nkw={quote(query)}"
        f"&LH_Sold=1&LH_Complete=1&_sop=13&_ipg=60"
    )
    print(f"  GET {url[:140]}...")

    headers = dict(BROWSER_HEADERS)
    headers["Referer"] = base_url + "/"
    headers["Sec-Fetch-Site"] = "same-origin"

    r = None
    for attempt in range(1, 4):
        try:
            r = session.get(url, headers=headers, timeout=30)
            if r.status_code == 200:
                break
            if r.status_code in (429, 503):
                wait = 2 ** attempt + random.uniform(0, 1)
                print(f"  HTTP {r.status_code}, retry dans {wait:.1f}s (tentative {attempt}/3)")
                time.sleep(wait)
                continue
            print(f"  HTTP {r.status_code} inattendu, abandon")
            return []
        except requests.RequestException as e:
            wait = 2 ** attempt
            print(f"  ERREUR {e}, retry dans {wait}s (tentative {attempt}/3)")
            time.sleep(wait)

    if r is None or r.status_code != 200:
        print(f"  Echec apres 3 tentatives")
        return []

    print(f"  HTTP {r.status_code}, {len(r.content)} bytes")

    soup = BeautifulSoup(r.text, "html.parser")
    items = (
        soup.select("li.s-item")
        or soup.select("div.s-item")
        or soup.select("[class*='s-item__wrapper']")
    )
    print(f"  {len(items)} items dans le HTML")

    prices = []
    for item in items:
        price_el = (
            item.select_one(".s-item__price")
            or item.select_one("span.POSITIVE")
            or item.select_one(".prc")
        )
        if not price_el:
            continue
        price = parse_price(price_el.get_text(strip=True))
        if price is not None:
            prices.append(price)
        if len(prices) >= MAX_RESULTS_PER_CARD:
            break

    return prices


def robust_median(prices):
    if not prices:
        return None
    if len(prices) <= 2:
        return statistics.median(prices)
    mean = statistics.mean(prices)
    stdev = statistics.stdev(prices)
    if stdev == 0:
        return statistics.median(prices)
    filtered = [p for p in prices if abs(p - mean) <= 2 * stdev]
    return statistics.median(filtered) if filtered else statistics.median(prices)


def load_prices(path):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"last_update": None, "cards": {}}


def update_card(data, card, now_iso, session, base_url, rate):
    prices_raw = fetch_sold_prices(session, base_url, card["query"])
    if not prices_raw:
        print(f"  ⚠ Aucune vente trouvee, prix inchange")
        return False
    median_raw = robust_median(prices_raw)
    median_eur = round(median_raw * rate)
    print(f"  ✓ Mediane: {median_raw:.0f} -> {median_eur}€  (sur {len(prices_raw)} ventes)")
    entry = data["cards"].get(card["id"], {"history": [], "price": None})
    hist = entry.get("history", [])
    hist.append(median_eur)
    entry["history"] = hist[-MAX_HISTORY:]
    entry["price"] = median_eur
    entry["sales_count"] = len(prices_raw)
    entry["last_update"] = now_iso
    data["cards"][card["id"]] = entry
    return True


def try_site(base_url, currency, data, now_iso):
    print(f"\n╔══ Tentative {base_url} ({currency}) ══╗")
    rate = get_rate(currency)
    session = requests.Session()
    if not warm_up_session(session, base_url):
        print(f"Warm-up echoue sur {base_url}, on passe")
        return 0
    updated = 0
    for card in CARDS:
        print(f"\n[{card['id']}]")
        try:
            if update_card(data, card, now_iso, session, base_url, rate):
                updated += 1
        except Exception as e:
            print(f"  ERREUR: {e}")
        time.sleep(random.uniform(3, 6))
    print(f"\n→ {updated}/{len(CARDS)} cartes mises a jour via {base_url}")
    return updated


def main():
    path = "prices.json"
    data = load_prices(path)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    print(f"=== PKMN VAULT update @ {now} ===")

    updated = try_site("https://www.ebay.com", "USD", data, now)

    if updated == 0:
        print("\n⚠ ebay.com a tout bloque, fallback ebay.co.uk...")
        updated = try_site("https://www.ebay.co.uk", "GBP", data, now)

    data["last_update"] = now

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"\n✓ {path} mis a jour ({updated}/{len(CARDS)} cartes scrapees)")


if __name__ == "__main__":
    main()
