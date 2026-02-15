import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

API_URL = "http://localhost:8000/portfolio"
HOLDINGS_URL = "http://localhost:8000/holdings/top"
SECTORS_URL = "http://localhost:8000/sectors"
PERFORMANCE_URL = "http://localhost:8000/performance"

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

tab_positions, tab_holdings, tab_sectors, tab_performance = st.tabs(
    ["Positions", "Top 20 Holdings", "Secteurs", "Performance"]
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
