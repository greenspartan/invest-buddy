import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

API_URL = "http://localhost:8000/portfolio"
HOLDINGS_URL = "http://localhost:8000/holdings/top"
SECTORS_URL = "http://localhost:8000/sectors"
PERFORMANCE_URL = "http://localhost:8000/performance"
MACRO_URL = "http://localhost:8000/macro"
TARGET_URL = "http://localhost:8000/target"
DRIFT_URL = "http://localhost:8000/drift"

st.set_page_config(page_title="Invest Buddy", layout="wide")
st.title("Invest Buddy")

CURRENCY_SYMBOLS = {"EUR": "\u20ac", "USD": "$", "GBP": "\u00a3", "CHF": "CHF", "JPY": "\u00a5"}


# ---------------------------------------------------------------------------
# Data fetching (cached)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300)
def fetch_portfolio():
    resp = requests.get(API_URL, timeout=30)
    resp.raise_for_status()
    return resp.json()


@st.cache_data(ttl=300)
def fetch_top_holdings():
    resp = requests.get(HOLDINGS_URL, timeout=60)
    resp.raise_for_status()
    return resp.json()


@st.cache_data(ttl=300)
def fetch_sectors():
    resp = requests.get(SECTORS_URL, timeout=60)
    resp.raise_for_status()
    return resp.json()


@st.cache_data(ttl=300)
def fetch_performance(period: str):
    resp = requests.get(PERFORMANCE_URL, params={"period": period}, timeout=120)
    resp.raise_for_status()
    return resp.json()


@st.cache_data(ttl=300)
def fetch_macro(refresh: bool = False):
    resp = requests.get(MACRO_URL, params={"refresh": refresh}, timeout=120)
    resp.raise_for_status()
    return resp.json()


@st.cache_data(ttl=300)
def fetch_target(mode: str = "smart"):
    resp = requests.get(TARGET_URL, params={"mode": mode}, timeout=30)
    resp.raise_for_status()
    return resp.json()


@st.cache_data(ttl=300)
def fetch_drift():
    resp = requests.get(DRIFT_URL, timeout=30)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Load portfolio data (required for all tabs)
# ---------------------------------------------------------------------------

try:
    data = fetch_portfolio()
except requests.exceptions.ConnectionError:
    st.error("Impossible de se connecter a l'API FastAPI. Verifiez qu'elle est lancee sur le port 8000.")
    st.stop()
except Exception as e:
    st.error(f"Erreur: {e}")
    st.stop()

# ---------------------------------------------------------------------------
# Global summary bar (always visible)
# ---------------------------------------------------------------------------

total = data["total"]
col1, col2, col3, col4 = st.columns(4)
col1.metric("Valeur totale", f"{total['market_value']:,.2f} \u20ac")
col2.metric("Cout total", f"{total['cost_basis']:,.2f} \u20ac")
col3.metric("P&L total", f"{total['pnl']:+,.2f} \u20ac")
col4.metric("P&L %", f"{total['pnl_pct']:+.2f}%")

st.divider()

# ---------------------------------------------------------------------------
# Fetch macro data (shared by Macro + News tabs)
# ---------------------------------------------------------------------------

try:
    macro_data = fetch_macro(refresh=st.session_state.get("_macro_refresh", False))
    if st.session_state.get("_macro_refresh"):
        st.session_state["_macro_refresh"] = False
except Exception as e:
    macro_data = None

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

tab_macro, tab_news, tab_target, tab_positions, tab_holdings, tab_sectors, tab_performance, tab_drift = st.tabs(
    ["Macro", "News", "Allocation Cible", "Positions", "Top 20 Holdings", "Secteurs", "Performance", "Rebalancement"]
)

