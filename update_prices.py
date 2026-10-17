#!/usr/bin/env python3
"""
PAPOU VAULT — relevé quotidien des cotes PSA 10.

Même mécanisme qu'avant (runners GitHub Actions, pas la machine de dev) :
  eBay ventes réussies Europe + Monde, médiane robuste, filtres de titre.
Extensions :
  - pas de nouveau point d'historique s'il n'y a pas de nouvelle vente
  - un prix nul ou une source en échec ne remplace jamais un prix connu
  - 10 dernières ventes conservées (l'UI en montre 5), avec date si eBay l'écrit
  - population PSA et fiche Cardmarket en best-effort, sinon repli manuel
  - liste de souhaits lue dans vault.json
  - alertes : issue GitHub si un seuil est franchi ou si une vente apparaît
  - cache local des photos quand PSA les sert (sinon le site garde le hotlink)

Les blocages anti-bot ne sont pas contournés : on note l'échec et on garde
la dernière valeur correcte.
"""

import io
import json
import os
import random
import re
import statistics
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

# ═══════════════════════════════════════════════════════════════════
CARDS = [
    {
        "id": "charizard-v-ssv",
        "name": "Dracaufeu V",
        "cert": "145866913",
        "image": "https://www.psacard.com/cert/145866913/psa/image/57DoD5MGc0a45T7rZvOBbw",
        "cardmarket_url": "https://www.cardmarket.com/fr/Pokemon/Products/Singles/Shiny-Star-V/Charizard-V-s4a307?language=7",
        "url_eu": "https://www.ebay.fr/sch/i.html?_nkw=PSA+10+Charizard+V+307%2F190+Shiny+Star+V+Japanese&_sacat=0&_from=R40&_trksid=m570.l1313&_odkw=PSA+10+Umbreon+ex+217%2F187+SV8a+Terastal+Festival+Japanese&_osacat=0&_sop=13&LH_PrefLoc=3&LH_Sold=1",
        "url_ww": "https://www.ebay.fr/sch/i.html?_nkw=PSA+10+Charizard+V+307%2F190+Shiny+Star+V+Japanese&_sacat=0&_from=R40&_sop=13&LH_Sold=1&rt=nc&LH_PrefLoc=2",
        "must_contain": ["psa 10", "charizard", "307"],
        "must_match_one": ["shiny star", "s4a", "190", "ssv"],
        "price_min": 100,
        "price_max": 600,
    },
    {
        "id": "mentali-v-eh",
        "name": "Mentali V",
        "cert": "95360955",
        "image": "https://www.psacard.com/cert/95360955/psa/image/vWfFGLoOfkGbq605JlutgQ",
        "cardmarket_url": "https://www.cardmarket.com/fr/Pokemon/Products/Singles/Eevee-Heroes/Espeon-V-V3-s6a081?language=7",
        "url_eu": "https://www.ebay.fr/sch/i.html?_from=R40&_nkw=PSA+10+Espeon+V+081%2F069+Eevee+Heroes+Japanese&LH_Sold=1&LH_Complete=1&_sop=13&rt=nc&LH_PrefLoc=3",
        "url_ww": "https://www.ebay.fr/sch/i.html?_from=R40&_nkw=PSA+10+Espeon+V+081%2F069+Eevee+Heroes+Japanese&LH_Sold=1&LH_Complete=1&_sop=13&rt=nc&LH_PrefLoc=2",
        "must_contain": ["psa 10", "espeon", "81"],
        "must_match_one": ["eevee heroes", "s6a", "69"],
        "price_min": 150,
        "price_max": 700,
    },
    {
        "id": "dracaufeu-ex-151",
        "name": "Dracaufeu ex",
        "cert": "102215566",
        "image": "https://www.psacard.com/cert/102215566/psa/image/VCCjBrZ3AES-hPUcUnHh2Q",
        "cardmarket_url": "https://www.cardmarket.com/fr/Pokemon/Products/Singles/Pokemon-Card-151/Charizard-ex-V3-sv2a201?language=7",
        "url_eu": "https://www.ebay.fr/sch/i.html?_from=R40&_nkw=PSA+10+Charizard+ex+201%2F165+SV2a+151+Japanese&LH_Sold=1&LH_PrefLoc=3&_sop=13&rt=nc",
        "url_ww": "https://www.ebay.fr/sch/i.html?_from=R40&_nkw=PSA+10+Charizard+ex+201%2F165+SV2a+151+Japanese&LH_Sold=1&_sop=13&LH_PrefLoc=2&rt=nc",
        "must_contain": ["psa 10", "charizard", "201"],
        "must_match_one": ["151", "sv2a", "165"],
        "price_min": 400,
        "price_max": 1500,
    },
    {
        "id": "pikachu-ex-sv8",
        "name": "Pikachu ex",
        "cert": "102618365",
        "image": "https://www.psacard.com/cert/102618365/psa/image/sLvYjXjxt0yZrUKGPYGTDw",
        "cardmarket_url": "https://www.cardmarket.com/fr/Pokemon/Products/Singles/Super-Electric-Breaker/Pikachu-ex-V3-sv8132?language=7",
        "url_eu": "https://www.ebay.fr/sch/i.html?_from=R40&_nkw=PSA+10+Pikachu+ex+132%2F106+SV8+Super+Electric+Breaker+Japanese&LH_Sold=1&_sop=13&rt=nc&LH_PrefLoc=3",
        "url_ww": "https://www.ebay.fr/sch/i.html?_from=R40&_nkw=PSA+10+Pikachu+ex+132%2F106+SV8+Super+Electric+Breaker+Japanese&LH_Sold=1&_sop=13&rt=nc&LH_PrefLoc=2",
        "must_contain": ["psa 10", "pikachu", "132"],
        "must_match_one": ["electric breaker", "sv8", "106"],
        "price_min": 500,
        "price_max": 1500,
    },
    {
        "id": "umbreon-ex-sv8a",
        "name": "Noctali ex",
        "cert": "109838459",
        "image": "https://www.psacard.com/cert/109838459/psa/image/Ure9Ck43B0KUOT_Bfgneeg",
        "cardmarket_url": "https://www.cardmarket.com/fr/Pokemon/Products/Singles/Terastal-Festival-ex/Umbreon-ex-V2-sv8a217?language=7",
        "url_eu": "https://www.ebay.fr/sch/i.html?_from=R40&_nkw=PSA+10+Umbreon+ex+217%2F187+SV8a+Terastal+Festival+Japanese&LH_Sold=1&_sop=13&LH_PrefLoc=3&rt=nc&LH_Complete=1",
        "url_ww": "https://www.ebay.fr/sch/i.html?_from=R40&_nkw=PSA+10+Umbreon+ex+217%2F187+SV8a+Terastal+Festival+Japanese&LH_Sold=1&_sop=13&rt=nc&LH_PrefLoc=2",
        "must_contain": ["psa 10", "umbreon", "217"],
        "must_match_one": ["terastal", "sv8a", "187"],
        "price_min": 400,
        "price_max": 1500,
    },
]

