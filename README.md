# PKMN // VAULT

Dashboard auto-updated qui track la cote PSA 10 de ma collection Pokémon.
Scraping eBay.fr chaque lundi → médiane robuste → graphique sur 11 semaines.

## 📦 Structure du repo

```
├── index.html                    # dashboard (GitHub Pages)
├── prices.json                   # données prix + historique (updated par l'action)
├── scripts/
│   └── update_prices.py          # scraper eBay.fr
└── .github/workflows/
    └── update.yml                # GitHub Action (lundi 8h UTC)
```

## 🚀 Setup en 5 étapes

1. **Crée un repo public** sur GitHub (ex: `pkmn-vault`)
2. **Upload les 4 fichiers** (respecte l'arborescence)
3. **Settings → Pages** → Source: `main` / `root` → Save
   → ton dashboard sera live à `https://<ton-user>.github.io/pkmn-vault`
4. **Settings → Actions → General** → Workflow permissions : coche `Read and write permissions` → Save
   (obligatoire pour que l'action puisse commiter `prices.json`)
5. **Onglet Actions** → `Update prices` → `Run workflow` pour lancer une première MAJ manuelle

## 🔄 Comment ça tourne

- **Chaque lundi 8h UTC**, l'action GitHub démarre automatiquement
- Elle scrape eBay.fr pour chaque carte (recherche `PSA 10 + nom + numéro`, ventes complétées)
- Calcule la **médiane robuste** sur les 30 dernières ventes (exclut les outliers ±2σ)
- Ajoute 1 point dans `history` et retire le plus ancien (rolling 11 semaines)
- Commit `prices.json` si changement détecté
- Le dashboard fetch `prices.json` à chaque chargement → prix toujours à jour

## 🕒 Transition historique fabriqué → réel

Le `prices.json` initial contient des valeurs estimées pour que le graphique soit pas vide au démarrage.
À chaque passage hebdo de l'action, **1 faux point est remplacé par 1 vrai point**.
Après **11 semaines**, 100% des données affichées sont du scraping réel.

## 🛠 Customisation

- **Ajouter/retirer une carte** : éditer la constante `CARDS` dans `index.html` (pour l'affichage) ET dans `scripts/update_prices.py` (pour le scraping). L'`id` doit matcher entre les deux.
- **Changer la fréquence** : éditer `cron: '0 8 * * 1'` dans `.github/workflows/update.yml`
  ([syntaxe cron](https://crontab.guru/))
- **Modifier les requêtes eBay** : éditer `query` dans `scripts/update_prices.py`
- **Lancer manuellement** : onglet Actions → Update prices → Run workflow

## 🔒 Mode édition manuel

Le bouton `✎ Mode édition` dans le dashboard permet d'overrider localement :
- **Prix** : écrase le prix du `prices.json` (sauvegardé dans localStorage, uniquement sur ton navigateur)
- **Image** : colle l'URL d'une photo de ton choix

Les overrides sont privés à ton navigateur (pas partagés avec les visiteurs).

## ⚠️ Bon à savoir

- Si eBay bloque le scraper (rare mais possible), l'action garde les anciennes valeurs et loggue l'erreur dans l'onglet Actions
- Le dashboard est **public** par défaut — n'importe qui avec l'URL voit tes prix
- GitHub Actions gratuit = 2000 min/mois sur les repos privés. Repo public = illimité.
