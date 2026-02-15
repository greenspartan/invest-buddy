"""Historical portfolio performance computation.

This module is self-contained: it depends only on yfinance, pandas,
and the standard library, so it can be reused by any script that
needs historical performance data.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field

import pandas as pd
import yfinance as yf


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PERIODS = {"1M", "3M", "6M", "1Y", "YTD", "ALL"}

BASE_CURRENCY = "EUR"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class DailyPerformance:
    """A single day's portfolio performance snapshot."""

    date: str  # "YYYY-MM-DD"
    portfolio_value_eur: float
    cost_basis_eur: float
    pnl_eur: float
    pnl_pct: float
    drawdown_pct: float


@dataclass
class PerformanceResult:
    """Full result of the performance computation."""

    daily: list[DailyPerformance] = field(default_factory=list)
    period: str = "ALL"
    start_date: str = ""
    end_date: str = ""


# ---------------------------------------------------------------------------
# Period resolution
# ---------------------------------------------------------------------------

def _resolve_start_date(
    period: str,
    earliest_purchase: datetime.date,
    today: datetime.date,
) -> datetime.date:
    """Convert a period code to a concrete start date."""
    if period == "1M":
        return today - datetime.timedelta(days=30)
    if period == "3M":
        return today - datetime.timedelta(days=90)
    if period == "6M":
        return today - datetime.timedelta(days=180)
    if period == "1Y":
        return today - datetime.timedelta(days=365)
    if period == "YTD":
        return datetime.date(today.year, 1, 1)
    # "ALL"
    return earliest_purchase


# ---------------------------------------------------------------------------
# Historical data fetching
# ---------------------------------------------------------------------------

def _fetch_historical_prices(
    ticker: str,
    start: datetime.date,
    end: datetime.date,
) -> pd.Series:
    """Fetch daily Close prices for a ticker between *start* and *end*.

    Returns a pandas Series indexed by ``datetime.date``.
    Returns an empty Series on failure.
    """
    try:
        t = yf.Ticker(ticker)
        df = t.history(
            start=start.isoformat(),
            end=(end + datetime.timedelta(days=1)).isoformat(),
            interval="1d",
        )
        if df.empty:
            return pd.Series(dtype=float)
        series = df["Close"]
        series.index = series.index.date
        return series
    except Exception:
        return pd.Series(dtype=float)


def _fetch_historical_fx_rate(
    from_currency: str,
    to_currency: str,
    start: datetime.date,
    end: datetime.date,
) -> pd.Series:
    """Fetch daily FX rates. Returns Series of 1.0 if same currency."""
    if from_currency.upper() == to_currency.upper():
        idx = pd.bdate_range(start, end).date
        return pd.Series(1.0, index=idx)

    pair = f"{from_currency.upper()}{to_currency.upper()}"
    return _fetch_historical_prices(f"{pair}=X", start, end)


def _get_fx_rate_on_date(
    from_currency: str,
    to_currency: str,
    target_date: datetime.date,
) -> float:
    """Fetch the FX rate on a specific date (for fixed cost basis).

    Looks at a small window around the target date to handle weekends
    and holidays, returns the closest available rate.
    """
    if from_currency.upper() == to_currency.upper():
        return 1.0

    start = target_date - datetime.timedelta(days=7)
    end = target_date + datetime.timedelta(days=1)
    series = _fetch_historical_fx_rate(from_currency, to_currency, start, end)

    if series.empty:
        raise ValueError(
            f"Cannot fetch FX rate for {from_currency}/{to_currency} "
            f"around {target_date}"
        )

    valid = series[series.index <= target_date]
    if valid.empty:
        return float(series.iloc[0])
    return float(valid.iloc[-1])


# ---------------------------------------------------------------------------
# Main computation
# ---------------------------------------------------------------------------