MAX_HISTORY = 400
MAX_VALID_RESULTS = 10
MAX_ITEMS_TO_SCAN = 100
MAX_SALES_STORED = 10

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

MONTHS = {
    "jan": 1, "janv": 1, "janvier": 1,
    "feb": 2, "fev": 2, "fevr": 2, "février": 2, "fevrier": 2,
    "mar": 3, "mars": 3,
    "apr": 4, "avr": 4, "avril": 4,
    "may": 5, "mai": 5,
    "jun": 6, "juin": 6,
    "jul": 7, "juil": 7, "juillet": 7,
    "aug": 8, "aou": 8, "août": 8, "aout": 8,
    "sep": 9, "sept": 9, "septembre": 9,
    "oct": 10, "octobre": 10,
    "nov": 11, "novembre": 11,
    "dec": 12, "déc": 12, "decembre": 12, "décembre": 12,
}


def normalize(text):
    """Lowercase + retire accents pour matching robuste."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return text.lower()


def keyword_to_pattern(kw):
    """Convertit un mot-cle en regex.
    - Numerique ('81') -> \\b0*81\\b matche '081', '0081', '81'.
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
        if num <= 0:
            return None
        if price_min <= num <= price_max:
            return num
    except ValueError:
        pass
    return None


def parse_sold_date(text):
    """Extrait une date AAAA-MM-JJ si le texte eBay en contient une. Sinon None."""
    if not text:
        return None
    raw = normalize(text).replace(".", " ")
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.search(r"(\d{1,2})\s+([a-z]+)\s+(\d{4})", raw)
    if not m:
        m = re.search(r"([a-z]+)\s+(\d{1,2}),?\s+(\d{4})", raw)
        if m:
            month = MONTHS.get(m.group(1)[:3]) or MONTHS.get(m.group(1))
            if not month:
                return None
            day = int(m.group(2))
            year = int(m.group(3))
        else:
            return None
    else:
        day = int(m.group(1))
        token = m.group(2)
        month = MONTHS.get(token) or MONTHS.get(token[:3]) or MONTHS.get(token[:4])
        year = int(m.group(3))
    if not month or not (1 <= day <= 31) or not (2015 <= year <= 2100):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


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
        ("se connecter", "page de connexion eBay"),
    ]:
        if marker in lower:
            print(f"  → Signal: {meaning}")
            return meaning
    return None