# === Tab 1: Positions =====================================================
with tab_positions:

    # --- Positions table ---
    def _fmt_price(row, col):
        sym = CURRENCY_SYMBOLS.get(row["currency"], row["currency"])
        return f"{row[col]:.2f} {sym}" if row[col] is not None else ""

    df = pd.DataFrame(data["positions"])
    df["PRU"] = df.apply(lambda r: _fmt_price(r, "avg_price"), axis=1)
    df["Prix actuel"] = df.apply(lambda r: _fmt_price(r, "current_price"), axis=1)
    total_mv = total["market_value"]
    df["weight_pct"] = df["market_value_eur"].apply(
        lambda v: round(v / total_mv * 100, 2) if v and total_mv else 0.0
    )

    df = df[["account", "ticker", "qty", "PRU", "Prix actuel", "market_value_eur", "weight_pct", "pnl_eur", "pnl_pct"]]
    df.columns = ["Compte", "Ticker", "Qty", "PRU", "Prix actuel", "Valeur (EUR)", "Poids (%)", "P&L (EUR)", "P&L %"]

    st.dataframe(
        df.style.format({
            "Valeur (EUR)": "{:.2f} \u20ac",
            "Poids (%)": "{:.2f}%",
            "P&L (EUR)": "{:+.2f} \u20ac",
            "P&L %": "{:+.2f}%",
        }).map(
            lambda v: "color: green" if isinstance(v, (int, float)) and v > 0
            else ("color: red" if isinstance(v, (int, float)) and v < 0 else ""),
            subset=["P&L (EUR)", "P&L %"],
        ),
        use_container_width=True,
        hide_index=True,
    )

    # --- Totals by account ---
    st.subheader("Totaux par compte")

    for account, totals in data["totals_by_account"].items():
        c1, c2, c3, c4 = st.columns(4)
        c1.metric(f"{account} - Valeur", f"{totals['market_value']:,.2f} \u20ac")
        c2.metric(f"{account} - Cout", f"{totals['cost_basis']:,.2f} \u20ac")
        c3.metric(f"{account} - P&L", f"{totals['pnl']:+,.2f} \u20ac")
        c4.metric(f"{account} - P&L %", f"{totals['pnl_pct']:+.2f}%")

# === Tab 2: Top 20 Holdings ===============================================
with tab_holdings:

    try:
        holdings_data = fetch_top_holdings()
    except Exception as e:
        st.warning(f"Impossible de recuperer les holdings: {e}")
        holdings_data = None

    if holdings_data:
        meta = holdings_data["meta"]
        no_data_label = ", ".join(meta["etfs_no_data"]) if meta["etfs_no_data"] else "aucun"
        st.caption(
            f"Analyse basee sur {len(meta['etfs_analyzed'])} ETFs "
            f"({meta['portfolio_coverage_pct']:.1f}% du portefeuille). "
            f"Donnees indisponibles pour : {no_data_label}."
        )

        df_h = pd.DataFrame(holdings_data["top_holdings"])
        df_h["etf_sources"] = df_h["etf_sources"].apply(lambda x: ", ".join(x))
        df_h = df_h[["rank", "symbol", "name", "effective_weight_pct", "etf_sources"]]
        df_h.columns = ["#", "Symbole", "Nom", "Poids effectif (%)", "Present dans"]

        st.dataframe(
            df_h.style.format({"Poids effectif (%)": "{:.2f}%"}),
            use_container_width=True,
            hide_index=True,
        )

# === Tab 3: Sector Exposure ===============================================
with tab_sectors:

    try:
        sectors_data = fetch_sectors()
    except Exception as e:
        st.warning(f"Impossible de recuperer les secteurs: {e}")
        sectors_data = None

    if sectors_data and sectors_data["sectors"]:
        meta_s = sectors_data["meta"]
        no_data_s = ", ".join(meta_s["etfs_no_data"]) if meta_s["etfs_no_data"] else "aucun"
        st.caption(
            f"Analyse basee sur {len(meta_s['etfs_analyzed'])} ETFs "
            f"({meta_s['portfolio_coverage_pct']:.1f}% du portefeuille). "
            f"Donnees indisponibles pour : {no_data_s}."
        )

        df_s = pd.DataFrame(sectors_data["sectors"])
        df_s["etf_sources_str"] = df_s["etf_sources"].apply(lambda x: ", ".join(x))

        fig = px.pie(
            df_s,
            names="name",
            values="weight_pct",
            hole=0.4,
            custom_data=["etf_sources_str"],
        )
        fig.update_traces(
            sort=False,
            textinfo="label+percent",
            textposition="outside",
            pull=[0.03] * len(df_s),
            hovertemplate="<b>%{label}</b><br>Poids: %{value:.2f}%<br>ETFs: %{customdata[0]}<extra></extra>",
        )
        fig.update_layout(
            height=650,
            legend=dict(
                orientation="h",
                yanchor="top",
                y=-0.15,
                xanchor="center",
                x=0.5,
            ),
            margin=dict(t=40, b=120, l=40, r=40),
        )
        st.plotly_chart(fig, use_container_width=True)

