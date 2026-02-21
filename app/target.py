"""Target portfolio allocation and drift computation.

Supports two modes:
- static: reads target_portfolio.yaml (manual weights)
- smart: accepts a SmartAllocationResult from allocation.py (macro-derived weights)

Drift computation is mode-agnostic (works with any TargetPortfolioResult).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import yaml

from app.config import TARGET_PATH

if TYPE_CHECKING:
    from app.allocation import SmartAllocationResult


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TargetAllocation:
    ticker: str
    name: str
    weight_pct: float


@dataclass
class TargetPortfolioResult:
    allocations: list[TargetAllocation] = field(default_factory=list)
    total_weight_pct: float = 0.0


@dataclass
class DriftEntry:
    ticker: str
    name: str
    target_pct: float
    current_pct: float
    drift_pct: float
    action: str  # "BUY", "SELL", "HOLD"
    current_value_eur: float
    target_value_eur: float
    rebalance_amount_eur: float  # positive = buy, negative = sell


@dataclass
class DriftResult:
    entries: list[DriftEntry] = field(default_factory=list)
    total_portfolio_eur: float = 0.0
    max_drift_pct: float = 0.0


# ---------------------------------------------------------------------------
# Target loading
# ---------------------------------------------------------------------------

def _load_static_target() -> TargetPortfolioResult:
    """Load target_portfolio.yaml and return parsed allocations (static mode)."""
    if not os.path.exists(TARGET_PATH):
        return TargetPortfolioResult()

    with open(TARGET_PATH, "r") as f:
        data = yaml.safe_load(f) or {}

    raw = data.get("target_allocations", []) or []
    allocations = [
        TargetAllocation(
            ticker=entry["ticker"],
            name=entry.get("name", entry["ticker"]),
            weight_pct=float(entry["weight_pct"]),
        )
        for entry in raw
    ]
    total = sum(a.weight_pct for a in allocations)

    return TargetPortfolioResult(
        allocations=allocations,
        total_weight_pct=round(total, 2),
    )


def load_target_portfolio(
    smart_allocation: SmartAllocationResult | None = None,
) -> TargetPortfolioResult:
    """Load target allocations (smart or static).

    If smart_allocation is provided and has allocations, use it.
    Otherwise, fall back to static target_portfolio.yaml.
    """
    if smart_allocation and smart_allocation.allocations:
        allocations = [
            TargetAllocation(
                ticker=a.ticker,
                name=a.name,
                weight_pct=a.weight_pct,
            )
            for a in smart_allocation.allocations
        ]
        total = sum(a.weight_pct for a in allocations)
        return TargetPortfolioResult(
            allocations=allocations,
            total_weight_pct=round(total, 2),
        )

    return _load_static_target()


# ---------------------------------------------------------------------------
# Drift computation
# ---------------------------------------------------------------------------

DRIFT_THRESHOLD = 2.0  # percent


def compute_drift(
    enriched_positions: list[dict],
    target: TargetPortfolioResult,
) -> DriftResult:
    """Compare live portfolio weights vs target weights.

    Parameters
    ----------
    enriched_positions:
        Enriched position dicts (from enrich_positions()), each with
        at least 'ticker' and 'market_value_eur' keys.
    target:
        Parsed target portfolio.

    Returns
    -------
    DriftResult with drift per ticker and rebalance suggestions.
    """
    if not target.allocations:
        return DriftResult()

    # Aggregate live market values by ticker (across accounts)
    valid = [p for p in enriched_positions if p.get("market_value_eur") is not None]
    total_mv = sum(p["market_value_eur"] for p in valid)
    if total_mv == 0:
        return DriftResult()

    live_by_ticker: dict[str, float] = {}
    for p in valid:
        t = p["ticker"]
        live_by_ticker[t] = live_by_ticker.get(t, 0.0) + p["market_value_eur"]

    live_weights = {t: (mv / total_mv) * 100 for t, mv in live_by_ticker.items()}

    target_tickers = {a.ticker for a in target.allocations}
    entries: list[DriftEntry] = []

    # Process all tickers in target
    for alloc in target.allocations:
        current_pct = live_weights.get(alloc.ticker, 0.0)
        drift = current_pct - alloc.weight_pct
        current_val = live_by_ticker.get(alloc.ticker, 0.0)
        target_val = total_mv * alloc.weight_pct / 100.0
        rebalance = target_val - current_val

        if drift < -DRIFT_THRESHOLD:
            action = "BUY"
        elif drift > DRIFT_THRESHOLD:
            action = "SELL"
        else:
            action = "HOLD"

        entries.append(DriftEntry(
            ticker=alloc.ticker,
            name=alloc.name,
            target_pct=round(alloc.weight_pct, 2),
            current_pct=round(current_pct, 2),
            drift_pct=round(drift, 2),
            action=action,
            current_value_eur=round(current_val, 2),
            target_value_eur=round(target_val, 2),
            rebalance_amount_eur=round(rebalance, 2),
        ))

    # Handle positions in live but NOT in target -> suggest SELL
    for ticker, mv in live_by_ticker.items():
        if ticker not in target_tickers:
            current_pct = live_weights[ticker]
            entries.append(DriftEntry(
                ticker=ticker,
                name=ticker,
                target_pct=0.0,
                current_pct=round(current_pct, 2),
                drift_pct=round(current_pct, 2),
                action="SELL",
                current_value_eur=round(mv, 2),
                target_value_eur=0.0,
                rebalance_amount_eur=round(-mv, 2),
            ))

    max_drift = max(abs(e.drift_pct) for e in entries) if entries else 0.0

    return DriftResult(
        entries=entries,
        total_portfolio_eur=round(total_mv, 2),
        max_drift_pct=round(max_drift, 2),
    )