def fetch_url_filtered(session, url, label, card):
    """Fetch + 3 filtres. Renvoie (ventes, erreur). Une vente = {price, date, title}."""
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
            if r.status_code in (403, 429, 503):
                wait = 3 ** attempt + random.uniform(0, 2)
                print(f"  HTTP {r.status_code}, retry dans {wait:.1f}s ({attempt}/3)")
                time.sleep(wait)
                continue
            print(f"  HTTP {r.status_code} inattendu, abandon")
            return [], f"HTTP {r.status_code}"
        except requests.RequestException as e:
            wait = 3 ** attempt
            print(f"  ERREUR {e}, retry dans {wait}s ({attempt}/3)")
            time.sleep(wait)

    if r is None or r.status_code != 200:
        code = r.status_code if r is not None else "aucun"
        return [], f"HTTP {code}, prix conservé"

    print(f"  HTTP {r.status_code}, {len(r.content)} bytes")

    soup = BeautifulSoup(r.text, "html.parser")
    items, used_sel = extract_items(soup)
    if not items:
        print("  0 items trouvés")
        meaning = diagnose(soup, r.text)
        return [], meaning or "aucun résultat, prix conservé"
    print(f"  {len(items)} items via '{used_sel}'")

    mc = card["must_contain"]
    mmo = card.get("must_match_one", [])
    pmin = card["price_min"]
    pmax = card["price_max"]

    sales = []
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

        if not title_matches_card(title, mc, mmo):
            rejected_title += 1
            if len(title_examples) < 3:
                title_examples.append(title[:80])
            continue

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

        date_el = (
            item.select_one(".s-item__caption--signal")
            or item.select_one(".s-item__caption")
            or item.select_one(".s-item__title--tag")
            or item.select_one(".POSITIVE")
        )
        date_text = date_el.get_text(" ", strip=True) if date_el else ""
        if not parse_sold_date(date_text):
            blob = item.get_text(" ", strip=True)
            if re.search(r"vendu|sold", blob, re.I):
                date_text = blob
        sales.append({
            "price": price,
            "date": parse_sold_date(date_text),
            "title": title[:140],
        })
        if len(sales) >= MAX_VALID_RESULTS:
            break

    print(
        f"  → scannés:{scanned} | rejetés titre:{rejected_title} | "
        f"rejetés prix:{rejected_price} | conservés:{len(sales)} (range {pmin}-{pmax}€)"
    )
    if title_examples:
        print("  Rejetés (titre):")
        for ex in title_examples:
            print(f"    × {ex}")
    if price_examples:
        print("  Rejetés (prix hors range):")
        for ex in price_examples:
            print(f"    × {ex}")

    if not sales:
        return [], "aucune vente dans la fourchette, prix conservé"
    return sales, None


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


def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return default


def sale_signature(sale):
    title = normalize(sale.get("title") or "")[:48]
    date = sale.get("date") or ""
    price = int(round(sale["price"]))
    return f"{date}|{price}|{title}"


def append_snapshot(entry, hist_key, dated_key, price, today):
    dated = list(entry.get(dated_key) or [])
    if dated and dated[-1].get("d") == today:
        dated[-1]["p"] = int(price)
    else:
        dated.append({"d": today, "p": int(price)})
    entry[dated_key] = dated[-MAX_HISTORY:]
    entry[hist_key] = [pt["p"] for pt in entry[dated_key]]


def apply_market(entry, market, sales, now_iso, empty_reason):
    """Met à jour un marché sans jamais écraser un bon prix par 0 ou par un échec."""
    price_key = f"price_{market}"
    hist_key = f"history_{market}"
    dated_key = f"history_{market}_dated"
    sales_key = f"sales_{market}"
    count_key = f"sales_count_{market}"
    status_key = f"source_{market}"
    today = now_iso[:10]
    old_raw = entry.get(price_key)
    old_price = old_raw if isinstance(old_raw, (int, float)) and old_raw > 0 else None
    result = {
        "ok": False,
        "kept": True,
        "old_price": old_price,
        "new_price": old_price,
        "fresh": [],
        "detail": empty_reason or "prix conservé",
    }

    def keep(detail):
        entry[status_key] = {
            "ok": False,
            "kept_previous": True,
            "detail": detail,
            "checked_at": now_iso,
        }
        result["detail"] = detail
        return result

    if not sales:
        return keep(empty_reason or "aucune vente exploitable, prix conservé")

    prices = [s["price"] for s in sales if isinstance(s.get("price"), (int, float)) and s["price"] > 0]
    median = robust_median(prices)
    if median is None:
        return keep("médiane invalide, prix conservé")
    median = int(round(median))
    if median <= 0:
        return keep("prix nul rejeté, ancien prix conservé")

    old_sales = entry.get(sales_key) or []
    had_sales = isinstance(old_sales, list) and len(old_sales) > 0
    old_keys = {sale_signature(s) for s in old_sales} if had_sales else set()
    new_keys = {sale_signature(s) for s in sales}
    fresh = [s for s in sales if sale_signature(s) not in old_keys] if had_sales else []
    same = had_sales and new_keys == old_keys

    entry[sales_key] = [
        {
            "price": int(round(s["price"])),
            "date": s.get("date"),
            "title": (s.get("title") or "")[:140],
        }
        for s in sales[:MAX_SALES_STORED]
    ]
    entry[count_key] = len(sales)

    if same and old_price:
        detail = "aucune nouvelle vente, dernier prix conservé"
        entry[status_key] = {
            "ok": True,
            "kept_previous": True,
            "detail": detail,
            "checked_at": now_iso,
        }
        result.update(ok=True, kept=True, new_price=old_price, fresh=[], detail=detail)
        return result

    entry[price_key] = median
    append_snapshot(entry, hist_key, dated_key, median, today)
    if market == "eu":
        entry["price"] = median
        entry["history"] = list(entry.get(hist_key) or [])
        entry["sales_count"] = len(sales)
    detail = "référence initiale des ventes" if not had_sales else "nouvelles ventes intégrées"
    entry[status_key] = {
        "ok": True,
        "kept_previous": False,
        "detail": detail,
        "checked_at": now_iso,
    }
    result.update(
        ok=True,
        kept=False,
        new_price=median,
        fresh=[] if not had_sales else fresh,
        detail=detail,
    )
    return result


