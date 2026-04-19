#!/usr/bin/env python3
"""
PKMN VAULT - Price Updater v4
- eBay.fr en primaire (EUR direct)
- Requetes simplifiees (moins de mots-cles = plus de matches)
- Delays longs entre cartes (8-15s) pour simuler un humain
- Selecteurs CSS modernes + legacy
- Debug verbeux : title de la page, detection "0 resultat"
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
# Requetes courtes - plus de matches que les precedentes trop specifiques
CARDS = [
    {"id": "charizard-v-ssv",   "query": "PSA 10 Charizard V Shiny Star V"},
    {"id": "mentali-v-eh",      "query": "PSA 10 Espeon V Eevee Heroes"},
    {"id": "dracaufeu-ex-151",  "query": "PSA 10 Charizard ex 201 Pokemon 151"},
    {"id": "pikachu-ex-sv8",    "query": "PSA 10 Pikachu ex 132 Super Electric Breaker"},
    {"id": "umbreon-ex-sv8a",   "query": "PSA 10 Umbreon ex Terastal Festival"},
]

PRICE_MIN = 50
PRICE_MAX = 8000
MAX_HISTORY = 11
MAX_RESULTS_PER_CARD = 30

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
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
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


def warm_up(session, base_url):
    print(f"Warm-up: GET {base_url}/ ...")
    try:
        r = session.get(base_url + "/", headers=BROWSER_HEADERS, timeout=30)
        print(f"  HTTP {r.status_code}, {len(r.content)} bytes, {len(session.cookies)} cookies")
        if r.status_code != 200:
            return False
        time.sleep(random.uniform(3, 6))  # pause humaine apres landing
        r = session.get(base_url + "/sch/i.html?_nkw=pokemon", headers=BROWSER_HEADERS, timeout=30)
        print(f"  warmup search: HTTP {r.status_code}, {len(session.cookies)} cookies")
        time.sleep(random.uniform(2, 4))
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
        text.replace("\xa0", " ").replace(",", ".").replace("€", "").replace("EUR", "")
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


def extract_items(soup):
    """Essaie plusieurs selecteurs eBay, renvoie la premiere liste non vide."""
    selectors = [
        "li.s-item",
        "div.s-item",
        "ul.srp-results > li",
        ".srp-results__list > li",
        "[class*='s-item__wrapper']",
        "[data-view*='iid']",
    ]
    for sel in selectors:
        items = soup.select(sel)
        if items:
            return items, sel
    return [], None


def diagnose_page(soup, text_content):
    """Log des infos de debug pour comprendre ce qu'eBay renvoie."""
    title = soup.find("title")
    if title:
        print(f"  <title>: {title.get_text(strip=True)[:100]}")

    # Indices d'absence de resultats
    lower = text_content.lower()
    signals = {
        "pas de correspondance": "aucun résultat eBay.fr",
        "no exact matches": "aucun résultat exact",
        "0 résultats": "0 résultats",
        "captcha": "CAPTCHA détecté",
        "robot": "anti-bot détecté",
        "access denied": "accès refusé",
        "pardon our interruption": "challenge PerimeterX",
    }
    for marker, meaning in signals.items():
        if marker in lower:
            print(f"  → Signal: {meaning}")
            break


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
                wait = 3 ** attempt + random.uniform(0, 2)
                print(f"  HTTP {r.status_code}, retry dans {wait:.1f}s ({attempt}/3)")
                time.sleep(wait)
                continue
            print(f"  HTTP {r.status_code} inattendu, abandon")
            return []
        except requests.RequestException as e:
            wait = 3 ** attempt
            print(f"  ERREUR {e}, retry dans {wait}s ({attempt}/3)")
            time.sleep(wait)

    if r is None or r.status_code != 200:
        return []

    print(f"  HTTP {r.status_code}, {len(r.content)} bytes")

    soup = BeautifulSoup(r.text, "html.parser")
    items, used_selector = extract_items(soup)

    if not items:
        print(f"  0 items trouvés avec tous les sélecteurs")
        diagnose_page(soup, r.text)
        return []

    print(f"  {len(items)} items trouvés via '{used_selector}'")

    prices = []
    for item in items:
        price_el = (
            item.select_one(".s-item__price")
            or item.select_one("span.POSITIVE")
            or item.select_one(".prc")
            or item.select_one("[class*='price']")
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


def update_card(data, card, now_iso, session, base_url):
    prices = fetch_sold_prices(session, base_url, card["query"])
    if not prices:
        print(f"  ⚠ Aucune vente exploitable, prix inchange")
        return False
    median = round(robust_median(prices))
    print(f"  ✓ Mediane: {median}€  (sur {len(prices)} ventes)")
    entry = data["cards"].get(card["id"], {"history": [], "price": None})
    hist = entry.get("history", [])
    hist.append(median)
    entry["history"] = hist[-MAX_HISTORY:]
    entry["price"] = median
    entry["sales_count"] = len(prices)
    entry["last_update"] = now_iso
    data["cards"][card["id"]] = entry
    return True


def main():
    path = "prices.json"
    data = load_prices(path)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    base_url = "https://www.ebay.fr"

    print(f"=== PKMN VAULT update @ {now} (source: {base_url}) ===\n")

    session = requests.Session()
    if not warm_up(session, base_url):
        print("Warm-up echoue, on tente quand meme")

    updated = 0
    for i, card in enumerate(CARDS, 1):
        print(f"\n[{card['id']}] ({i}/{len(CARDS)})")
        try:
            if update_card(data, card, now, session, base_url):
                updated += 1
        except Exception as e:
            print(f"  ERREUR: {e}")
        if i < len(CARDS):
            delay = random.uniform(8, 15)
            print(f"  ... pause {delay:.1f}s avant carte suivante")
            time.sleep(delay)

    data["last_update"] = now
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"\n✓ {path} mis a jour — {updated}/{len(CARDS)} cartes scrapees")


if __name__ == "__main__":
    main()
