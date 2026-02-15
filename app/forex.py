"""Exchange rate fetching and currency conversion.

This module is self-contained: it depends only on yfinance and the
standard library, so it can be reused by any script that needs
forex data.
"""

from __future__ import annotations

import yfinance as yf

# Module-level cache: populated once per process lifetime, cleared on restart.
_rate_cache: dict[str, float] = {}


def get_exchange_rate(from_currency: str, to_currency: str) -> float:
    """Return the exchange rate *from_currency* -> *to_currency*.

    Uses yfinance forex tickers (e.g. ``USDEUR=X``).
    Results are cached in memory so repeated calls for the same pair
    within the same process are free.

    Returns 1.0 when *from_currency* == *to_currency*.
    """
    from_currency = from_currency.upper()
    to_currency = to_currency.upper()

    if from_currency == to_currency:
        return 1.0

    pair = f"{from_currency}{to_currency}"
    if pair in _rate_cache:
        return _rate_cache[pair]

    ticker = yf.Ticker(f"{pair}=X")
    rate = ticker.fast_info.get("lastPrice")
    if rate is None:
        raise ValueError(f"Cannot fetch exchange rate for {pair}=X")

    _rate_cache[pair] = float(rate)
    # Also cache the inverse to avoid an extra API call.
    _rate_cache[f"{to_currency}{from_currency}"] = 1.0 / float(rate)

    return float(rate)


def convert(amount: float, from_currency: str, to_currency: str) -> float:
    """Convert *amount* from one currency to another."""
    return amount * get_exchange_rate(from_currency, to_currency)