def positive_int(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    n = int(round(value))
    return n if n > 0 else None


def threshold_alerts(card_name, cid, market, old_price, new_price, vault_card, alert_log, now_iso):
    alerts = []
    if old_price is None or new_price is None or old_price == new_price:
        return alerts
    label = "Europe" if market == "eu" else "Monde"
    checks = (
        ("below", "alert_below", "sous", lambda old, new, t: old >= t > new),
        ("above", "alert_above", "au-dessus de", lambda old, new, t: old <= t < new),
    )
    for kind, field, word, crossed in checks:
        threshold = positive_int(vault_card.get(field))
        if not threshold:
            continue
        key = f"{cid}:{market}:{kind}:{threshold}"
        if crossed(old_price, new_price, threshold):
            if alert_log.get(key) != new_price:
                alerts.append({
                    "key": key,
                    "title": f"[Vault] {card_name} — {label} {word} {threshold} €",
                    "body": (
                        f"La cote PSA 10 **{label}** de **{card_name}** est passée "
                        f"de {int(old_price)} € à {int(new_price)} € "
                        f"et a franchi le seuil de {threshold} €.\n\n"
                        f"Réglage : `vault.json` → `{field}`.\n\n"
                        f"Collection : https://cgform-source.github.io/Poke/\n"
                    ),
                })
                alert_log[key] = new_price
        elif kind == "below" and new_price >= threshold and key in alert_log:
            del alert_log[key]
        elif kind == "above" and new_price <= threshold and key in alert_log:
            del alert_log[key]
    return alerts


def sale_alerts(card_name, cid, market, fresh, alert_log, now_iso):
    alerts = []
    label = "Europe" if market == "eu" else "Monde"
    for sale in fresh:
        key = f"{cid}:{market}:sale:{sale_signature(sale)}"
        if key in alert_log:
            continue
        when = sale.get("date") or "date non indiquée par eBay"
        alerts.append({
            "key": key,
            "title": f"[Vault] {card_name} — nouvelle vente {label} {int(round(sale['price']))} €",
            "body": (
                f"Nouvelle vente relevée pour **{card_name}** ({label}).\n\n"
                f"- Prix : {int(round(sale['price']))} €\n"
                f"- Date : {when}\n"
                f"- Titre : {sale.get('title') or '—'}\n\n"
                f"Collection : https://cgform-source.github.io/Poke/\n"
            ),
        })
        alert_log[key] = now_iso
    return alerts


def github_json(method, url, payload=None):
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        return None
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "papou-vault-prices")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            body = response.read().decode()
            return response.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()[:400]
        print(f"  GitHub HTTP {exc.code}: {detail}")
        return exc.code, detail


def publish_alerts(alerts):
    repo = os.environ.get("GITHUB_REPOSITORY")
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not alerts:
        return
    if not token or not repo:
        print(f"{len(alerts)} alerte(s) non envoyée(s) : pas de GITHUB_TOKEN (normal hors Actions).")
        for alert in alerts:
            print(f"  · {alert['title']}")
        return
    existing = set()
    listed = github_json(
        "GET",
        f"https://api.github.com/repos/{repo}/issues?state=open&per_page=50",
    )
    if listed and isinstance(listed[1], list):
        existing = {item.get("title") for item in listed[1]}
    for alert in alerts:
        if alert["title"] in existing:
            print(f"  issue déjà ouverte : {alert['title']}")
            continue
        body = alert["body"] + (
            "\n---\nPour recevoir ces alertes : sur GitHub, **Watch** → Custom → "
            "**Issues**, avec les notifications e-mail activées, ou l'application GitHub."
        )
        created = github_json(
            "POST",
            f"https://api.github.com/repos/{repo}/issues",
            {"title": alert["title"], "body": body, "labels": ["alerte-vault"]},
        )
        if created and created[0] == 422:
            created = github_json(
                "POST",
                f"https://api.github.com/repos/{repo}/issues",
                {"title": alert["title"], "body": body},
            )
        if created and created[0] in (200, 201):
            print(f"  issue ouverte : {alert['title']}")
        else:
            print(f"  échec issue : {alert['title']}")


