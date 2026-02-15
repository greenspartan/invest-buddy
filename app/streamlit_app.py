import streamlit as st
import requests
import pandas as pd

API_URL = "http://localhost:8000/portfolio"

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

df = pd.DataFrame(data["positions"])
df = df[["account", "ticker", "qty", "avg_price", "current_price", "market_value", "pnl", "pnl_pct"]]
df.columns = ["Compte", "Ticker", "Qty", "PRU", "Prix actuel", "Valeur", "P&L", "P&L %"]

st.dataframe(
    df.style.format({
        "PRU": "{:.2f} EUR",
        "Prix actuel": "{:.2f} EUR",
        "Valeur": "{:.2f} EUR",
        "P&L": "{:+.2f} EUR",
        "P&L %": "{:+.2f}%",
    }).map(
        lambda v: "color: green" if isinstance(v, (int, float)) and v > 0
        else ("color: red" if isinstance(v, (int, float)) and v < 0 else ""),
        subset=["P&L", "P&L %"],
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
