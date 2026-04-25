#!/usr/bin/env python3
"""
PKMN VAULT - Price Updater v7
3 couches de filtrage anti-faux-positif :
  1. must_contain : tous les mots-cles obligatoires (regex \b0*N\b sur les chiffres)
  2. must_match_one : au moins un mot-cle parmi cette liste
  3. price range : fourchette min/max par carte (anti-cartes-pas-cheres et lots)
Logs verbeux : titres + prix rejetes par chaque couche.
"""

import json
import os
import random
import re
import statistics
import time
import unicodedata
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

# ═══════════════════════════════════════════════════════════════════
CARDS = [
    {
        "id": "charizard-v-ssv",
        "url_eu": "https://www.ebay.fr/sch/i.html?_nkw=PSA+10+Charizard+V+307%2F190+Shiny+Star+V+Japanese&_sacat=0&_from=R40&_trksid=m570.l1313&_odkw=PSA+10+Umbreon+ex+217%2F187+SV8a+Terastal+Festival+Japanese&_osacat=0&_sop=13&LH_PrefLoc=3&LH_Sold=1",
        "url_ww": "https://www.ebay.fr/sch/i.html?_nkw=PSA+10+Charizard+V+307%2F190+Shiny+Star+V+Japanese&_sacat=0&_from=R40&_sop=13&LH_Sold=1&rt=nc&LH_PrefLoc=2",
        "must_contain": ["psa 10", "charizard", "307"],
        "must_match_one": ["shiny star", "s4a", "190", "ssv"],
        "price_min": 100,
        "price_max": 600,
    },
    {
        "id": "mentali-v-eh",
        "url_eu": "https://www.ebay.fr/sch/i.html?_from=R40&_nkw=PSA+10+Espeon+V+081%2F069+Eevee+Heroes+Japanese&LH_Sold=1&LH_Complete=1&_sop=13&rt=nc&LH_PrefLoc=3",
        "url_ww": "https://www.ebay.fr/sch/i.html?_from=R40&_nkw=PSA+10+Espeon+V+081%2F069+Eevee+Heroes+Japanese&LH_Sold=1&LH_Complete=1&_sop=13&rt=nc&LH_PrefLoc=2",
        "must_contain": ["psa 10", "espeon", "81"],
        "must_match_one": ["eevee heroes", "s6a", "69"],
        "price_min": 150,
        "price_max": 700,
    },
    {
        "id": "dracaufeu-ex-151",
        "url_eu": "https://www.ebay.fr/sch/i.html?_from=R40&_nkw=PSA+10+Charizard+ex+201%2F165+SV2a+151+Japanese&LH_Sold=1&LH_PrefLoc=3&_sop=13&rt=nc",
        "url_ww": "https://www.ebay.fr/sch/i.html?_from=R40&_nkw=PSA+10+Charizard+ex+201%2F165+SV2a+151+Japanese&LH_Sold=1&_sop=13&LH_PrefLoc=2&rt=nc",
        "must_contain": ["psa 10", "charizard", "201"],
        "must_match_one": ["151", "sv2a", "165"],
        "price_min": 400,
        "price_max": 1500,
    },
    {
        "id": "pikachu-ex-sv8",
        "url_eu": "https://www.ebay.fr/sch/i.html?_from=R40&_nkw=PSA+10+Pikachu+ex+132%2F106+SV8+Super+Electric+Breaker+Japanese&LH_Sold=1&_sop=13&rt=nc&LH_PrefLoc=3",
        "url_ww": "https://www.ebay.fr/sch/i.html?_from=R40&_nkw=PSA+10+Pikachu+ex+132%2F106+SV8+Super+Electric+Breaker+Japanese&LH_Sold=1&_sop=13&rt=nc&LH_PrefLoc=2",
        "must_contain": ["psa 10", "pikachu", "132"],
        "must_match_one": ["electric breaker", "sv8", "106"],
        "price_min": 250,
        "price_max": 1500,
    },
    {
        "id": "umbreon-ex-sv8a",
        "url_eu": "https://www.ebay.fr/sch/i.html?_from=R40&_nkw=PSA+10+Umbreon+ex+217%2F187+SV8a+Terastal+Festival+Japanese&LH_Sold=1&_sop=13&LH_PrefLoc=3&rt=nc&LH_Complete=1",
        "url_ww": "https://www.ebay.fr/sch/i.html?_from=R40&_nkw=PSA+10+Umbreon+ex+217%2F187+SV8a+Terastal+Festival+Japanese&LH_Sold=1&_sop=13&rt=nc&LH_PrefLoc=2",
        "must_contain": ["psa 10", "umbreon", "217"],
        "must_match_one": ["terastal", "sv8a", "187"],
        "price_min": 400,
        "price_max": 1500,
    },
]

MAX_HISTORY = 11
MAX_VALID_RESULTS = 10  # plafond apres tous les filtres - 10 dernieres ventes seulement
MAX_ITEMS_TO_SCAN = 100  # on lit jusqu'a 100 listings pour atteindre les 10 valides

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