def compute_performance(
    positions: list[dict],
    period: str = "ALL",
) -> PerformanceResult:
    """Compute daily portfolio performance over the selected period.

    Parameters
    ----------
    positions:
        Raw position dicts from portfolio.yaml. Must contain:
        ``ticker``, ``qty``, ``avg_price``, ``currency``, ``purchase_date``.
    period:
        One of "1M", "3M", "6M", "1Y", "YTD", "ALL".

    Returns
    -------
    PerformanceResult
        Daily performance snapshots with P&L % and drawdown %.
    """
    today = datetime.date.today()

    # Parse purchase dates
    for pos in positions:
        pd_str = pos.get("purchase_date")
        if isinstance(pd_str, str):
            pos["_purchase_date"] = datetime.date.fromisoformat(pd_str)
        elif isinstance(pd_str, datetime.date):
            pos["_purchase_date"] = pd_str
        else:
            pos["_purchase_date"] = today

    earliest = min(p["_purchase_date"] for p in positions)
    start = _resolve_start_date(period, earliest, today)
    end = today

    # --- Fixed cost basis in EUR for each position ---
    cost_bases_eur: dict[str, float] = {}
    for pos in positions:
        currency = pos.get("currency", BASE_CURRENCY)
        fx_at_purchase = _get_fx_rate_on_date(
            currency, BASE_CURRENCY, pos["_purchase_date"]
        )
        cost_bases_eur[pos["ticker"]] = pos["qty"] * pos["avg_price"] * fx_at_purchase

    # --- Fetch historical price series for each ticker ---
    price_series: dict[str, pd.Series] = {}
    for pos in positions:
        price_series[pos["ticker"]] = _fetch_historical_prices(
            pos["ticker"], start, end
        )

    # --- Fetch historical FX rates for non-EUR currencies ---
    currencies_needed = {
        pos.get("currency", BASE_CURRENCY).upper()
        for pos in positions
        if pos.get("currency", BASE_CURRENCY).upper() != BASE_CURRENCY.upper()
    }
    fx_series: dict[str, pd.Series] = {}
    for ccy in currencies_needed:
        fx_series[ccy] = _fetch_historical_fx_rate(ccy, BASE_CURRENCY, start, end)

    # --- Build union of all trading dates ---
    all_dates: set[datetime.date] = set()
    for s in price_series.values():
        all_dates.update(s.index)
    trading_dates = sorted(d for d in all_dates if d >= start)

    if not trading_dates:
        return PerformanceResult(
            period=period,
            start_date=start.isoformat(),
            end_date=end.isoformat(),
        )

    # --- Compute daily portfolio value and drawdown ---
    daily_results: list[DailyPerformance] = []
    running_peak = 0.0

    for date in trading_dates:
        portfolio_value = 0.0
        total_cost = 0.0

        for pos in positions:
            if date < pos["_purchase_date"]:
                continue

            ticker = pos["ticker"]
            currency = pos.get("currency", BASE_CURRENCY).upper()

            # Get price (forward-fill from last available)
            prices = price_series.get(ticker, pd.Series(dtype=float))
            available = prices[prices.index <= date]
            if available.empty:
                continue
            close_price = float(available.iloc[-1])

            # Get FX rate (forward-fill)
            if currency == BASE_CURRENCY.upper():
                fx_rate = 1.0
            else:
                fx = fx_series.get(currency, pd.Series(dtype=float))
                fx_available = fx[fx.index <= date]
                if fx_available.empty:
                    continue
                fx_rate = float(fx_available.iloc[-1])

            portfolio_value += pos["qty"] * close_price * fx_rate
            total_cost += cost_bases_eur[ticker]

        if total_cost == 0:
            continue

        pnl_eur = portfolio_value - total_cost
        pnl_pct = (pnl_eur / total_cost) * 100

        if portfolio_value > running_peak:
            running_peak = portfolio_value
        drawdown_pct = (
            (portfolio_value - running_peak) / running_peak * 100
            if running_peak > 0
            else 0.0
        )

        daily_results.append(DailyPerformance(
            date=date.isoformat(),
            portfolio_value_eur=round(portfolio_value, 2),
            cost_basis_eur=round(total_cost, 2),
            pnl_eur=round(pnl_eur, 2),
            pnl_pct=round(pnl_pct, 2),
            drawdown_pct=round(drawdown_pct, 2),
        ))

    return PerformanceResult(
        daily=daily_results,
        period=period,
        start_date=start.isoformat(),
        end_date=end.isoformat(),
    )
