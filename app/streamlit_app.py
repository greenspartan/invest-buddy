import streamlit as st
import requests
import pandas as pd
import plotly.express as px

API_URL = "http://localhost:8000/portfolio"
HOLDINGS_URL = "http://localhost:8000/holdings/top"
SECTORS_URL = "http://localhost:8000/sectors"

st.set_page_config(page_title="Invest Buddy", layout="wide")
st.title("Invest Buddy")


@st.cache_data(ttl=300)
def fetch_portfolio():
    resp = requests.get(API_URL, timeout=30)
    resp.raise_for_status()
    return resp.json()


try:
    data = fetch_portfolio()
except requests.exceptions.ConnectionError:
    st.error("Impossible de se connecter a l'API FastAPI. Verifiez qu'elle est lancee sur le port 8000.")
    st.stop()
except Exception as e:
    st.error(f"Erreur: {e}")
    st.stop()

# --- Positions table ---
st.header("Positions")

CURRENCY_SYMBOLS = {"EUR": "\u20ac", "USD": "$", "GBP": "\u00a3", "CHF": "CHF", "JPY": "\u00a5"}

df = pd.DataFrame(data["positions"])

# Format PRU and current price with native currency symbol
def _fmt_price(row, col):
    sym = CURRENCY_SYMBOLS.get(row["currency"], row["currency"])
    return f"{row[col]:.2f} {sym}" if row[col] is not None else ""

df["PRU"] = df.apply(lambda r: _fmt_price(r, "avg_price"), axis=1)
df["Prix actuel"] = df.apply(lambda r: _fmt_price(r, "current_price"), axis=1)

df = df[["account", "ticker", "qty", "PRU", "Prix actuel", "market_value_eur", "pnl_eur", "pnl_pct"]]
df.columns = ["Compte", "Ticker", "Qty", "PRU", "Prix actuel", "Valeur (EUR)", "P&L (EUR)", "P&L %"]

st.dataframe(
    df.style.format({
        "Valeur (EUR)": "{:.2f} \u20ac",
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
st.header("Totaux par compte")

for account, totals in data["totals_by_account"].items():
    col1, col2, col3, col4 = st.columns(4)
    col1.metric(f"{account} - Valeur", f"{totals['market_value']:,.2f} EUR")
    col2.metric(f"{account} - Cout", f"{totals['cost_basis']:,.2f} EUR")
    col3.metric(f"{account} - P&L", f"{totals['pnl']:+,.2f} EUR")
    col4.metric(f"{account} - P&L %", f"{totals['pnl_pct']:+.2f}%")

# --- Global total ---
st.header("Total global")

total = data["total"]
col1, col2, col3, col4 = st.columns(4)
col1.metric("Valeur totale", f"{total['market_value']:,.2f} EUR")
col2.metric("Cout total", f"{total['cost_basis']:,.2f} EUR")
col3.metric("P&L total", f"{total['pnl']:+,.2f} EUR")
col4.metric("P&L %", f"{total['pnl_pct']:+.2f}%")

# --- Top 20 underlying holdings ---
st.header("Top 20 positions sous-jacentes")


@st.cache_data(ttl=300)
def fetch_top_holdings():
    resp = requests.get(HOLDINGS_URL, timeout=60)
    resp.raise_for_status()
    return resp.json()


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

# --- Sector exposure pie chart ---
st.header("Exposition sectorielle")


@st.cache_data(ttl=300)
def fetch_sectors():
    resp = requests.get(SECTORS_URL, timeout=60)
    resp.raise_for_status()
    return resp.json()


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
    fig = px.pie(
        df_s,
        names="name",
        values="weight_pct",
        hole=0.35,
    )
    fig.update_traces(textinfo="label+percent", textposition="outside")
    fig.update_layout(showlegend=False, margin=dict(t=20, b=20, l=20, r=20))
    st.plotly_chart(fig, use_container_width=True)
