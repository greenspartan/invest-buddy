# Invest Buddy

## Stack
- Backend: Python FastAPI (app/main.py)
- Frontend: Streamlit (app/streamlit_app.py)
- Database: PostgreSQL via Docker Compose
- Prix: yfinance (Yahoo Finance)

## Commandes
- Lancer Postgres: `docker compose up -d`
- Lancer API: `uvicorn app.main:app --reload`
- Lancer UI: `streamlit run app/streamlit_app.py`
- Installer deps: `pip install -r requirements.txt`

## Architecture
- Les positions sont definies dans `portfolio.yaml` (pas en DB directement)
- L'API lit le YAML, enrichit avec les prix Yahoo, persiste en DB, retourne le JSON
- Streamlit appelle GET /portfolio et affiche les donnees (lecture seule)

## Conventions
- Python 3.9+
- SQLAlchemy pour l'ORM
- Pas de saisie cote Streamlit (affichage uniquement)
