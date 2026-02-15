# Invest Buddy

Assistant personnel d'investissement — suivi de portefeuille (ETFs, actions), prix en temps reel, calcul de P&L et dashboard web.

---

## Comment ca marche (vue d'ensemble)

L'application est composee de **4 briques** qui communiquent entre elles :

```
portfolio.yaml          Tu definis tes positions ici (tickers, quantites, prix d'achat)
       |
       v
  FastAPI (backend)     Lit le YAML, recupere les prix live via Yahoo Finance,
       |                calcule les P&L, stocke en base de donnees
       |
       v
  PostgreSQL (DB)       Stocke les positions enrichies (sert de cache)
       |
       v
  Streamlit (frontend)  Appelle l'API et affiche un dashboard dans ton navigateur
```

### Chaque brique expliquee

| Brique | C'est quoi ? | Role dans le projet |
|--------|-------------|-------------------|
| **portfolio.yaml** | Un simple fichier texte structuree | Ta "source de verite" : tu y mets tes ETFs, quantites et prix d'achat |
| **FastAPI** | Un framework Python pour creer des APIs web | Le cerveau de l'app : il expose des URLs (endpoints) que d'autres programmes peuvent appeler pour recuperer des donnees en JSON |
| **yfinance** | Une librairie Python qui se connecte a Yahoo Finance | Recupere les prix actuels de tes ETFs automatiquement |
| **PostgreSQL** | Une base de donnees relationnelle | Stocke les positions enrichies (prix actuel, P&L). Tourne dans un container Docker |
| **Docker** | Un outil qui lance des applications dans des containers isoles | Permet de lancer PostgreSQL sans l'installer sur ton Mac. Un container = une mini-machine virtuelle legere |
| **Streamlit** | Un framework Python pour creer des dashboards web | Affiche tes positions, P&L et totaux dans une page web. Mode lecture seule |
| **Swagger UI** | Interface web auto-generee par FastAPI | Accessible sur `/docs`, permet de voir et tester tous les endpoints de l'API directement dans le navigateur. Utile pour le debug et la documentation |

### Le flux de donnees en detail

1. Tu edites `portfolio.yaml` pour ajouter/modifier tes positions
2. Quand tu (ou Streamlit) appelles `GET /portfolio` :
   - FastAPI lit le fichier YAML
   - Pour chaque ETF, il demande le prix actuel a Yahoo Finance via yfinance
   - Il calcule : valeur marche = prix actuel x quantite, P&L = valeur marche - cout d'achat
   - Il sauvegarde tout en PostgreSQL
   - Il retourne le JSON complet (positions + totaux par compte + total global)
3. Streamlit recoit ce JSON et l'affiche dans un tableau avec mise en forme (vert = gain, rouge = perte)
4. Quand tu (ou Streamlit) appelles `GET /holdings/top` :
   - Pour chaque ETF, il recupere les 10 premieres positions sous-jacentes via yfinance
   - Il calcule le poids effectif de chaque action : poids dans l'ETF x poids de l'ETF dans le portefeuille
   - Il agrege les actions presentes dans plusieurs ETFs (ex: Apple dans IWDA + VWCE)
   - Il retourne le top 20 classe par poids decroissant

---

## Structure du projet

```
.
├── app/
│   ├── main.py            # API FastAPI (endpoints /portfolio, /holdings/top, /health)
│   ├── streamlit_app.py   # Dashboard web Streamlit
│   ├── portfolio.py       # Chargement YAML + appel Yahoo Finance + calcul P&L
│   ├── holdings.py        # Fetch des top holdings ETF + calcul des poids effectifs
│   ├── models.py          # Modele de la table "positions" en base (SQLAlchemy ORM)
│   ├── database.py        # Connexion a PostgreSQL
│   └── config.py          # Configuration (lit le fichier .env)
├── portfolio.yaml         # Tes positions ETF (a personnaliser)
├── docker-compose.yml     # Configuration du container PostgreSQL
├── requirements.txt       # Dependances Python
├── .env                   # Variables d'environnement (URL de la DB, etc.)
└── .venv/                 # Environnement virtuel Python (pas dans git)
```

---

## Lancement rapide

### Pre-requis

- **Python 3.9+** installe sur ta machine
- **Docker Desktop** installe et lance (icone visible dans la barre de menu)

### 1. Lancer PostgreSQL

```bash
cd invest-buddy
docker compose up -d
```

> `up -d` lance le container en arriere-plan. Tu peux verifier dans Docker Desktop qu'il tourne.