def blocked(html, status):
    if status != 200:
        return True
    low = html.lower()
    return any(
        marker in low
        for marker in ("just a moment", "cf-challenge", "challenge-platform", "cf-mitigated")
    )


def parse_population(html):
    patterns = (
        r'"grade"\s*:\s*"?10"?.{0,160}?"population"\s*:\s*"?(\d+)"?',
        r'"population"\s*:\s*"?(\d+)"?.{0,160}?"grade"\s*:\s*"?10"?',
        r'GEM[\s-]*MT[^0-9]{0,40}(\d{1,7})',
    )
    for pattern in patterns:
        match = re.search(pattern, html, re.I | re.S)
        if not match:
            continue
        count = int(match.group(1))
        if 1 <= count <= 500000:
            return count
    return None


def fetch_population(cert):
    if not cert:
        return None, "certificat absent"
    url = f"https://www.psacard.com/cert/{cert}/psa"
    try:
        response = requests.get(url, headers=BROWSER_HEADERS, timeout=25)
    except requests.RequestException as exc:
        return None, f"PSA indisponible ({exc.__class__.__name__}), saisie manuelle"
    if blocked(response.text, response.status_code):
        return None, f"page PSA illisible (HTTP {response.status_code}), saisie manuelle"
    count = parse_population(response.text)
    if count:
        return count, None
    return None, "population introuvable sur la fiche PSA, saisie manuelle"


def dig_price(node):
    if isinstance(node, dict):
        if "price" in node and not isinstance(node["price"], (dict, list)):
            try:
                value = float(str(node["price"]).replace(",", "."))
                if value > 0:
                    return value
            except ValueError:
                pass
        for key in ("offers", "lowPrice"):
            if key in node:
                found = dig_price(node[key])
                if found:
                    return found
        for value in node.values():
            found = dig_price(value)
            if found:
                return found
    elif isinstance(node, list):
        for value in node:
            found = dig_price(value)
            if found:
                return found
    return None


# Pays vendeurs européens, identifiants publics Cardmarket (filtre sellerCountry).
EU_SELLER_COUNTRIES = (
    1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20,
    21, 22, 23, 24, 25, 26, 27, 28, 30, 31, 35, 37,
)
GRADED_RE = re.compile(
    r"\b(psa|bgs|cgc|sgc|pca|cga|graad|graded|gradee|gradée|gem\s*mt|beckett)\b",
    re.I,
)


def cardmarket_loose_url(url):
    """Fiche produit filtrée : japonais, vendeurs européens. Pas de contournement."""
    parts = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qs(parts.query, keep_blank_values=True)
    query["language"] = ["7"]
    query["sellerCountry"] = [str(code) for code in EU_SELLER_COUNTRIES]
    pairs = []
    for key, values in query.items():
        for value in values:
            pairs.append((key, value))
    return urllib.parse.urlunsplit((
        parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(pairs), ""
    ))


def parse_euro_amount(text):
    if not text:
        return None
    raw = text.replace("\xa0", " ").replace(" ", "")
    match = re.search(r"(\d{1,3}(?:\.\d{3})+,\d{2}|\d+,\d{2}|\d+\.\d{2})", raw)
    if not match:
        return None
    token = match.group(1)
    if "," in token:
        token = token.replace(".", "").replace(",", ".")
    try:
        value = float(token)
    except ValueError:
        return None
    return value if value > 0 else None


def cheapest_loose_price(html):
    """Offre la moins chère dont le texte ne mentionne pas une carte gradée."""
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select(".article-row, div[id^='articleRow'], [class*='article-row']")
    found = []
    for row in rows:
        if GRADED_RE.search(row.get_text(" ", strip=True)):
            continue
        price_el = (
            row.select_one(".price-container .color-primary")
            or row.select_one(".price-container")
            or row.select_one("[class*='price']")
        )
        if not price_el:
            continue
        amount = parse_euro_amount(price_el.get_text(" ", strip=True))
        if amount:
            found.append(amount)
    if not found:
        return None
    return round(min(found), 2)


def fetch_cardmarket(url):
    """Prix loose le moins cher d'un vendeur européen. Cloudflare n'est pas contourné."""
    if not url:
        return None, "Cardmarket indisponible"
    target = cardmarket_loose_url(url)
    headers = dict(BROWSER_HEADERS)
    headers["Accept-Language"] = "fr-FR,fr;q=0.9,en;q=0.8"
    headers["Referer"] = "https://www.cardmarket.com/fr/Pokemon"
    print(f"  [CM] GET {target[:160]}...")
    try:
        response = requests.get(target, headers=headers, timeout=25)
    except requests.RequestException as exc:
        return None, f"Cardmarket indisponible ({exc.__class__.__name__})"
    if blocked(response.text, response.status_code):
        return None, "Cardmarket indisponible"
    price = cheapest_loose_price(response.text)
    if price:
        return price, None
    return None, "Cardmarket indisponible"


