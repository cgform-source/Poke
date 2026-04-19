#!/usr/bin/env python3
"""
PKMN VAULT - Price Updater
Scrape eBay.fr ventes complétées PSA 10 pour chaque carte,
calcule la médiane robuste (exclut les outliers 2σ),
met à jour prices.json.
"""

import json
import os
import re
import statistics
import time
from datetime import datetime, timezone
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

# ═══════════════════════════════════════════════════════════════════
# CARTES A TRACKER - doit correspondre aux ids dans index.html
# ═══════════════════════════════════════════════════════════════════
CARDS = [
    {
        "id": "charizard-v-ssv",
        "query": "PSA 10 Charizard V 307/190 Shiny Star V Japanese",
    },
    {
        "id": "mentali-v-eh",
        "query": "PSA 10 Espeon V 081/069 Eevee Heroes Japanese",
    },
    {
        "id": "dracaufeu-ex-151",
        "query": "PSA 10 Charizard ex 201/165 SV2a 151 Japanese",
    },
    {
        "id": "pikachu-ex-sv8",
        "query": "PSA 10 Pikachu ex 132/106 SV8 Super Electric Breaker Japanese",
    },
    {
        "id": "umbreon-ex-sv8a",
        "query": "PSA 10 Umbreon ex 217/187 SV8a Terastal Festival Japanese",
    },
]

# Bornes de sanité pour écarter les ventes aberrantes (lots, erreurs)
PRICE_MIN = 50
PRICE_MAX = 5000
MAX_HISTORY = 11  # on garde 11 points dans l'historique
MAX_RESULTS_PER_CARD = 30  # on scrape jusqu'à 30 ventes par carte

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}


def parse_price(text: str) -> float | None:
    """Extrait un montant en € depuis un texte eBay. Renvoie None si invalide."""
    if not text:
        return None
    # Ignorer les fourchettes ("12,00 € à 45,00 €")
    if " à " in text or " to " in text.lower():
        return None
    # Nettoyer et chercher un nombre
    cleaned = text.replace("\xa0", " ").replace(",", ".")
    # Pattern : un nombre potentiellement séparé par des espaces (milliers)
    matches = re.findall(r"(\d{1,3}(?:\s?\d{3})*(?:\.\d+)?)", cleaned)
    if not matches:
        return None
    try:
        num = float(matches[0].replace(" ", ""))
        if PRICE_MIN <= num <= PRICE_MAX:
            return num
    except ValueError:
        pass
    return None


def fetch_sold_prices(query: str) -> list[float]:
    """Scrape les ventes complétées eBay.fr, renvoie la liste des prix."""
    url = (
        f"https://www.ebay.fr/sch/i.html?"
        f"_from=R40&_nkw={quote(query)}"
        f"&LH_Sold=1&LH_Complete=1"
        f"&_sop=13"  # trié par date de fin la plus récente
        f"&_ipg=60"  # 60 résultats par page
    )
    print(f"  GET {url[:120]}...")
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"  ERREUR fetch: {e}")
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    prices = []

    for item in soup.select("li.s-item"):
        # eBay met souvent un 1er item "placeholder", on skip s'il n'a pas de lien valide
        link = item.select_one(".s-item__link")
        if not link or "itm/" not in link.get("href", ""):
            continue

        price_el = item.select_one(".s-item__price")
        if not price_el:
            continue

        price = parse_price(price_el.get_text(strip=True))
        if price is not None:
            prices.append(price)

        if len(prices) >= MAX_RESULTS_PER_CARD:
            break

    return prices


def robust_median(prices: list[float]) -> float | None:
    """
    Médiane robuste : exclut les outliers au-delà de 2 écarts-types.
    Renvoie None si aucun prix utilisable.
    """
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


def load_prices(path: str) -> dict:
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"ATTENTION: prices.json illisible ({e}), re-création")
    return {"last_update": None, "cards": {}}


def update_card(data: dict, card: dict, now_iso: str) -> None:
    """Met à jour une carte dans le dict data."""
    prices = fetch_sold_prices(card["query"])
    if not prices:
        print(f"  ⚠ Aucune vente trouvée pour {card['id']}, prix inchangé")
        return

    median = round(robust_median(prices))
    print(f"  ✓ Médiane: {median}€  (sur {len(prices)} ventes)")

    entry = data["cards"].get(card["id"], {"history": [], "price": None})

    # Ajout du nouveau point + rotation pour garder MAX_HISTORY valeurs
    hist = entry.get("history", [])
    hist.append(median)
    entry["history"] = hist[-MAX_HISTORY:]

    entry["price"] = median
    entry["sales_count"] = len(prices)
    entry["last_update"] = now_iso
    data["cards"][card["id"]] = entry


def main():
    path = "prices.json"
    data = load_prices(path)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    print(f"=== PKMN VAULT update @ {now} ===\n")

    for card in CARDS:
        print(f"[{card['id']}]")
        try:
            update_card(data, card, now)
        except Exception as e:
            print(f"  ERREUR: {e}")
        time.sleep(3)  # on reste poli avec eBay

    data["last_update"] = now

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"\n✓ {path} mis à jour")


if __name__ == "__main__":
    main()