### 2. Creer l'environnement Python et installer les dependances

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

> Le **venv** (virtual environment) isole les librairies de ce projet pour ne pas polluer ton systeme.
> Tu dois faire `source .venv/bin/activate` a chaque nouveau terminal.

### 3. Personnaliser ton portefeuille

Editer `portfolio.yaml` avec tes positions. Format :

```yaml
positions:
  - ticker: "IWDA.AS"       # Ticker Yahoo Finance
    qty: 50                  # Nombre de parts
    avg_price: 82.50         # Prix d'achat moyen
    account: "PEA"           # Compte (PEA, CTO, etc.)
```

> Pour trouver le bon ticker : cherche ton ETF sur [finance.yahoo.com](https://finance.yahoo.com/) et copie le symbole (ex: IWDA.AS pour Euronext Amsterdam).

### 4. Lancer l'API (terminal 1)

```bash
source .venv/bin/activate
uvicorn app.main:app --reload
```

> `--reload` : l'API redemarre automatiquement quand tu modifies le code. Pratique en dev.

URLs disponibles :
- **http://127.0.0.1:8000/portfolio** — Donnees JSON du portefeuille
- **http://127.0.0.1:8000/holdings/top** — Top 20 positions sous-jacentes
- **http://127.0.0.1:8000/docs** — Documentation interactive Swagger UI
- **http://127.0.0.1:8000/redoc** — Documentation alternative (ReDoc)

### 5. Lancer le dashboard Streamlit (terminal 2)

```bash
source .venv/bin/activate
streamlit run app/streamlit_app.py
```

> Ouvre ton navigateur sur **http://localhost:8501**

---

## Endpoints API

| Methode | URL | Description |
|---------|-----|-------------|
| GET | `/portfolio` | Retourne les positions enrichies avec prix live, P&L et totaux |
| GET | `/holdings/top` | Top 20 positions sous-jacentes du portefeuille (poids effectifs agreges) |
| GET | `/health` | Health check (`{"status": "ok"}`) |
| GET | `/docs` | Documentation Swagger UI (interface de test) |
| GET | `/redoc` | Documentation ReDoc (lecture seule) |

### Exemple de reponse `/portfolio`

```json
{
  "positions": [
    {
      "ticker": "IWDA.AS",
      "qty": 50,
      "avg_price": 82.5,
      "current_price": 112.28,
      "market_value": 5613.75,
      "pnl": 1488.75,
      "pnl_pct": 36.09,
      "account": "PEA"
    }
  ],
  "totals_by_account": {
    "PEA": { "cost_basis": 8913.0, "market_value": 12145.6, "pnl": 3232.6, "pnl_pct": 36.27 }
  },
  "total": { "cost_basis": 14295.0, "market_value": 19133.12, "pnl": 4838.12, "pnl_pct": 33.84 }
}
```

### Exemple de reponse `/holdings/top`

```json
{
  "top_holdings": [
    {
      "rank": 1,
      "symbol": "NVDA",
      "name": "NVIDIA Corp",
      "effective_weight_pct": 2.67,
      "etf_sources": ["IWDA.AS", "VWCE.DE"]
    }
  ],
  "meta": {
    "etfs_analyzed": ["IWDA.AS", "EIMI.MI", "VWCE.DE"],
    "etfs_no_data": ["PANX.PA", "ESE.PA"],
    "portfolio_coverage_pct": 74.46
  }
}
```

> **Note** : certains ETFs (ex: PANX.PA, ESE.PA) n'exposent pas leurs holdings via Yahoo Finance. Le champ `meta` indique quels ETFs ont ete analyses et le pourcentage du portefeuille couvert.

---

## Commandes utiles

| Action | Commande |
|--------|---------|
| Lancer PostgreSQL | `docker compose up -d` |
| Arreter PostgreSQL | `docker compose down` |
| Lancer l'API | `uvicorn app.main:app --reload` |
| Lancer le dashboard | `streamlit run app/streamlit_app.py` |
| Activer le venv | `source .venv/bin/activate` |
| Installer les deps | `pip install -r requirements.txt` |

---

## Roadmap

- [ ] Integration IBKR (positions temps reel depuis le broker)
- [ ] Frontend web (SvelteKit ou React) en remplacement de Streamlit
- [ ] Historique de performance (suivi de la valeur dans le temps)
- [ ] Alertes de prix (notification si un ETF passe un seuil)
- [ ] Graphiques de repartition (camembert par compte, par ETF)
