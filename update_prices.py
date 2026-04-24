#!/usr/bin/env python3
"""
PKMN VAULT - Price Updater v5
- Scrape 2 marches par carte : Europe (LH_PrefLoc=3) + Monde (LH_PrefLoc=2)
- URLs exactes fournies par l'utilisateur (zero modification)
- Stocke history_eu + history_ww + retro-compat (price + history = EU)
- Selecteur ul.srp-results > li (confirme marche en V4)
- Delais longs entre requetes (humain-like)
"""

import json
import os
import random
import re
import statistics
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

# ═══════════════════════════════════════════════════════════════════
# Cartes avec URLs exactes EU + WW fournies par l'utilisateur
# ═══════════════════════════════════════════════════════════════════
CARDS = [
    {
        "id": "charizard-v-ssv",
        "url_eu": "https://www.ebay.fr/sch/i.html?_nkw=PSA+10+Charizard+V+307%2F190+Shiny+Star+V+Japanese&_sacat=0&_from=R40&_trksid=m570.l1313&_odkw=PSA+10+Umbreon+ex+217%2F187+SV8a+Terastal+Festival+Japanese&_osacat=0&_sop=13&LH_PrefLoc=3&LH_Sold=1",
        "url_ww": "https://www.ebay.fr/sch/i.html?_nkw=PSA+10+Charizard+V+307%2F190+Shiny+Star+V+Japanese&_sacat=0&_from=R40&_sop=13&LH_Sold=1&rt=nc&LH_PrefLoc=2",
    },
    {
        "id": "mentali-v-eh",
        "url_eu": "https://www.ebay.fr/sch/i.html?_from=R40&_nkw=PSA+10+Espeon+V+081%2F069+Eevee+Heroes+Japanese&LH_Sold=1&LH_Complete=1&_sop=13&rt=nc&LH_PrefLoc=3",
        "url_ww": "https://www.ebay.fr/sch/i.html?_from=R40&_nkw=PSA+10+Espeon+V+081%2F069+Eevee+Heroes+Japanese&LH_Sold=1&LH_Complete=1&_sop=13&rt=nc&LH_PrefLoc=2",
    },
    {
        "id": "dracaufeu-ex-151",
        "url_eu": "https://www.ebay.fr/sch/i.html?_from=R40&_nkw=PSA+10+Charizard+ex+201%2F165+SV2a+151+Japanese&LH_Sold=1&LH_PrefLoc=3&_sop=13&rt=nc",
        "url_ww": "https://www.ebay.fr/sch/i.html?_from=R40&_nkw=PSA+10+Charizard+ex+201%2F165+SV2a+151+Japanese&LH_Sold=1&_sop=13&LH_PrefLoc=2&rt=nc",
    },
    {
        "id": "pikachu-ex-sv8",
        "url_eu": "https://www.ebay.fr/sch/i.html?_from=R40&_nkw=PSA+10+Pikachu+ex+132%2F106+SV8+Super+Electric+Breaker+Japanese&LH_Sold=1&_sop=13&rt=nc&LH_PrefLoc=3",
        "url_ww": "https://www.ebay.fr/sch/i.html?_from=R40&_nkw=PSA+10+Pikachu+ex+132%2F106+SV8+Super+Electric+Breaker+Japanese&LH_Sold=1&_sop=13&rt=nc&LH_PrefLoc=2",
    },
    {
        "id": "umbreon-ex-sv8a",
        "url_eu": "https://www.ebay.fr/sch/i.html?_from=R40&_nkw=PSA+10+Umbreon+ex+217%2F187+SV8a+Terastal+Festival+Japanese&LH_Sold=1&_sop=13&LH_PrefLoc=3&rt=nc&LH_Complete=1",
        "url_ww": "https://www.ebay.fr/sch/i.html?_from=R40&_nkw=PSA+10+Umbreon+ex+217%2F187+SV8a+Terastal+Festival+Japanese&LH_Sold=1&_sop=13&rt=nc&LH_PrefLoc=2",
    },
]

PRICE_MIN = 50
PRICE_MAX = 8000
MAX_HISTORY = 11
MAX_RESULTS_PER_QUERY = 30

BASE_URL = "https://www.ebay.fr"

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


