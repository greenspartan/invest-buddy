"""ETF holdings fetching and portfolio-level aggregation.

This module is self-contained: it depends only on yfinance and the
standard library, so it can be reused by any script that needs
holdings data.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import yfinance as yf


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Holding:
    """A single holding within an ETF."""

    symbol: str
    name: str
    weight: float  # fraction, e.g. 0.054 = 5.4 %


@dataclass
class EffectiveHolding:
    """A holding with its effective weight across the whole portfolio."""

    symbol: str
    name: str
    effective_weight: float  # fraction, e.g. 0.038 = 3.8 %
    etf_sources: list[str] = field(default_factory=list)


@dataclass
class TopHoldingsResult:
    """Full result of the top-holdings computation, including metadata."""

    holdings: list[EffectiveHolding]
    etfs_analyzed: list[str]
    etfs_no_data: list[str]
    portfolio_coverage: float  # fraction of portfolio MV covered


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def fetch_etf_holdings(ticker: str) -> list[Holding]:
    """Fetch the top holdings for a single ETF via yfinance.

    Returns an empty list when data is unavailable (graceful degradation).
    """
    try:
        etf = yf.Ticker(ticker)
        top_holdings = etf.funds_data.top_holdings
        if top_holdings is None or top_holdings.empty:
            return []
        return [
            Holding(
                symbol=str(symbol),
                name=row["Name"],
                weight=float(row["Holding Percent"]),
            )
            for symbol, row in top_holdings.iterrows()
        ]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def compute_top_holdings(
    positions: list[dict],
    top_n: int = 20,
) -> TopHoldingsResult:
    """Compute the top *N* effective holdings across the entire portfolio.

    Parameters
    ----------
    positions:
        Enriched position dicts (must contain ``ticker`` and ``market_value_eur``).
    top_n:
        Number of holdings to return.

    Returns
    -------
    TopHoldingsResult
        Holdings sorted by descending effective weight, plus coverage metadata.
    """
    valid = [p for p in positions if p.get("market_value_eur") is not None]
    total_mv = sum(p["market_value_eur"] for p in valid)

    if total_mv == 0:
        return TopHoldingsResult([], [], [], 0.0)

    aggregated: dict[str, dict] = {}
    etfs_analyzed: list[str] = []
    etfs_no_data: list[str] = []
    covered_mv = 0.0

    for pos in valid:
        ticker = pos["ticker"]
        etf_weight = pos["market_value_eur"] / total_mv
        holdings = fetch_etf_holdings(ticker)

        if not holdings:
            etfs_no_data.append(ticker)
            continue

        etfs_analyzed.append(ticker)
        covered_mv += pos["market_value_eur"]

        for h in holdings:
            eff_w = h.weight * etf_weight
            if h.symbol in aggregated:
                aggregated[h.symbol]["effective_weight"] += eff_w
                if ticker not in aggregated[h.symbol]["etf_sources"]:
                    aggregated[h.symbol]["etf_sources"].append(ticker)
            else:
                aggregated[h.symbol] = {
                    "name": h.name,
                    "effective_weight": eff_w,
                    "etf_sources": [ticker],
                }

    sorted_holdings = sorted(
        aggregated.items(),
        key=lambda item: item[1]["effective_weight"],
        reverse=True,
    )[:top_n]

    return TopHoldingsResult(
        holdings=[
            EffectiveHolding(
                symbol=symbol,
                name=data["name"],
                effective_weight=round(data["effective_weight"], 6),
                etf_sources=data["etf_sources"],
            )
            for symbol, data in sorted_holdings
        ],
        etfs_analyzed=etfs_analyzed,
        etfs_no_data=etfs_no_data,
        portfolio_coverage=round(covered_mv / total_mv, 4),
    )