# === Tab 4: Performance ====================================================
with tab_performance:

    period_options = {
        "1 mois": "1M",
        "3 mois": "3M",
        "6 mois": "6M",
        "1 an": "1Y",
        "Depuis janv.": "YTD",
        "Tout": "ALL",
    }
    selected_label = st.selectbox(
        "Periode", list(period_options.keys()), index=5,
    )
    selected_period = period_options[selected_label]

    try:
        perf_data = fetch_performance(selected_period)
    except Exception as e:
        st.warning(f"Impossible de recuperer la performance: {e}")
        perf_data = None

    if perf_data and perf_data["daily"]:
        df_perf = pd.DataFrame(perf_data["daily"])
        df_perf["date"] = pd.to_datetime(df_perf["date"])

        st.caption(
            f"Du {perf_data['start_date']} au {perf_data['end_date']} "
            f"({perf_data['data_points']} jours de bourse)"
        )

        # --- P&L % chart (green positive, red negative) ---
        st.subheader("P&L (%)")
        fig_pnl = go.Figure()
        fig_pnl.add_trace(go.Scatter(
            x=df_perf["date"], y=df_perf["pnl_pct"].clip(lower=0),
            fill="tozeroy", fillcolor="rgba(46, 204, 113, 0.15)",
            line=dict(width=0), showlegend=False, hoverinfo="skip",
        ))
        fig_pnl.add_trace(go.Scatter(
            x=df_perf["date"], y=df_perf["pnl_pct"].clip(upper=0),
            fill="tozeroy", fillcolor="rgba(231, 76, 60, 0.15)",
            line=dict(width=0), showlegend=False, hoverinfo="skip",
        ))
        fig_pnl.add_trace(go.Scatter(
            x=df_perf["date"], y=df_perf["pnl_pct"],
            line=dict(color="white", width=1.5),
            name="P&L (%)", showlegend=False,
        ))
        fig_pnl.add_hline(y=0, line_dash="dash", line_color="grey", opacity=0.5)
        fig_pnl.update_layout(
            height=400,
            hovermode="x unified",
            yaxis_ticksuffix="%",
            yaxis_title="P&L (%)",
            xaxis_title="Date",
            margin=dict(t=20, b=40, l=60, r=20),
        )
        st.plotly_chart(fig_pnl, use_container_width=True)

        # --- Max Drawdown chart (blue) ---
        st.subheader("Max Drawdown (%)")
        fig_dd = px.area(
            df_perf,
            x="date",
            y="drawdown_pct",
            labels={"date": "Date", "drawdown_pct": "Drawdown (%)"},
        )
        fig_dd.update_traces(
            line_color="#3498db",
            fillcolor="rgba(52, 152, 219, 0.15)",
        )
        fig_dd.update_layout(
            height=350,
            hovermode="x unified",
            yaxis_ticksuffix="%",
            margin=dict(t=20, b=40, l=60, r=20),
        )
        st.plotly_chart(fig_dd, use_container_width=True)

    elif perf_data:
        st.info("Aucune donnee de performance disponible pour cette periode.")

# === Tab 5: Macro ==========================================================

# --- Macro helper constants ---
_OUTLOOK_CONFIG = {
    "risk-on": {"label": "RISK-ON", "icon": "🟢"},
    "moderate-risk-on": {"label": "RISK-ON MODERE", "icon": "🟡"},
    "neutral": {"label": "NEUTRE", "icon": "⚪"},
    "moderate-risk-off": {"label": "RISK-OFF MODERE", "icon": "🟠"},
    "risk-off": {"label": "RISK-OFF", "icon": "🔴"},
}
_FORCE_DISPLAY = {0: "🟡", 1: "🟢", 2: "🟢🟢", 3: "🟢🟢🟢"}
_CHANGE_DISPLAY = {"=": "=", "up": "↑", "down": "↓"}
_STATUS_BADGES = {"active": "✅", "partial": "⚠️", "cut": "🔴", "proposed": "📋"}
_TREND_ARROWS = {"up": "↑", "down": "↓", "flat": "→"}
_SIGNAL_ICONS = {"bullish": "🟢", "bearish": "🔴", "neutral": "⚪"}
_CATEGORY_ORDER = [
    ("inflation", "📊 Inflation"),
    ("rates", "💰 Taux"),
    ("employment", "👷 Emploi"),
    ("activity", "🏭 Activite"),
    ("monetary", "🏦 Monetaire"),
    ("commodity", "🛢️ Commodites"),
    ("sentiment", "📈 Sentiment"),
    ("credit", "📉 Credit"),
    ("forex", "💱 Devises"),
]


