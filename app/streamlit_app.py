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
def fetch_target():
    resp = requests.get(TARGET_URL, timeout=15)
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
# Tabs
# ---------------------------------------------------------------------------

tab_positions, tab_holdings, tab_sectors, tab_performance, tab_macro, tab_target, tab_drift = st.tabs(
    ["Positions", "Top 20 Holdings", "Secteurs", "Performance", "Macro", "Allocation Cible", "Rebalancement"]
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
with tab_macro:

    col_refresh, _ = st.columns([1, 5])
    with col_refresh:
        do_refresh = st.button("Rafraichir les donnees")

    try:
        if do_refresh:
            fetch_macro.clear()
        macro_data = fetch_macro(refresh=do_refresh)
    except Exception as e:
        st.warning(f"Impossible de recuperer les donnees macro: {e}")
        macro_data = None

    if macro_data:
        # --- Outlook banner ---
        outlook = macro_data["outlook"]
        score = macro_data["score"]

        OUTLOOK_CONFIG = {
            "risk-on": {"label": "RISK-ON", "icon": "🟢"},
            "moderate-risk-on": {"label": "RISK-ON MODERE", "icon": "🟡"},
            "neutral": {"label": "NEUTRE", "icon": "⚪"},
            "moderate-risk-off": {"label": "RISK-OFF MODERE", "icon": "🟠"},
            "risk-off": {"label": "RISK-OFF", "icon": "🔴"},
        }
        cfg = OUTLOOK_CONFIG.get(outlook, OUTLOOK_CONFIG["neutral"])

        st.markdown(f"### {cfg['icon']} Outlook: **{cfg['label']}** (score: {score:+.3f})")

        st.caption(
            f"Sources actives: {', '.join(macro_data['sources_available'])}. "
            f"Echec: {', '.join(macro_data['sources_failed']) or 'aucun'}. "
            f"Derniere MAJ: {macro_data['last_updated']}"
        )

        # --- Themes (from Lyn Alden, if populated) ---
        if macro_data.get("themes"):
            st.subheader("Themes macro")
            for theme in macro_data["themes"]:
                st.markdown(f"- {theme}")

        # --- Indicators table ---
        st.subheader("Indicateurs")

        indicators_ok = [ind for ind in macro_data["indicators"] if ind.get("error") is None]
        if indicators_ok:
            df_macro = pd.DataFrame(indicators_ok)

            TREND_ARROWS = {"up": "↑", "down": "↓", "flat": "→"}
            SIGNAL_COLORS = {"bullish": "🟢", "bearish": "🔴", "neutral": "⚪"}

            df_macro["Tendance"] = df_macro["trend"].map(lambda t: TREND_ARROWS.get(t, "—"))
            df_macro["Signal"] = df_macro["signal"].map(lambda s: SIGNAL_COLORS.get(s, "—"))

            df_display = df_macro[["name_fr", "value", "previous_value", "Tendance", "Signal", "unit", "source", "date"]]
            df_display = df_display.copy()
            df_display.columns = ["Indicateur", "Valeur", "Precedente", "Tendance", "Signal", "Unite", "Source", "Date"]

            st.dataframe(
                df_display.style.format({
                    "Valeur": lambda v: f"{v:.2f}" if pd.notna(v) else "—",
                    "Precedente": lambda v: f"{v:.2f}" if pd.notna(v) else "—",
                }),
                use_container_width=True,
                hide_index=True,
            )

        # --- Failed indicators ---
        failed = [ind for ind in macro_data["indicators"] if ind.get("error") is not None]
        if failed:
            with st.expander(f"{len(failed)} indicateur(s) indisponible(s)"):
                for ind in failed:
                    st.text(f"{ind['name_fr']}: {ind['error']}")

# === Tab 6: Allocation Cible ===============================================
with tab_target:

    try:
        target_data = fetch_target()
    except Exception as e:
        st.warning(f"Impossible de recuperer l'allocation cible: {e}")
        target_data = None

    if target_data and target_data["allocations"]:
        total_w = target_data["total_weight_pct"]
        if abs(total_w - 100.0) > 0.01:
            st.warning(f"La somme des poids est de {total_w:.1f}% (devrait etre 100%)")

        df_target = pd.DataFrame(target_data["allocations"])
        df_target.columns = ["Ticker", "Nom", "Poids cible (%)"]

        st.dataframe(
            df_target.style.format({"Poids cible (%)": "{:.1f}%"}),
            use_container_width=True,
            hide_index=True,
        )

        # Pie chart (same style as sectors tab)
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

    elif target_data:
        st.info("Aucune allocation cible definie. Editez target_portfolio.yaml.")

# === Tab 7: Rebalancement ==================================================
with tab_drift:

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
