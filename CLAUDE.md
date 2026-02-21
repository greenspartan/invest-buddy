# Invest Buddy

## Stack
- Backend: Python FastAPI (app/main.py)
- Frontend: Streamlit avec plotly (app/streamlit_app.py)
- Database: PostgreSQL via Docker Compose
- Prix: yfinance (Yahoo Finance) — prix live, historiques, holdings, secteurs, forex

## Commandes
- Lancer Postgres: `docker compose up -d`
- Lancer API: `uvicorn app.main:app --reload`
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
- Streamlit appelle les endpoints et affiche les donnees (lecture seule, 7 onglets)

## Modules Python (app/)
- `portfolio.py` — chargement YAML + transactions + agregation lots/PRU + enrichissement prix + conversion EUR
- `forex.py` — taux de change live via yfinance (cache en memoire)
- `holdings.py` — top holdings ETF + agregation ponderation effective
- `sectors.py` — exposition sectorielle GICS + agregation par ETF
- `performance.py` — perf historique (prix + forex historiques, P&L %, drawdown)
- `macro.py` — indicateurs macro (FRED, ECB, yfinance) + scoring risk-on/risk-off + cache YAML
- `target.py` — allocation cible (target_portfolio.yaml) + calcul drift vs portefeuille live
- `models.py` — modele SQLAlchemy Position
- `database.py` — connexion PostgreSQL
- `config.py` — DATABASE_URL, PORTFOLIO_PATH, TRANSACTIONS_PATH, TARGET_PATH, BASE_CURRENCY, FRED_API_KEY

## Endpoints API
- GET /portfolio — positions enrichies + totaux par compte + total global
- GET /holdings/top?top_n=20 — top N positions sous-jacentes agreges
- GET /sectors — exposition sectorielle (11 secteurs GICS)
- GET /performance?period=ALL — perf historique (periodes: 1M, 3M, 6M, 1Y, YTD, ALL)
- GET /macro?refresh=false — indicateurs macro + outlook (cache YAML 6h, refresh=true force re-fetch)
- GET /target — allocation cible depuis target_portfolio.yaml
- GET /drift — drift portefeuille live vs allocation cible + suggestions rebalancement
- GET /health — health check

## Conventions
- Python 3.9+
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