_ZONE_ICONS = {
    "US": "\U0001f1fa\U0001f1f8",
    "Europe": "\U0001f1ea\U0001f1fa",
    "Tech": "\U0001f4bb",
    "Energie": "\u26a1",
    "Geopolitique": "\U0001f30d",
    "Marches": "\U0001f4c8",
    "Autre": "\U0001f4f0",
}
_ZONE_ORDER = ["US", "Europe", "Tech", "Energie", "Geopolitique", "Marches", "Autre"]


def _render_news_tab(macro_data):
    """Render the News tab with items organized by thematic/geographic zone."""
    news = macro_data.get("news_feed", [])
    if not news:
        st.info("Aucune actualite disponible. Verifiez la configuration des flux RSS dans macro_config.yaml.")
        return

    st.caption(f"{len(news)} articles disponibles")

    # Group by zone
    by_zone: dict[str, list] = {}
    for n in news:
        zone = n.get("zone", "Autre") or "Autre"
        by_zone.setdefault(zone, []).append(n)

    for zone in _ZONE_ORDER:
        items = by_zone.get(zone, [])
        if not items:
            continue

        icon = _ZONE_ICONS.get(zone, "\U0001f4f0")
        st.subheader(f"{icon} {zone}")

        for n in items[:8]:
            cols = st.columns([1, 5])
            with cols[0]:
                st.caption(n["date"][:10])
                st.caption(f"*{n['source']}*")
            with cols[1]:
                st.markdown(f"[**{n['title']}**]({n['url']})")
                if n.get("summary"):
                    st.caption(n["summary"][:150])

        st.divider()


def _render_macro_outlook(macro_data):
    """Section 1: Outlook banner."""
    outlook = macro_data["outlook"]
    score = macro_data["score"]
    cfg = _OUTLOOK_CONFIG.get(outlook, _OUTLOOK_CONFIG["neutral"])
    st.markdown(f"### {cfg['icon']} Outlook: **{cfg['label']}** (score: {score:+.3f})")
    st.caption(
        f"Sources actives: {', '.join(macro_data['sources_available'])}. "
        f"Echec: {', '.join(macro_data['sources_failed']) or 'aucun'}. "
        f"Derniere MAJ: {macro_data['last_updated']}"
    )
    if macro_data.get("themes"):
        st.markdown("**Synthese macro:**")
        for theme in macro_data["themes"]:
            st.markdown(f"- {theme}")


def _render_mega_trends(macro_data):
    """Section 2: Mega-Trends matrix."""
    st.subheader("Matrice Mega-Trends")
    trends = macro_data.get("mega_trends", [])
    if not trends:
        st.info("Aucune donnee mega-trends. Editez macro_config.yaml.")
        return

    trends_sorted = sorted(trends, key=lambda t: t.get("force", 0), reverse=True)
    rows = []
    for i, t in enumerate(trends_sorted, 1):
        all_etfs = t.get("etfs_sectoriels", []) + t.get("etfs_geo", []) + t.get("etfs_thematiques", [])
        rows.append({
            "#": i,
            "Mega-Trend": t["name_fr"],
            "Force": _FORCE_DISPLAY.get(t.get("force", 0), "?"),
            "Δ": _CHANGE_DISPLAY.get(t.get("change", "="), "="),
            "ETFs": ", ".join(all_etfs) or "—",
            "Secteurs": ", ".join(t.get("sectors", [])) or "—",
        })
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    with st.expander("Detail des catalyseurs"):
        for t in trends_sorted:
            force_str = _FORCE_DISPLAY.get(t.get("force", 0), "?")
            st.markdown(f"**{force_str} {t['name_fr']}**")
            for c in t.get("catalysts", []):
                st.markdown(f"  - {c}")