def apply_population(entry, fetched, error, manual):
    if isinstance(fetched, int) and fetched > 0:
        entry["population"] = fetched
        entry["population_source"] = "psa"
        entry["population_error"] = None
        return True
    if (
        isinstance(entry.get("population"), int)
        and entry["population"] > 0
        and entry.get("population_source") == "psa"
    ):
        entry["population_error"] = error
        return False
    manual_n = positive_int(manual)
    if manual_n:
        entry["population"] = manual_n
        entry["population_source"] = "manuel"
        entry["population_error"] = error
        return False
    if isinstance(entry.get("population"), int) and entry["population"] > 0:
        entry["population_error"] = error
        return False
    entry["population"] = None
    entry["population_source"] = None
    entry["population_error"] = error
    return False


def positive_amount(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    amount = round(float(value), 2)
    return amount if amount > 0 else None


def apply_cardmarket(entry, auto_price, error, manual):
    manual_n = positive_amount(manual)
    if manual_n:
        entry["price_cm"] = manual_n
        entry["price_cm_source"] = "manuel"
        entry["price_cm_error"] = error
        return False
    if isinstance(auto_price, (int, float)) and auto_price > 0:
        entry["price_cm"] = round(float(auto_price), 2)
        entry["price_cm_source"] = "loose"
        entry["price_cm_note"] = "Carte non gradée, offre la moins chère d'un vendeur européen."
        entry["price_cm_error"] = None
        return True
    if isinstance(entry.get("price_cm"), (int, float)) and entry["price_cm"] > 0:
        entry["price_cm_error"] = error
        return False
    entry["price_cm"] = None
    entry["price_cm_source"] = None
    entry["price_cm_error"] = error
    return False


def cache_image(card):
    url = card.get("image")
    if not url:
        return False
    os.makedirs("images", exist_ok=True)
    dest = os.path.join("images", card["id"] + ".webp")
    if os.path.exists(dest) and os.path.getsize(dest) > 2000:
        print(f"  image déjà en cache {dest}")
        return True
    headers = dict(BROWSER_HEADERS)
    headers["Accept"] = "image/avif,image/webp,image/*,*/*"
    headers["Sec-Fetch-Dest"] = "image"
    if card.get("cert"):
        headers["Referer"] = f"https://www.psacard.com/cert/{card['cert']}/psa"
    try:
        response = requests.get(url, headers=headers, timeout=25)
    except requests.RequestException as exc:
        print(f"  image {card['id']}: {exc.__class__.__name__}")
        return False
    ctype = (response.headers.get("content-type") or "").lower()
    if response.status_code != 200 or "html" in ctype or response.content[:1] == b"<":
        print(f"  image {card['id']} non récupérée (HTTP {response.status_code}, {ctype or 'type inconnu'})")
        return False
    try:
        from PIL import Image

        image = Image.open(io.BytesIO(response.content))
        image = image.convert("RGB")
        image.thumbnail((900, 1300))
        image.save(dest, "WEBP", quality=80, method=4)
        print(f"  image {dest} ({os.path.getsize(dest)} o)")
        return True
    except Exception as exc:
        print(f"  image {card['id']} illisible ({exc.__class__.__name__})")
        return False


def wishlist_card(item):
    return {
        "id": item["id"],
        "name": item.get("name") or item["id"],
        "url_eu": item.get("url_eu") or "",
        "url_ww": item.get("url_ww") or "",
        "must_contain": item.get("must_contain") or ["psa 10"],
        "must_match_one": item.get("must_match_one") or [],
        "price_min": item.get("price_min") or 20,
        "price_max": item.get("price_max") or 20000,
    }


def run_selftest():
    assert parse_sold_date("Vendu le 12 oct. 2026") == "2026-10-12"
    assert parse_sold_date("Sold Oct 3, 2026") == "2026-10-03"
    assert parse_sold_date("rien") is None
    assert parse_price("0,00 EUR", 10, 100) is None
    assert title_matches_card("PSA 10 Charizard V 307/190 Shiny Star", ["psa 10", "charizard", "307"], ["shiny star"])

    entry = {"price_eu": 265, "history_eu": [255, 265], "history_eu_dated": [{"d": "2026-10-01", "p": 255}, {"d": "2026-10-12", "p": 265}]}
    kept = apply_market(entry, "eu", [], "2026-10-17T06:15:00+00:00", "HTTP 403, prix conservé")
    assert kept["ok"] is False and entry["price_eu"] == 265 and entry["history_eu"] == [255, 265]

    zero = apply_market(entry, "eu", [{"price": 0, "date": None, "title": "x"}], "2026-10-17T06:15:00+00:00", "")
    assert zero["ok"] is False and entry["price_eu"] == 265

    first = {"price_eu": 265, "history_eu_dated": [{"d": "2026-10-12", "p": 265}]}
    seeded = apply_market(
        first,
        "eu",
        [{"price": 270, "date": "2026-10-16", "title": "PSA 10 Charizard"}],
        "2026-10-17T06:15:00+00:00",
        "",
    )
    assert seeded["fresh"] == [] and first["price_eu"] == 270
    assert first["history_eu_dated"][-1] == {"d": "2026-10-17", "p": 270}

    again = apply_market(
        first,
        "eu",
        [{"price": 270, "date": "2026-10-16", "title": "PSA 10 Charizard"}],
        "2026-10-18T06:15:00+00:00",
        "",
    )
    assert again["kept"] is True and again["fresh"] == []
    assert first["price_eu"] == 270
    assert first["history_eu_dated"][-1]["d"] == "2026-10-17"

    moved = apply_market(
        first,
        "eu",
        [
            {"price": 270, "date": "2026-10-16", "title": "PSA 10 Charizard"},
            {"price": 250, "date": "2026-10-18", "title": "PSA 10 Charizard new"},
        ],
        "2026-10-18T06:15:00+00:00",
        "",
    )
    assert moved["fresh"] and moved["new_price"] == 260
    assert first["price_eu"] == 260

    log = {}
    alerts = threshold_alerts("Dracaufeu V", "charizard-v-ssv", "eu", 265, 240, {"alert_below": 250}, log, "2026-10-18T00:00:00+00:00")
    assert len(alerts) == 1 and "sous 250" in alerts[0]["title"]
    assert threshold_alerts("Dracaufeu V", "charizard-v-ssv", "eu", 240, 230, {"alert_below": 250}, log, "2026-10-19T00:00:00+00:00") == []
    assert parse_population('{"grade":"10","population":1234}') == 1234
    assert parse_population("<html>Just a moment") is None
    sample = cardmarket_loose_url("https://www.cardmarket.com/fr/Pokemon/Products/Singles/X?language=1")
    assert "language=7" in sample and "sellerCountry=12" in sample and "sellerCountry=7" in sample
    html = """
    <div class="article-row"><span class="price-container"><span class="color-primary">80,00 €</span></span> PSA 10</div>
    <div class="article-row"><span class="price-container"><span class="color-primary">9,00 €</span></span> EX</div>
    <div class="article-row"><span class="price-container"><span class="color-primary">4,50 €</span></span> Near Mint</div>
    """
    assert cheapest_loose_price(html) == 4.5
    assert cheapest_loose_price('<div class="article-row"><span class="price-container">12,00 €</span> BGS 10</div>') is None
    assert blocked("<html>Just a moment", 403)
    print("selftest OK")


def main():
    path = "prices.json"
    data = load_json(path, {"last_update": None, "cards": {}})
    vault = load_json("vault.json", {"cards": {}, "wishlist": []})
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    alert_log = data.setdefault("alert_log", {})
    alerts = []

    print(f"=== PAPOU VAULT update @ {now} ===")
    print(f"=== Source eBay: {BASE_URL} | quotidien | prix conservé si échec ===\n")

    session = requests.Session()
    if not warm_up(session):
        print("Warm-up échoué, on tente quand même\n")

    ebay_ok = 0
    ebay_fail = 0
    for i, card in enumerate(CARDS, 1):
        cid = card["id"]
        print(f"\n[{cid}] ({i}/{len(CARDS)})")
        print(f"  Filtre: contient={card['must_contain']} | un_de={card['must_match_one']}")
        print(f"  Range prix: {card['price_min']}-{card['price_max']}€")
        entry = data["cards"].get(cid, {})
        vault_card = (vault.get("cards") or {}).get(cid, {})

        for market, url in (("eu", card["url_eu"]), ("ww", card["url_ww"])):
            label = "EU" if market == "eu" else "WW"
            print(f"  {'🇪🇺' if market == 'eu' else '🌎'} marché {label}")
            try:
                sales, error = fetch_url_filtered(session, url, label, card)
                result = apply_market(entry, market, sales, now, error)
            except Exception as exc:
                print(f"    ERREUR {label}: {exc}")
                result = apply_market(entry, market, [], now, f"erreur interne, prix conservé")
            if result["ok"]:
                ebay_ok += 1
                print(f"    ✓ {result['detail']} → {result['new_price']}€")
            else:
                ebay_fail += 1
                print(f"    ⚠ {result['detail']}")
            alerts.extend(threshold_alerts(
                card["name"], cid, market, result["old_price"], result["new_price"], vault_card, alert_log, now
            ))
            alerts.extend(sale_alerts(card["name"], cid, market, result["fresh"], alert_log, now))
            if market == "eu":
                time.sleep(random.uniform(6, 11))

        try:
            fetched, pop_error = fetch_population(card["cert"])
        except Exception as exc:
            fetched, pop_error = None, f"PSA erreur ({exc.__class__.__name__}), saisie manuelle"
        apply_population(entry, fetched, pop_error, vault_card.get("population"))
        print(f"  population: {entry.get('population')} ({entry.get('population_source') or pop_error})")

        try:
            cm_price, cm_error = fetch_cardmarket(card.get("cardmarket_url"))
        except Exception as exc:
            cm_price, cm_error = None, f"Cardmarket erreur ({exc.__class__.__name__}), saisie manuelle"
        apply_cardmarket(entry, cm_price, cm_error, vault_card.get("price_cm"))
        print(f"  cardmarket: {entry.get('price_cm')} ({entry.get('price_cm_source') or cm_error})")

        entry["last_update"] = now
        data["cards"][cid] = entry

        if i < len(CARDS):
            delay = random.uniform(8, 14)
            print(f"  ... pause {delay:.1f}s avant carte suivante")
            time.sleep(delay)

    print("\n=== Liste de souhaits ===")
    wish_out = data.get("wishlist") if isinstance(data.get("wishlist"), dict) else {}
    for item in vault.get("wishlist") or []:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        wid = item["id"]
        print(f"\n[souhait {wid}]")
        spec = wishlist_card(item)
        record = wish_out.get(wid, {})
        record["name"] = item.get("name") or wid
        record["target_price"] = positive_int(item.get("target_price"))
        for market, url_key in (("eu", "url_eu"), ("ww", "url_ww")):
            url = spec[url_key]
            if not url:
                apply_market(record, market, [], now, "lien eBay manquant")
                continue
            try:
                sales, error = fetch_url_filtered(session, url, market.upper(), spec)
                result = apply_market(record, market, sales, now, error)
            except Exception as exc:
                result = apply_market(record, market, [], now, f"erreur, prix conservé ({exc.__class__.__name__})")
            print(f"  {market}: {result['detail']} → {result['new_price']}")
            time.sleep(random.uniform(4, 8))
        prices = [
            record.get("price_eu") if isinstance(record.get("price_eu"), (int, float)) else None,
            record.get("price_ww") if isinstance(record.get("price_ww"), (int, float)) else None,
        ]
        known = [p for p in prices if p and p > 0]
        target = record.get("target_price")
        if target and known and min(known) <= target:
            key = f"wish:{wid}:under:{target}"
            if key not in alert_log:
                best = int(min(known))
                alerts.append({
                    "key": key,
                    "title": f"[Vault] Bonne affaire — {record['name']} à {best} €",
                    "body": (
                        f"**{record['name']}** est à {best} €, sous le plafond de {target} € "
                        f"défini dans `vault.json`.\n\n"
                        f"Collection : https://cgform-source.github.io/Poke/\n"
                    ),
                })
                alert_log[key] = best
        elif target and known and min(known) > target:
            alert_log.pop(f"wish:{wid}:under:{target}", None)
        wish_out[wid] = record
    data["wishlist"] = wish_out

    psa_ok = any(
        (data["cards"].get(c["id"]) or {}).get("population_source") == "psa" for c in CARDS
    )
    cm_ok = any(
        (data["cards"].get(c["id"]) or {}).get("price_cm_source") == "loose"
        and not (data["cards"].get(c["id"]) or {}).get("price_cm_error")
        for c in CARDS
    )
    data["sources"] = {
        "ebay": {
            "ok": ebay_ok > 0,
            "checked_at": now,
            "detail": (
                f"{ebay_ok} marché(s) lu(s), {ebay_fail} conservé(s) sans nouveau prix."
                if ebay_ok
                else "eBay illisible sur ce run : tous les derniers prix sont conservés."
            ),
        },
        "cardmarket": {
            "ok": cm_ok,
            "checked_at": now,
            "detail": (
                "Prix loose le moins cher chez un vendeur européen."
                if cm_ok
                else "Cardmarket indisponible. Saisie manuelle du prix loose (carte non gradée, vendeur européen)."
            ),
        },
        "psa": {
            "ok": psa_ok,
            "checked_at": now,
            "detail": (
                "Population PSA 10 lue sur la fiche certificat."
                if psa_ok
                else "Population non lue. Saisie manuelle dans vault.json ou dans l'interface."
            ),
        },
    }
    if ebay_ok:
        data["last_success"] = now
    elif not data.get("last_success"):
        data["last_success"] = data.get("last_update")
    data["last_update"] = now
    data["alert_log"] = alert_log

    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print(f"\n✓ {path} écrit — eBay {ebay_ok}/{ebay_ok + ebay_fail} marchés")

    print("\n=== Photos (cache local, échec non bloquant) ===")
    cached = 0
    for card in CARDS:
        try:
            if cache_image(card):
                cached += 1
        except Exception as exc:
            print(f"  image {card['id']}: {exc}")
    print(f"images en cache: {cached}/{len(CARDS)} (sinon le site garde le hotlink PSA)")

    print(f"\n=== Alertes: {len(alerts)} ===")
    publish_alerts(alerts)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        run_selftest()
    else:
        main()
