# Context — Sources de donnees pour Invest Buddy

Ce repertoire contient les documents de reference et analyses externes utilises par le dashboard macro.

## Structure

```
context/
├── ETF_Reporting_2026-02-11.md    # Reporting macro complet (modele de reference)
└── macro/
    ├── Lyn Alden/                  # Articles premium Lyn Alden
    │   ├── *.md                    # Syntheses structurees (parsees par macro.py)
    │   └── *.pdf                   # PDFs source (gitignore)
    └── sell-side/                  # Rapports sell-side (banques d'investissement)
        ├── JPMorgan_2026_Outlook.md
        └── BofA_2026_Outlook.md
```

## Sources

### Lyn Alden — Analyses Premium

Articles bi-mensuels de [Lyn Alden](https://www.lynalden.com/) couvrant la macro, la liquidite, les secteurs et le positionnement de portefeuille.

| Fichier | Date | Sujet |
|---------|------|-------|
| `251109_Liquidity_Shutdowns_Tariffs_Earnings.md` | 09/11/2025 | Liquidite, shutdowns, tarifs, earnings |
| `251123_AI_Hyperscalers.md` | 23/11/2025 | Analyse des hyperscalers IA |
| `251207_Pricing_Risk_Fairly.md` | 07/12/2025 | Pricing du risque |
| `251221_Fed_Structural_Shift.md` | 21/12/2025 | Shift structurel de la Fed |
| `260104_Energy_Sector_Update.md` | 04/01/2026 | Mise a jour secteur energie |
| `260118_Three_Notable_Breakouts.md` | 18/01/2026 | Trois breakouts notables |
| `260201_Boom_AI_Agents.md` | 01/02/2026 | Boom des agents IA |
| `260215_Disrupted_Software_Stocks.md` | 15/02/2026 | Stocks software perturbes |

**Format** : `YYMMDD_Titre_Court.md`

**Sections parsees par macro.py** :
- `# Titre` → titre de l'article
- `## Points Cles` → bullet points extraits automatiquement
- `## Mises a Jour du Portefeuille` → mouvements de portefeuille

**PDFs** : Les fichiers PDF source sont dans le meme repertoire mais exclus du git (`.gitignore` : `context/**/*.pdf`).

### Sell-Side — Rapports Banques d'Investissement

Syntheses structurees des outlooks annuels des grandes banques.

| Fichier | Source | Date | Contenu |
|---------|--------|------|---------|
| `JPMorgan_2026_Outlook.md` | JPMorgan | 09/12/2025 | Previsions macro, actions, taux, devises, commodites, themes, risques |
| `BofA_2026_Outlook.md` | BofA Global Research | 16/12/2025 | Previsions PIB, actions (S&P 7100), taux, themes (capex shift, EM), risques |

**Integration** : Les previsions cles sont extraites dans `macro_config.yaml` (section `sell_side_views`) et affichees dans l'onglet Macro de Streamlit.

### ETF Reporting

| Fichier | Date | Contenu |
|---------|------|---------|
| `ETF_Reporting_2026-02-11.md` | 11/02/2026 | Reporting complet : macro, positions, mega-trends, plans de relance, allocation cible. Sert de modele de reference pour le dashboard macro. |

### Fil d'Actualite RSS — Sources en temps reel

Flux RSS finances et macro parses automatiquement par `macro.py` (via `feedparser`). Cache dans `news_cache.yaml` (TTL 30 min, gitignore).

| Source | Categorie | Description |
|--------|-----------|-------------|
| Reuters (via Google News) | macro | Actualites business internationales |
| Les Echos | marches | Finance et marches francais/europeens |
| Zone Bourse | marches | Actualites boursieres francophones |
| Investing.com | macro | News marches internationaux |
| BCE | macro | Communiques de presse Banque Centrale Europeenne |
| Fed | macro | Communiques de presse Federal Reserve |

**Configuration** : Les URLs RSS sont dans `macro_config.yaml` (section `news_sources`). Max 10 items par source, 50 au total, tries par date desc.

### Themes d'Allocation — Scoring Macro

Section `allocation_themes` dans `macro_config.yaml` : 9 themes d'investissement, chacun avec :

- `id` : identifiant unique (ex: `defense`, `ia_tech`)
- `name_fr` : nom d'affichage en francais
- `type` : thematique, geo, ou secteur
- `supporting_mega_trends` : liste des IDs de mega-trends qui supportent ce theme
- `sectors` : secteurs GICS associes (pour l'ajustement sectoriel)

L'allocation smart calcule un poids % par theme (pas par ETF). L'utilisateur mappe ses ETFs aux themes dans `target_portfolio.yaml`.

---

## Ajout de nouvelles sources

### Ajouter un article Lyn Alden
1. Placer le PDF dans `context/macro/Lyn Alden/`
2. Creer la synthese `.md` au format `YYMMDD_Titre_Court.md`
3. Inclure les sections `## Points Cles` et `## Mises a Jour du Portefeuille`
4. L'article sera automatiquement parse au prochain appel `/macro`

### Ajouter un rapport sell-side
1. Creer la synthese `.md` dans `context/macro/sell-side/`
2. Ajouter les previsions dans `macro_config.yaml` (section `sell_side_views`)
3. Les donnees seront affichees au prochain appel `/macro`