def _render_investment_plans(macro_data):
    """Section 3: Plans de Relance (US + EU)."""
    st.subheader("Plans de Relance")
    plans = macro_data.get("investment_plans", [])
    if not plans:
        st.info("Aucune donnee plans de relance. Editez macro_config.yaml.")
        return

    us_plans = [p for p in plans if p.get("region") == "us"]
    eu_plans = [p for p in plans if p.get("region") == "eu"]

    col_us, col_eu = st.columns(2)

    with col_us:
        st.markdown("#### 🇺🇸 US — Congres / Administration")
        if us_plans:
            rows = [{
                "Programme": p["name"],
                "Montant": p["amount"],
                "Statut": f"{_STATUS_BADGES.get(p.get('status', ''), '?')} {p.get('status_detail', '')}",
                "Δ": _CHANGE_DISPLAY.get(p.get("change", "="), "="),
            } for p in us_plans]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    with col_eu:
        st.markdown("#### 🇪🇺 EU — Commission / Parlement")
        if eu_plans:
            rows = [{
                "Programme": p["name"],
                "Montant": p["amount"],
                "Statut": f"{_STATUS_BADGES.get(p.get('status', ''), '?')} {p.get('status_detail', '')}",
                "Δ": _CHANGE_DISPLAY.get(p.get("change", "="), "="),
            } for p in eu_plans]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def _render_sell_side_views(macro_data):
    """Section 4: Previsions Sell-Side (JPMorgan, BofA)."""
    st.subheader("Previsions Sell-Side")
    views = macro_data.get("sell_side_views", [])
    if not views:
        st.info("Aucune prevision sell-side. Editez macro_config.yaml.")
        return

    tabs_sell = st.tabs([f"{v['source']} ({v['date']})" for v in views])
    for tab_sv, view in zip(tabs_sell, views):
        with tab_sv:
            # Forecasts table
            forecasts = view.get("forecasts", {})
            if forecasts:
                st.markdown("**Previsions cles:**")
                rows = [{"Indicateur": k.replace("_", " ").title(), "Prevision": v} for k, v in forecasts.items()]
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

            # Key themes
            themes = view.get("key_themes", [])
            if themes:
                st.markdown("**Themes:**")
                for t in themes:
                    st.markdown(f"- {t}")

            # Risks
            risks = view.get("risks", [])
            if risks:
                st.markdown("**Risques:**")
                for r in risks:
                    st.markdown(f"- ⚠️ {r}")


def _render_lyn_alden(macro_data):
    """Section 5: Lyn Alden Premium Insights."""
    st.subheader("Lyn Alden — Analyse Premium")
    articles = macro_data.get("lyn_alden_insights", [])
    if not articles:
        st.info("Aucun article Lyn Alden trouve dans context/macro/Lyn Alden/.")
        return

    latest = articles[0]
    st.markdown(f"#### 📄 Dernier article: **{latest['title']}** ({latest['date']})")

    if latest.get("key_points"):
        st.markdown("**Points cles:**")
        for pt in latest["key_points"]:
            st.markdown(f"- {pt}")

    if latest.get("portfolio_changes"):
        st.markdown("**Mouvements portefeuille:**")
        for mv in latest["portfolio_changes"]:
            st.markdown(f"- {mv}")

    if len(articles) > 1:
        with st.expander(f"Articles precedents ({len(articles) - 1})"):
            for art in articles[1:]:
                st.markdown(f"**{art['title']}** — {art['date']}")
                if art.get("key_points"):
                    for pt in art["key_points"][:3]:
                        st.markdown(f"  - {pt}")
                st.markdown("---")


def _render_indicators(macro_data):
    """Section 6: Macro indicators grouped by category."""
    st.subheader("Indicateurs Macro")

    indicators_ok = [ind for ind in macro_data["indicators"] if ind.get("error") is None]
    by_category = {}
    for ind in indicators_ok:
        cat = ind.get("category", "other")
        by_category.setdefault(cat, []).append(ind)

    for cat_key, cat_label in _CATEGORY_ORDER:
        inds = by_category.get(cat_key, [])
        if not inds:
            continue

        st.markdown(f"**{cat_label}**")
        df = pd.DataFrame(inds)
        df["Tendance"] = df["trend"].map(lambda t: _TREND_ARROWS.get(t, "—"))
        df["Signal"] = df["signal"].map(lambda s: _SIGNAL_ICONS.get(s, "—"))

        df_display = df[["name_fr", "value", "previous_value", "Tendance", "Signal", "unit", "source", "date"]].copy()
        df_display.columns = ["Indicateur", "Valeur", "Precedente", "Tendance", "Signal", "Unite", "Source", "Date"]

        st.dataframe(
            df_display.style.format({
                "Valeur": lambda v: f"{v:,.2f}" if pd.notna(v) else "—",
                "Precedente": lambda v: f"{v:,.2f}" if pd.notna(v) else "—",
            }),
            use_container_width=True,
            hide_index=True,
        )

    failed = [ind for ind in macro_data["indicators"] if ind.get("error") is not None]
    if failed:
        with st.expander(f"{len(failed)} indicateur(s) indisponible(s)"):
            for ind in failed:
                st.text(f"{ind['name_fr']}: {ind['error']}")


