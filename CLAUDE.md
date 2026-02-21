# Invest Buddy

## Stack
- Backend: Python FastAPI (app/main.py)
- Frontend: Streamlit avec plotly (app/streamlit_app.py)
- Database: PostgreSQL via Docker Compose
- Prix: yfinance (Yahoo Finance) — prix live, historiques, holdings, secteurs, forex

## Commandes
- Lancer Postgres: `docker compose up -d`
- Lancer API: `uvicorn app.main:app` (sans --reload, voir bug ci-dessous)
- Lancer UI: `streamlit run app/streamlit_app.py`
- Installer deps: `pip install -r requirements.txt`

## Architecture
- Les positions initiales sont definies dans `portfolio.yaml`
- Les achats additionnels sont dans `transactions.yaml` (optionnel)
- Chaque position: ticker, qty, avg_price, currency, account, purchase_date
- Chaque transaction: ticker, account, qty, price, date
- `aggregate_positions()` fusionne positions + transactions → PRU auto-calcule
- Chaque achat (initial ou transaction) = un "lot" avec sa date et son prix
- L'API lit les 2 YAML, agrege, enrichit avec les prix Yahoo, persiste en DB, retourne le JSON
- `target_portfolio.yaml` definit les poids cibles du portefeuille (editable manuellement)
- `macro_outlook.yaml` est genere automatiquement par le backend (cache 6h, gitignore)
- `macro_config.yaml` definit les mega-trends, plans de relance et previsions sell-side (editable manuellement)
- Streamlit appelle les endpoints et affiche les donnees (lecture seule, 7 onglets)

## Modules Python (app/)
- `portfolio.py` — chargement YAML + transactions + agregation lots/PRU + enrichissement prix + conversion EUR
- `forex.py` — taux de change live via yfinance (cache en memoire)
- `holdings.py` — top holdings ETF + agregation ponderation effective
- `sectors.py` — exposition sectorielle GICS + agregation par ETF
- `performance.py` — perf historique (prix + forex historiques, P&L %, drawdown)
- `macro.py` — dashboard macro complet: 21 indicateurs (FRED/ECB/yfinance) + mega-trends + plans de relance + parser Lyn Alden + sell-side views + signaux sectoriels + scoring risk-on/risk-off + cache YAML
- `target.py` — allocation cible (target_portfolio.yaml) + calcul drift vs portefeuille live
- `models.py` — modele SQLAlchemy Position
- `database.py` — connexion PostgreSQL
- `config.py` — DATABASE_URL, PORTFOLIO_PATH, TRANSACTIONS_PATH, TARGET_PATH, BASE_CURRENCY, FRED_API_KEY, MACRO_CONFIG_PATH, LYN_ALDEN_DIR, SELL_SIDE_DIR

## Endpoints API
- GET /portfolio — positions enrichies + totaux par compte + total global
- GET /holdings/top?top_n=20 — top N positions sous-jacentes agreges
- GET /sectors — exposition sectorielle (11 secteurs GICS)
- GET /performance?period=ALL — perf historique (periodes: 1M, 3M, 6M, 1Y, YTD, ALL)
- GET /macro?refresh=false — dashboard macro complet: indicateurs (21), mega-trends (13), plans de relance (12), sell-side views (2), Lyn Alden insights (8), signaux sectoriels (11+) + outlook (cache YAML 6h, refresh=true force re-fetch)
- GET /target — allocation cible depuis target_portfolio.yaml
- GET /drift — drift portefeuille live vs allocation cible + suggestions rebalancement
- GET /health — health check

## Contexte Macro
- **Lyn Alden** : Les syntheses des articles premium sont dans `context/macro/Lyn Alden/`
  - Format: `YYMMDD_Titre_Court.md` (ex: `260215_Disrupted_Software_Stocks.md`)
  - Les PDFs source sont dans le meme dossier mais exclus du git (`context/**/*.pdf` dans .gitignore)
  - Parses automatiquement par macro.py (titre, points cles, mouvements portefeuille)
- **Sell-Side** : Les syntheses des rapports JPMorgan/BofA sont dans `context/macro/sell-side/`
  - Format libre `.md`, chargees dans macro_config.yaml (section sell_side_views)
