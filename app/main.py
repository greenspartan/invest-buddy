from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import init_db, get_db
from app.holdings import compute_top_holdings
from app.macro import compute_macro_outlook
from app.performance import compute_performance, PERIODS
from app.sectors import compute_sector_exposure
from app.target import load_target_portfolio, compute_drift
from app.models import Position
from app.portfolio import load_portfolio, load_transactions, aggregate_positions, enrich_positions


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Invest Buddy", lifespan=lifespan)


def _load_aggregated() -> list[dict]:
    """Load positions + transactions and return aggregated positions."""
    return aggregate_positions(load_portfolio(), load_transactions())


@app.get("/portfolio")
def get_portfolio(db: Session = Depends(get_db)):
    aggregated = _load_aggregated()
    enriched = enrich_positions(aggregated)

    # Persist to database
    db.query(Position).delete()
    for pos in enriched:
        db.add(Position(**pos))
    db.commit()

    # Compute totals per account (in EUR)
    accounts: dict[str, dict] = {}
    for pos in enriched:
        acct = pos["account"]
        if acct not in accounts:
            accounts[acct] = {"cost_basis": 0.0, "market_value": 0.0}
        if pos["cost_basis_eur"] is not None:
            accounts[acct]["cost_basis"] += pos["cost_basis_eur"]
        if pos["market_value_eur"] is not None:
            accounts[acct]["market_value"] += pos["market_value_eur"]

    totals_by_account = {}
    for acct, vals in accounts.items():
        pnl = round(vals["market_value"] - vals["cost_basis"], 2)
        pnl_pct = round((pnl / vals["cost_basis"]) * 100, 2) if vals["cost_basis"] != 0 else 0.0
        totals_by_account[acct] = {
            "cost_basis": round(vals["cost_basis"], 2),
            "market_value": round(vals["market_value"], 2),
            "pnl": pnl,
            "pnl_pct": pnl_pct,
        }

    # Global totals (in EUR)
    total_cost = sum(v["cost_basis"] for v in totals_by_account.values())
    total_mv = sum(v["market_value"] for v in totals_by_account.values())
    total_pnl = round(total_mv - total_cost, 2)
    total_pnl_pct = round((total_pnl / total_cost) * 100, 2) if total_cost != 0 else 0.0

    return {
        "positions": enriched,
        "totals_by_account": totals_by_account,
        "total": {
            "cost_basis": round(total_cost, 2),
            "market_value": round(total_mv, 2),
            "pnl": total_pnl,
            "pnl_pct": total_pnl_pct,
        },
    }


@app.get("/holdings/top")
def get_top_holdings(top_n: int = 20):
    """Top N effective holdings across the portfolio."""
    aggregated = _load_aggregated()
    enriched = enrich_positions(aggregated)
    result = compute_top_holdings(enriched, top_n=top_n)

    return {
        "top_holdings": [
            {
                "rank": i + 1,
                "symbol": h.symbol,
                "name": h.name,
                "effective_weight_pct": round(h.effective_weight * 100, 4),
                "etf_sources": h.etf_sources,
            }
            for i, h in enumerate(result.holdings)
        ],
        "meta": {
            "etfs_analyzed": result.etfs_analyzed,
            "etfs_no_data": result.etfs_no_data,
            "portfolio_coverage_pct": round(result.portfolio_coverage * 100, 2),
        },
    }


@app.get("/sectors")
def get_sectors():
    """Sector exposure across the portfolio."""
    aggregated = _load_aggregated()
    enriched = enrich_positions(aggregated)
    result = compute_sector_exposure(enriched)

    return {
        "sectors": [
            {
                "name": s.name,
                "weight_pct": round(s.effective_weight * 100, 2),
                "etf_sources": s.etf_sources,
            }
            for s in result.sectors
        ],
        "meta": {
            "etfs_analyzed": result.etfs_analyzed,
            "etfs_no_data": result.etfs_no_data,
            "portfolio_coverage_pct": round(result.portfolio_coverage * 100, 2),
        },
    }