def _render_sector_signals(macro_data):
    """Section 7: Sector signals."""
    st.subheader("Signaux Sectoriels")
    signals = macro_data.get("sector_signals", [])
    if not signals:
        st.info("Aucun signal sectoriel disponible.")
        return

    rows = []
    for s in signals:
        signal_icon = _SIGNAL_ICONS.get(s.get("signal", "neutral"), "⚪")
        signal_label = s.get("signal", "neutral").capitalize()
        rows.append({
            "Secteur": s["sector"],
            "Signal": f"{signal_icon} {signal_label}",
            "Mega-Trends": ", ".join(s.get("supporting_trends", [])) or "—",
        })
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)


with tab_macro:

    col_refresh, _ = st.columns([1, 5])
    with col_refresh:
        if st.button("Rafraichir les donnees"):
            fetch_macro.clear()
            st.session_state["_macro_refresh"] = True
            st.rerun()

    if macro_data:
        _render_macro_outlook(macro_data)
        st.divider()
        _render_mega_trends(macro_data)
        st.divider()
        _render_investment_plans(macro_data)
        st.divider()
        _render_sell_side_views(macro_data)
        st.divider()
        _render_lyn_alden(macro_data)
        st.divider()
        _render_indicators(macro_data)
        st.divider()
        _render_sector_signals(macro_data)
    else:
        st.warning("Impossible de recuperer les donnees macro.")

# === Tab 2: News =============================================================
with tab_news:
    if macro_data:
        _render_news_tab(macro_data)
    else:
        st.info("Donnees macro non disponibles.")

# === Tab 6: Allocation Cible ===============================================
with tab_target:

    _TYPE_LABELS = {"thematique": "Thematique", "geo": "Geographique", "secteur": "Sectoriel"}

    target_mode = st.radio(
        "Mode d'allocation",
        ["Smart (macro-driven)", "Statique (YAML)"],
        index=0,
        horizontal=True,
    )
    mode_param = "smart" if "Smart" in target_mode else "static"

    try:
        target_data = fetch_target(mode=mode_param)
    except Exception as e:
        st.warning(f"Impossible de recuperer l'allocation cible: {e}")
        target_data = None

    if target_data:
        method = target_data.get("method", "static")

        if method == "smart" and target_data.get("themes"):
            # --- Smart mode: theme-based allocation ---
            outlook = target_data.get("outlook", "neutral")
            score = target_data.get("score", 0.0)
            cfg = _OUTLOOK_CONFIG.get(outlook, _OUTLOOK_CONFIG["neutral"])
            st.caption(
                f"Allocation thematique generee depuis l'analyse macro "
                f"({cfg['icon']} {cfg['label']}, score: {score:+.3f}). "
                f"Mappez vos ETFs a ces themes dans target_portfolio.yaml."
            )

            total_w = target_data["total_weight_pct"]
            if abs(total_w - 100.0) > 0.01:
                st.warning(f"La somme des poids est de {total_w:.1f}% (devrait etre 100%)")

            df_themes = pd.DataFrame(target_data["themes"])
            df_themes["Type"] = df_themes["type"].map(lambda t: _TYPE_LABELS.get(t, t))
            df_themes = df_themes[["name_fr", "Type", "weight_pct", "rationale"]]
            df_themes.columns = ["Theme", "Type", "Poids cible (%)", "Raison"]

            st.dataframe(
                df_themes.style.format({"Poids cible (%)": "{:.1f}%"}),
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Raison": st.column_config.TextColumn(width="large"),
                },
            )

            # Pie chart by theme
            fig_target = px.pie(
                df_themes,
                names="Theme",
                values="Poids cible (%)",
                hole=0.4,
            )
            fig_target.update_traces(
                sort=False,
                textinfo="label+percent",
                textposition="outside",
                pull=[0.03] * len(df_themes),
                hovertemplate="<b>%{label}</b><br>Poids: %{value:.1f}%<extra></extra>",
            )
            fig_target.update_layout(
                height=650,
                legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5),
                margin=dict(t=40, b=120, l=40, r=40),
            )
            st.plotly_chart(fig_target, use_container_width=True)

        elif target_data.get("allocations"):
            # --- Static mode: ETF-based allocation ---
            total_w = target_data["total_weight_pct"]
            if abs(total_w - 100.0) > 0.01:
                st.warning(f"La somme des poids est de {total_w:.1f}% (devrait etre 100%)")

            df_target = pd.DataFrame(target_data["allocations"])
            df_target = df_target[["ticker", "name", "weight_pct"]]
            df_target.columns = ["Ticker", "Nom", "Poids cible (%)"]
            st.dataframe(
                df_target.style.format({"Poids cible (%)": "{:.1f}%"}),
                use_container_width=True,
                hide_index=True,
            )

            # Pie chart
            fig_target = px.pie(
                df_target,
                names="Nom",
                values="Poids cible (%)",
                hole=0.4,
            )
            fig_target.update_traces(
                sort=False,
                textinfo="label+percent",
                textposition="outside",
                pull=[0.03] * len(df_target),
                hovertemplate="<b>%{label}</b><br>Poids: %{value:.1f}%<extra></extra>",
            )
            fig_target.update_layout(
                height=650,
                legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5),
                margin=dict(t=40, b=120, l=40, r=40),
            )
            st.plotly_chart(fig_target, use_container_width=True)

        else:
            st.info("Aucune allocation cible definie. Configurez allocation_themes dans macro_config.yaml (smart) ou target_portfolio.yaml (statique).")