- **macro_config.yaml** : fichier YAML editable manuellement contenant :
  - 13 mega-trends avec force (0-3), catalyseurs, ETFs associes
  - 12 plans de relance (5 US + 7 EU) avec statut, montants, secteurs
  - Previsions sell-side (JPMorgan, BofA) avec forecasts, themes, risques
  - Relu a chaque appel /macro (pas de restart necessaire)
- **Indicateurs FRED** (11) : CPI, Core CPI, Chomage, Fed Funds, Production Industrielle, Courbe de taux, Bilan Fed, Inscriptions chomage, Sentiment conso, Spread HY, PIB
- **Indicateurs yfinance** (8) : US 10Y, VIX, EUR/USD, DXY, Or, Bitcoin, Cuivre, Petrole WTI
- **Indicateurs ECB** (2) : Taux refi, IPC zone euro

## Configuration

- `.env` a la racine (gitignore) contient les variables d'environnement (DATABASE_URL, FRED_API_KEY, etc.)
- `python-dotenv` charge automatiquement le `.env` au demarrage (via config.py)
- `context/README.md` documente toutes les sources de donnees macro

## Conventions

- Python 3.13 (venv recree en fev 2026, voir bug Python 3.14 ci-dessous)
- SQLAlchemy pour l'ORM
- Modules autonomes (holdings, sectors, performance) sans dependances croisees
- Pas de saisie cote Streamlit (affichage uniquement)
- Devise de base: EUR (toutes les valeurs converties)
- Multi-devises: EUR, USD supportees (GBP, CHF, JPY prets)

## Notes
- Si on ajoute un champ au dict enrichi dans portfolio.py, penser a ajouter la colonne dans models.py (sinon 500 sur /portfolio)
- Apres modification de models.py, recréer les tables: `Base.metadata.drop_all(bind=engine); Base.metadata.create_all(bind=engine)`
- portfolio.yaml et transactions.yaml sont relus a chaque appel API (pas besoin de relancer)
- Les lots (`_lots`) sont un champ interne utilise par performance.py, pas persiste en DB
- macro.py et target.py n'utilisent PAS models.py/PostgreSQL (YAML cache pour macro, calcul a la volee pour target/drift)
- FRED API : le parametre `units=pc1` retourne directement le % de variation annuel (necessaire pour CPI qui est un index brut sinon)
- ECB Data Portal : utiliser `data-api.ecb.europa.eu` (l'ancien domaine `sdw-wsrest.ecb.europa.eu` ne fonctionne plus)
- macro_outlook.yaml est dans .gitignore (fichier cache genere)

## Bugs Connus / Historique Debug

### Bug uvicorn --reload bloque (fev 2026)

**Symptome**: `uvicorn app.main:app --reload` affiche "Started reloader process" mais le worker process ne demarre jamais. L'API ne repond pas. Sans `--reload`, tout fonctionne normalement.

**Contexte**: Apres un `brew upgrade`, le venv utilisait Python 3.14.3 (tres recent, potentiellement instable). Le reloader StatReload de uvicorn ne parvient pas a lancer le worker subprocess.

**Diagnostic**:
1. `docker compose ps` → Postgres OK, port 5432 mappe
2. `docker exec invest-buddy-postgres psql -U etf_user -d invest_buddy -c "SELECT 1"` → DB OK
3. `psycopg2.connect(...)` direct → OK
4. `from app.database import engine` → bloquait avec Python 3.14, OK apres nettoyage des zombies
5. `uvicorn --reload` → "Started reloader process" mais jamais "Started server process"
6. `uvicorn` (sans --reload) → "Started server process" + "Application startup complete" → OK

**Resolution**:
1. Venv recree avec Python 3.13: `python3.13 -m venv .venv`
2. Deps reinstallees: `.venv/bin/pip install -r requirements.txt`
3. Lancer sans --reload: `uvicorn app.main:app` (pas de `--reload`)
4. L'ancien venv Python 3.14 est sauvegarde dans `.venv-3.14-backup/` (peut etre supprime)

**Prevention**: Eviter Python 3.14 tant qu'il n'est pas marque stable. Utiliser Python 3.13 pour le venv.