@app.get("/performance")
def get_performance(period: str = "ALL"):
    """Historical portfolio performance (P&L % and drawdown over time)."""
    if period not in PERIODS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid period '{period}'. Must be one of: {', '.join(sorted(PERIODS))}",
        )
    aggregated = _load_aggregated()
    result = compute_performance(aggregated, period=period)

    return {
        "period": result.period,
        "start_date": result.start_date,
        "end_date": result.end_date,
        "data_points": len(result.daily),
        "daily": [
            {
                "date": d.date,
                "portfolio_value_eur": d.portfolio_value_eur,
                "cost_basis_eur": d.cost_basis_eur,
                "pnl_eur": d.pnl_eur,
                "pnl_pct": d.pnl_pct,
                "drawdown_pct": d.drawdown_pct,
            }
            for d in result.daily
        ],
    }


@app.get("/macro")
def get_macro(refresh: bool = False):
    """Macro economic indicators, outlook, mega-trends, plans & insights."""
    result = compute_macro_outlook(force_refresh=refresh)

    return {
        "outlook": result.outlook,
        "score": result.score,
        "last_updated": result.last_updated,
        "sources_available": result.sources_available,
        "sources_failed": result.sources_failed,
        "themes": result.themes,
        "indicators": [
            {
                "key": ind.key,
                "name": ind.name,
                "name_fr": ind.name_fr,
                "source": ind.source,
                "category": ind.category,
                "unit": ind.unit,
                "value": ind.value,
                "previous_value": ind.previous_value,
                "date": ind.date,
                "trend": ind.trend,
                "signal": ind.signal,
                "error": ind.error,
            }
            for ind in result.indicators
        ],
        "mega_trends": [
            {
                "id": mt.id,
                "name_fr": mt.name_fr,
                "force": mt.force,
                "change": mt.change,
                "catalysts": mt.catalysts,
                "etfs_sectoriels": mt.etfs_sectoriels,
                "etfs_geo": mt.etfs_geo,
                "etfs_thematiques": mt.etfs_thematiques,
                "sectors": mt.sectors,
            }
            for mt in result.mega_trends
        ],
        "investment_plans": [
            {
                "name": p.name,
                "amount": p.amount,
                "status": p.status,
                "status_detail": p.status_detail,
                "change": p.change,
                "sectors": p.sectors,
                "region": p.region,
            }
            for p in result.investment_plans
        ],
        "sell_side_views": [
            {
                "source": sv.source,
                "date": sv.date,
                "forecasts": sv.forecasts,
                "key_themes": sv.key_themes,
                "risks": sv.risks,
            }
            for sv in result.sell_side_views
        ],
        "lyn_alden_insights": [
            {
                "filename": a.filename,
                "date": a.date,
                "title": a.title,
                "key_points": a.key_points,
                "portfolio_changes": a.portfolio_changes,
            }
            for a in result.lyn_alden_insights
        ],
        "sector_signals": [
            {
                "sector": s.sector,
                "signal": s.signal,
                "supporting_trends": s.supporting_trends,
                "indicator_signals": s.indicator_signals,
            }
            for s in result.sector_signals
        ],
    }


@app.get("/target")
def get_target():
    """Target portfolio allocations."""
    result = load_target_portfolio()
    return {
        "allocations": [
            {
                "ticker": a.ticker,
                "name": a.name,
                "weight_pct": a.weight_pct,
            }
            for a in result.allocations
        ],
        "total_weight_pct": result.total_weight_pct,
    }


@app.get("/drift")
def get_drift():
    """Portfolio drift vs target allocations."""
    aggregated = _load_aggregated()
    enriched = enrich_positions(aggregated)
    target = load_target_portfolio()
    result = compute_drift(enriched, target)

    return {
        "entries": [
            {
                "ticker": e.ticker,
                "name": e.name,
                "target_pct": e.target_pct,
                "current_pct": e.current_pct,
                "drift_pct": e.drift_pct,
                "action": e.action,
                "current_value_eur": e.current_value_eur,
                "target_value_eur": e.target_value_eur,
                "rebalance_amount_eur": e.rebalance_amount_eur,
            }
            for e in result.entries
        ],
        "total_portfolio_eur": result.total_portfolio_eur,
        "max_drift_pct": result.max_drift_pct,
    }


@app.get("/health")
def health():
    return {"status": "ok"}
