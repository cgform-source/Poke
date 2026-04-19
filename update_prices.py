#!/usr/bin/env python3
“””
PKMN VAULT - Price Updater v2

- Scrape ebay.com (gros volume de ventes PSA 10 Japanese vs ebay.fr vide)
- Conversion USD -> EUR automatique via API publique
- Requetes simplifiees
- Selecteurs CSS multiples (fallback si eBay change son HTML)
- Logs detailles pour diagnostic
  “””

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

# CARTES - requetes simplifiees pour maximiser les resultats

# ═══════════════════════════════════════════════════════════════════

CARDS = [
{
“id”: “charizard-v-ssv”,
“query”: “PSA 10 Charizard V 307 Shiny Star V Japanese”,
},
{
“id”: “mentali-v-eh”,
“query”: “PSA 10 Espeon V 081 Eevee Heroes Japanese”,
},
{
“id”: “dracaufeu-ex-151”,
“query”: “PSA 10 Charizard ex 201 Pokemon 151 Japanese”,
},
{
“id”: “pikachu-ex-sv8”,
“query”: “PSA 10 Pikachu ex 132 Super Electric Breaker”,
},
{
“id”: “umbreon-ex-sv8a”,
“query”: “PSA 10 Umbreon ex 217 Terastal Festival”,
},
]

# Bornes de sanité en USD (converties ensuite en EUR)

PRICE_MIN_USD = 50
PRICE_MAX_USD = 8000
MAX_HISTORY = 11
MAX_RESULTS_PER_CARD = 30

DEFAULT_USD_TO_EUR = 0.92  # fallback si API taux indispo

HEADERS = {
“User-Agent”: (
“Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) “
“AppleWebKit/537.36 (KHTML, like Gecko) “
“Chrome/120.0.0.0 Safari/537.36”
),
“Accept”: “text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8”,
“Accept-Language”: “en-US,en;q=0.9”,
}

def get_usd_to_eur() -> float:
“”“Recupere le taux USD->EUR en direct, fallback si l’API est down.”””
try:
r = requests.get(“https://api.exchangerate-api.com/v4/latest/USD”, timeout=10)
rate = float(r.json()[“rates”][“EUR”])
print(f”Taux USD->EUR: {rate:.4f}”)
return rate
except Exception as e:
print(f”API taux indispo ({e}), fallback {DEFAULT_USD_TO_EUR}”)
return DEFAULT_USD_TO_EUR

def parse_price_usd(text: str) -> float | None:
“”“Extrait un montant en USD depuis un texte eBay.”””
if not text:
return None
# Ignorer les fourchettes (”$12.00 to $45.00”)
if “ to “ in text.lower() or “ à “ in text:
return None
# Enlever separateurs de milliers et symbole
cleaned = text.replace(”\xa0”, “ “).replace(”,”, “”).replace(”$”, “”)
match = re.search(r”(\d+(?:.\d+)?)”, cleaned)
if not match:
return None
try:
num = float(match.group(1))
if PRICE_MIN_USD <= num <= PRICE_MAX_USD:
return num
except ValueError:
pass
return None

def fetch_sold_prices_usd(query: str) -> list[float]:
“”“Scrape ebay.com sold listings, renvoie les prix en USD.”””
url = (
f”https://www.ebay.com/sch/i.html?”
f”_from=R40&_nkw={quote(query)}”
f”&LH_Sold=1&LH_Complete=1”
f”&_sop=13”
f”&_ipg=60”
)
print(f”  GET {url[:130]}…”)

```
try:
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
except requests.RequestException as e:
    print(f"  ERREUR fetch: {e}")
    return []

print(f"  HTTP {r.status_code}, {len(r.content)} bytes reçus")

soup = BeautifulSoup(r.text, "html.parser")

# Plusieurs selecteurs - eBay change sa structure regulierement
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
        or item.select_one("[class*='price']")
    )
    if not price_el:
        continue

    price = parse_price_usd(price_el.get_text(strip=True))
    if price is not None:
        prices.append(price)

    if len(prices) >= MAX_RESULTS_PER_CARD:
        break

return prices
```

def robust_median(prices: list[float]) -> float | None:
“”“Mediane robuste : exclut les outliers au-dela de 2 ecarts-types.”””
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
with open(path, encoding=“utf-8”) as f:
return json.load(f)
except (json.JSONDecodeError, OSError) as e:
print(f”prices.json illisible ({e}), re-creation”)
return {“last_update”: None, “cards”: {}}

def update_card(data: dict, card: dict, now_iso: str, usd_to_eur: float) -> None:
prices_usd = fetch_sold_prices_usd(card[“query”])
if not prices_usd:
print(f”  ⚠ Aucune vente trouvee, prix inchange”)
return

```
median_usd = robust_median(prices_usd)
median_eur = round(median_usd * usd_to_eur)
print(f"  ✓ Mediane: ${median_usd:.0f} -> {median_eur}€  (sur {len(prices_usd)} ventes)")

entry = data["cards"].get(card["id"], {"history": [], "price": None})
hist = entry.get("history", [])
hist.append(median_eur)
entry["history"] = hist[-MAX_HISTORY:]

entry["price"] = median_eur
entry["sales_count"] = len(prices_usd)
entry["last_update"] = now_iso
data["cards"][card["id"]] = entry
```

def main():
path = “prices.json”
data = load_prices(path)
now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
usd_to_eur = get_usd_to_eur()

```
print(f"=== PKMN VAULT update @ {now} (source: ebay.com) ===\n")

for card in CARDS:
    print(f"[{card['id']}]")
    try:
        update_card(data, card, now, usd_to_eur)
    except Exception as e:
        print(f"  ERREUR: {e}")
    time.sleep(3)

data["last_update"] = now

with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print(f"\n✓ {path} mis a jour")
```

if **name** == “**main**”:
main()
