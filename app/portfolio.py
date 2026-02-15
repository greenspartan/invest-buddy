import yaml
import yfinance as yf

from app.config import PORTFOLIO_PATH


def load_portfolio() -> list[dict]:
    with open(PORTFOLIO_PATH, "r") as f:
        data = yaml.safe_load(f)
    return data.get("positions", [])


def fetch_current_prices(tickers: list[str]) -> dict[str, float | None]:
    prices = {}
    for ticker in tickers:
        try:
            t = yf.Ticker(ticker)
            info = t.fast_info
            prices[ticker] = info.get("lastPrice") or info.get("previousClose")
        except Exception:
            prices[ticker] = None
    return prices


def enrich_positions(positions: list[dict]) -> list[dict]:
    tickers = [p["ticker"] for p in positions]
    prices = fetch_current_prices(tickers)

    enriched = []
    for pos in positions:
        ticker = pos["ticker"]
        current_price = prices.get(ticker)
        qty = pos["qty"]
        avg_price = pos["avg_price"]

        if current_price is not None:
            market_value = round(current_price * qty, 2)
            cost_basis = round(avg_price * qty, 2)
            pnl = round(market_value - cost_basis, 2)
            pnl_pct = round((pnl / cost_basis) * 100, 2) if cost_basis != 0 else 0.0
        else:
            market_value = None
            pnl = None
            pnl_pct = None

        enriched.append({
            "ticker": ticker,
            "qty": qty,
            "avg_price": avg_price,
            "current_price": current_price,
            "market_value": market_value,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "account": pos["account"],
        })

    return enriched