def normalize(text):
    """Lowercase + retire accents pour matching robuste."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return text.lower()


def keyword_to_pattern(kw):
    """Convertit un mot-cle en regex.
    - Numerique ('81') -> \b0*81\b matche '081', '0081', '81'.
    - Texte avec espace ('psa 10') -> tolerance 0+ espaces ('PSA10' OK).
    """
    kw_norm = normalize(kw)
    if kw_norm.isdigit():
        return re.compile(r"\b0*" + kw_norm + r"\b")
    escaped = re.escape(kw_norm).replace(r"\ ", r"\s*")
    return re.compile(escaped)


def title_matches_card(title, must_contain, must_match_one):
    """True si title contient TOUS les must_contain ET au moins un must_match_one."""
    title_norm = normalize(title)
    for kw in must_contain:
        if not keyword_to_pattern(kw).search(title_norm):
            return False
    if must_match_one:
        if not any(keyword_to_pattern(kw).search(title_norm) for kw in must_match_one):
            return False
    return True


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


def parse_price(text, price_min, price_max):
    """Parse un texte eBay et renvoie le prix s'il est dans la fourchette."""
    if not text:
        return None
    if " to " in text.lower() or " à " in text:
        return None
    cleaned = text.replace("\xa0", " ").replace(",", ".").replace("€", "").replace("EUR", "")
    m = re.search(r"(\d+(?:\.\d+)?)", cleaned)
    if not m:
        return None
    try:
        num = float(m.group(1))
        if price_min <= num <= price_max:
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
    for marker, meaning in [
        ("pas de correspondance", "aucun résultat eBay"),
        ("no exact matches", "aucun résultat exact"),
        ("captcha", "CAPTCHA détecté"),
        ("robot", "anti-bot détecté"),
        ("access denied", "accès refusé"),
        ("pardon our interruption", "challenge PerimeterX"),
    ]:
        if marker in lower:
            print(f"  → Signal: {meaning}")
            return


def fetch_url_filtered(session, url, label, card):
    """Fetch + applique les 3 couches de filtre. Renvoie la liste des prix valides."""
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

    mc = card["must_contain"]
    mmo = card.get("must_match_one", [])
    pmin = card["price_min"]
    pmax = card["price_max"]

    prices = []
    scanned = 0
    rejected_title = 0
    rejected_price = 0
    title_examples = []
    price_examples = []

    for item in items:
        if scanned >= MAX_ITEMS_TO_SCAN:
            break

        title_el = (
            item.select_one(".s-item__title")
            or item.select_one("[class*='s-item__title']")
            or item.select_one("h3")
            or item.select_one("[role='heading']")
        )
        if not title_el:
            continue
        title = title_el.get_text(strip=True)
        if not title or title.lower() in ("shop on ebay", "achetez sur ebay"):
            continue

        scanned += 1

        # Couches 1+2 : filtre de titre
        if not title_matches_card(title, mc, mmo):
            rejected_title += 1
            if len(title_examples) < 3:
                title_examples.append(title[:80])
            continue

        # Extraction prix avec couche 3 : range par carte
        price_el = (
            item.select_one(".s-item__price")
            or item.select_one("span.POSITIVE")
            or item.select_one(".prc")
            or item.select_one("[class*='price']")
        )
        if not price_el:
            continue
        price_text = price_el.get_text(strip=True)
        price = parse_price(price_text, pmin, pmax)
        if price is None:
            rejected_price += 1
            if len(price_examples) < 3:
                price_examples.append(f"{title[:60]} → {price_text[:30]}")
            continue

        prices.append(price)
        if len(prices) >= MAX_VALID_RESULTS:
            break

    print(f"  → scannés:{scanned} | rejetés titre:{rejected_title} | rejetés prix:{rejected_price} | conservés:{len(prices)} (range {pmin}-{pmax}€)")
    if title_examples:
        print(f"  Rejetés (titre):")
        for ex in title_examples:
            print(f"    × {ex}")
    if price_examples:
        print(f"  Rejetés (prix hors range):")
        for ex in price_examples:
            print(f"    × {ex}")

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


def update_market(entry, history_key, price_key, count_key, prices):
    """Append le nouveau prix a l'historique en gardant max MAX_HISTORY points."""
    if not prices:
        return False
    median = round(robust_median(prices))
    print(f"    ✓ Médiane: {median}€  (sur {len(prices)} ventes valides)")
    hist = list(entry.get(history_key, []))
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
    print(f"=== Source: {BASE_URL} | filtres: titre + range prix ===\n")

    session = requests.Session()
    if not warm_up(session):
        print("Warm-up échoué, on tente quand même\n")

    updated = 0
    for i, card in enumerate(CARDS, 1):
        cid = card["id"]
        print(f"\n[{cid}] ({i}/{len(CARDS)})")
        print(f"  Filtre: contient={card['must_contain']} | un_de={card['must_match_one']}")
        print(f"  Range prix: {card['price_min']}-{card['price_max']}€")
        entry = data["cards"].get(cid, {})

        # 🇪🇺 EU
        print(f"  🇪🇺 marché Europe")
        try:
            prices_eu = fetch_url_filtered(session, card["url_eu"], "EU", card)
            if update_market(entry, "history_eu", "price_eu", "sales_count_eu", prices_eu):
                updated += 1
                # Retro-compat ancien format (price + history = EU)
                entry["price"] = entry["price_eu"]
                entry["history"] = entry["history_eu"]
            else:
                print(f"    ⚠ Aucune vente EU exploitable, prix inchangé")
        except Exception as e:
            print(f"    ERREUR EU: {e}")

        time.sleep(random.uniform(6, 11))

        # 🌎 WW
        print(f"  🌎 marché Monde")
        try:
            prices_ww = fetch_url_filtered(session, card["url_ww"], "WW", card)
            if update_market(entry, "history_ww", "price_ww", "sales_count_ww", prices_ww):
                updated += 1
            else:
                print(f"    ⚠ Aucune vente WW exploitable, prix inchangé")
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
