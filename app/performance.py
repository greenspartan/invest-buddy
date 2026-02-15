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

@dataclass
class _Lot:
    """Internal representation of a single buy lot."""

    ticker: str
    qty: float
    price: float
    date: datetime.date
    currency: str
    cost_basis_eur: float = 0.0  # pre-computed


def _build_lots(positions: list[dict], today: datetime.date) -> list[_Lot]:
    """Convert aggregated positions (with _lots) into flat list of _Lot objects.

    If a position has no ``_lots`` key (backwards compatibility), a single
    lot is created from the position itself.
    """
    lots: list[_Lot] = []
    for pos in positions:
        ticker = pos["ticker"]
        currency = pos.get("currency", BASE_CURRENCY)
        raw_lots = pos.get("_lots")

        if raw_lots:
            for rl in raw_lots:
                date_val = rl.get("date")
                if isinstance(date_val, str):
                    lot_date = datetime.date.fromisoformat(date_val)
                elif isinstance(date_val, datetime.date):
                    lot_date = date_val
                else:
                    lot_date = today
                lots.append(_Lot(
                    ticker=ticker,
                    qty=rl["qty"],
                    price=rl["price"],
                    date=lot_date,
                    currency=currency,
                ))
        else:
            pd_str = pos.get("purchase_date")
            if isinstance(pd_str, str):
                lot_date = datetime.date.fromisoformat(pd_str)
            elif isinstance(pd_str, datetime.date):
                lot_date = pd_str
            else:
                lot_date = today
            lots.append(_Lot(
                ticker=ticker,
                qty=pos["qty"],
                price=pos["avg_price"],
                date=lot_date,
                currency=currency,
            ))

    return lots


def compute_performance(
    positions: list[dict],
    period: str = "ALL",
) -> PerformanceResult:
    """Compute daily portfolio performance over the selected period.

    Parameters
    ----------
    positions:
        Aggregated position dicts (from ``aggregate_positions``).
        Each may contain ``_lots`` (list of individual buys).
        Falls back to a single lot per position if ``_lots`` is absent.
    period:
        One of "1M", "3M", "6M", "1Y", "YTD", "ALL".

    Returns
    -------
    PerformanceResult
        Daily performance snapshots with P&L % and drawdown %.
    """
    today = datetime.date.today()

    # Build flat list of lots
    lots = _build_lots(positions, today)
    if not lots:
        return PerformanceResult(period=period)

    earliest = min(l.date for l in lots)
    start = _resolve_start_date(period, earliest, today)
    end = today

    # --- Pre-compute cost basis EUR for each lot ---
    for lot in lots:
        fx_at_purchase = _get_fx_rate_on_date(lot.currency, BASE_CURRENCY, lot.date)
        lot.cost_basis_eur = lot.qty * lot.price * fx_at_purchase

    # --- Fetch historical price series for each unique ticker ---
    tickers = {lot.ticker for lot in lots}
    price_series: dict[str, pd.Series] = {}
    for ticker in tickers:
        price_series[ticker] = _fetch_historical_prices(ticker, start, end)

    # --- Fetch historical FX rates for non-EUR currencies ---
    currencies_needed = {
        lot.currency.upper()
        for lot in lots
        if lot.currency.upper() != BASE_CURRENCY.upper()
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

        for lot in lots:
            # Only include lots that are active on this date
            if date < lot.date:
                continue

            currency = lot.currency.upper()

            # Get price (forward-fill from last available)
            prices = price_series.get(lot.ticker, pd.Series(dtype=float))
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

            portfolio_value += lot.qty * close_price * fx_rate
            total_cost += lot.cost_basis_eur

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
