"""ETF sector-exposure fetching and portfolio-level aggregation.

This module is self-contained: it depends only on yfinance and the
standard library, so it can be reused by any script that needs
sector data.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import yfinance as yf


# ---------------------------------------------------------------------------
# Sector label mapping (yfinance snake_case -> display name)
# ---------------------------------------------------------------------------

SECTOR_LABELS: dict[str, str] = {
    "technology": "Technology",
    "financial_services": "Financial Services",
    "healthcare": "Healthcare",
    "consumer_cyclical": "Consumer Cyclical",
    "communication_services": "Communication Services",
    "industrials": "Industrials",
    "consumer_defensive": "Consumer Defensive",
    "energy": "Energy",
    "basic_materials": "Basic Materials",
    "realestate": "Real Estate",
    "utilities": "Utilities",
}


def _normalize_sector(name: str) -> str:
    """Convert a yfinance sector key to a human-readable label."""
    return SECTOR_LABELS.get(name, name.replace("_", " ").title())


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SectorExposureResult:
    """Aggregated sector exposure across the whole portfolio."""

    sectors: dict[str, float]  # sector_name -> effective weight (fraction)
    etfs_analyzed: list[str] = field(default_factory=list)
    etfs_no_data: list[str] = field(default_factory=list)
    portfolio_coverage: float = 0.0  # fraction of portfolio MV covered


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def fetch_etf_sectors(ticker: str) -> dict[str, float]:
    """Fetch sector weightings for a single ETF via yfinance.

    Returns a dict ``{"Technology": 0.25, ...}`` or an empty dict when
    data is unavailable (graceful degradation).
    """
    try:
        etf = yf.Ticker(ticker)
        weightings = etf.funds_data.sector_weightings
        if weightings is None:
            return {}
        # sector_weightings is a dict of dicts: {sector: {weight: value}}
        # or a simple dict depending on yfinance version
        result: dict[str, float] = {}
        if isinstance(weightings, dict):
            for sector, value in weightings.items():
                if isinstance(value, dict):
                    result[sector] = float(list(value.values())[0])
                else:
                    result[sector] = float(value)
        return result
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def compute_sector_exposure(
    positions: list[dict],
) -> SectorExposureResult:
    """Compute the effective sector exposure across the entire portfolio.

    Parameters
    ----------
    positions:
        Enriched position dicts (must contain ``ticker`` and ``market_value_eur``).

    Returns
    -------
    SectorExposureResult
        Sectors sorted by descending effective weight, plus coverage metadata.
    """
    valid = [p for p in positions if p.get("market_value_eur") is not None]
    total_mv = sum(p["market_value_eur"] for p in valid)

    if total_mv == 0:
        return SectorExposureResult({})

    aggregated: dict[str, float] = {}
    etfs_analyzed: list[str] = []
    etfs_no_data: list[str] = []
    covered_mv = 0.0

    for pos in valid:
        ticker = pos["ticker"]
        etf_weight = pos["market_value_eur"] / total_mv
        sectors = fetch_etf_sectors(ticker)

        if not sectors:
            etfs_no_data.append(ticker)
            continue

        etfs_analyzed.append(ticker)
        covered_mv += pos["market_value_eur"]

        for sector, weight in sectors.items():
            label = _normalize_sector(sector)
            aggregated[label] = aggregated.get(label, 0.0) + weight * etf_weight

    sorted_sectors = dict(
        sorted(aggregated.items(), key=lambda item: item[1], reverse=True)
    )

    return SectorExposureResult(
        sectors={k: round(v, 6) for k, v in sorted_sectors.items()},
        etfs_analyzed=etfs_analyzed,
        etfs_no_data=etfs_no_data,
        portfolio_coverage=round(covered_mv / total_mv, 4) if total_mv else 0.0,
    )