# === Tab 7: Rebalancement ==================================================
with tab_drift:

    st.caption("Drift calcule par rapport a target_portfolio.yaml (allocation statique par ETF).")

    try:
        drift_data = fetch_drift()
    except Exception as e:
        st.warning(f"Impossible de recuperer le drift: {e}")
        drift_data = None

    if drift_data and drift_data["entries"]:
        st.caption(
            f"Valeur totale du portefeuille: {drift_data['total_portfolio_eur']:,.2f} EUR. "
            f"Drift max: {drift_data['max_drift_pct']:.2f}%"
        )

        df_drift = pd.DataFrame(drift_data["entries"])
        df_drift = df_drift[["ticker", "name", "target_pct", "current_pct", "drift_pct", "action",
                              "current_value_eur", "target_value_eur", "rebalance_amount_eur"]]
        df_drift.columns = ["Ticker", "Nom", "Cible (%)", "Actuel (%)", "Drift (%)", "Action",
                             "Valeur actuelle (EUR)", "Valeur cible (EUR)", "Rebalancement (EUR)"]

        def _color_action(val):
            if val == "BUY":
                return "background-color: rgba(46, 204, 113, 0.2); color: green"
            elif val == "SELL":
                return "background-color: rgba(231, 76, 60, 0.2); color: red"
            return ""

        st.dataframe(
            df_drift.style.format({
                "Cible (%)": "{:.1f}%",
                "Actuel (%)": "{:.1f}%",
                "Drift (%)": "{:+.2f}%",
                "Valeur actuelle (EUR)": "{:,.2f} \u20ac",
                "Valeur cible (EUR)": "{:,.2f} \u20ac",
                "Rebalancement (EUR)": "{:+,.2f} \u20ac",
            }).map(
                lambda v: "color: red" if isinstance(v, (int, float)) and v > 2
                else ("color: orange" if isinstance(v, (int, float)) and v < -2 else ""),
                subset=["Drift (%)"],
            ).map(_color_action, subset=["Action"]),
            use_container_width=True,
            hide_index=True,
        )

        # Summary of actions needed
        actions = [e for e in drift_data["entries"] if e["action"] != "HOLD"]
        if actions:
            st.subheader("Actions de rebalancement suggerees")
            for entry in actions:
                sign = "+" if entry["rebalance_amount_eur"] > 0 else ""
                st.markdown(
                    f"- **{entry['action']}** {entry['ticker']} ({entry['name']}): "
                    f"{sign}{entry['rebalance_amount_eur']:,.2f} EUR"
                )
        else:
            st.success("Portefeuille aligne avec l'allocation cible. Aucune action necessaire.")

    elif drift_data:
        st.info("Aucune allocation cible definie. Editez target_portfolio.yaml d'abord.")
