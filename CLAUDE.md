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
- Les positions sont definies dans `portfolio.yaml` (pas en DB directement)
- Chaque position: ticker, qty, avg_price, currency, account, purchase_date
- L'API lit le YAML, enrichit avec les prix Yahoo, persiste en DB, retourne le JSON
- Streamlit appelle les endpoints et affiche les donnees (lecture seule, 4 onglets)

## Modules Python (app/)
- `portfolio.py` — chargement YAML + enrichissement prix + conversion EUR
- `forex.py` — taux de change live via yfinance (cache en memoire)
- `holdings.py` — top holdings ETF + agregation ponderation effective
- `sectors.py` — exposition sectorielle GICS + agregation par ETF
- `performance.py` — perf historique (prix + forex historiques, P&L %, drawdown)
- `models.py` — modele SQLAlchemy Position
- `database.py` — connexion PostgreSQL
- `config.py` — DATABASE_URL, PORTFOLIO_PATH, BASE_CURRENCY

## Endpoints API
- GET /portfolio — positions enrichies + totaux par compte + total global
- GET /holdings/top?top_n=20 — top N positions sous-jacentes agreges
- GET /sectors — exposition sectorielle (11 secteurs GICS)
- GET /performance?period=ALL — perf historique (periodes: 1M, 3M, 6M, 1Y, YTD, ALL)
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
- portfolio.yaml est relu a chaque appel API (pas besoin de relancer)