def warm_up(session):
    print(f"Warm-up: GET {BASE_URL}/ ...")
    try:
        r = session.get(BASE_URL + "/", headers=BROWSER_HEADERS, timeout=30)
        print(f"  HTTP {r.status_code}, {len(r.content)} bytes, {len(session.cookies)} cookies")
        if r.status_code != 200:
            return False
        time.sleep(random.uniform(3, 5))
        r = session.get(BASE_URL + "/sch/i.html?_nkw=pokemon", headers=BROWSER_HEADERS, timeout=30)
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
    selectors = [
        "ul.srp-results > li",
        "li.s-item",
        "div.s-item",
        ".srp-results__list > li",
        "[class*='s-item__wrapper']",
        "[data-view*='iid']",
    ]
    for sel in selectors:
        items = soup.select(sel)
        if items:
            return items, sel
    return [], None


def diagnose(soup, html):
    title = soup.find("title")
    if title:
        print(f"  <title>: {title.get_text(strip=True)[:100]}")
    lower = html.lower()
    signals = {
        "pas de correspondance": "aucun résultat eBay",
        "no exact matches": "aucun résultat exact",
        "captcha": "CAPTCHA détecté",
        "robot": "anti-bot détecté",
        "access denied": "accès refusé",
        "pardon our interruption": "challenge PerimeterX",
    }
    for marker, meaning in signals.items():
        if marker in lower:
            print(f"  → Signal: {meaning}")
            break


def fetch_url(session, url, label):
    print(f"  [{label}] GET {url[:130]}...")
    headers = dict(BROWSER_HEADERS)
    headers["Referer"] = BASE_URL + "/"
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
    items, used_sel = extract_items(soup)
    if not items:
        print(f"  0 items trouvés")
        diagnose(soup, r.text)
        return []
    print(f"  {len(items)} items via '{used_sel}'")

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
        if len(prices) >= MAX_RESULTS_PER_QUERY:
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


def update_market(entry, history_key, price_key, count_key, prices, now_iso):
    """Met a jour un marche (EU ou WW) dans entry."""
    if not prices:
        return False
    median = round(robust_median(prices))
    print(f"    ✓ Médiane: {median}€  (sur {len(prices)} ventes)")
    hist = entry.get(history_key, [])
    hist.append(median)
    entry[history_key] = hist[-MAX_HISTORY:]
    entry[price_key] = median
    entry[count_key] = len(prices)
    return True


def main():
    path = "prices.json"
    data = load_prices(path)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    print(f"=== PKMN VAULT update @ {now} ===")
    print(f"=== Source: {BASE_URL} | 2 marchés par carte (🇪🇺 + 🌎) ===\n")

    session = requests.Session()
    if not warm_up(session):
        print("Warm-up échoué, on tente quand même\n")

    updated = 0
    for i, card in enumerate(CARDS, 1):
        cid = card["id"]
        print(f"\n[{cid}] ({i}/{len(CARDS)})")
        entry = data["cards"].get(cid, {})

        # 🇪🇺 EU
        print(f"  🇪🇺 marché Europe")
        try:
            prices_eu = fetch_url(session, card["url_eu"], "EU")
            if update_market(entry, "history_eu", "price_eu", "sales_count_eu", prices_eu, now):
                updated += 1
                # retro-compat ancien format
                entry["price"] = entry["price_eu"]
                entry["history"] = entry["history_eu"]
            else:
                print(f"    ⚠ Aucune vente EU exploitable")
        except Exception as e:
            print(f"    ERREUR EU: {e}")

        time.sleep(random.uniform(6, 11))

        # 🌎 WW
        print(f"  🌎 marché Monde")
        try:
            prices_ww = fetch_url(session, card["url_ww"], "WW")
            if update_market(entry, "history_ww", "price_ww", "sales_count_ww", prices_ww, now):
                updated += 1
            else:
                print(f"    ⚠ Aucune vente WW exploitable")
        except Exception as e:
            print(f"    ERREUR WW: {e}")

        entry["last_update"] = now
        data["cards"][cid] = entry

        if i < len(CARDS):
            delay = random.uniform(8, 14)
            print(f"  ... pause {delay:.1f}s avant carte suivante")
            time.sleep(delay)

    data["last_update"] = now
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"\n✓ {path} mis à jour — {updated}/{2 * len(CARDS)} marchés scrapés")


if __name__ == "__main__":
    main()
