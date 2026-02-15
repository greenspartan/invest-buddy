from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import init_db, get_db
from app.holdings import compute_top_holdings
from app.performance import compute_performance, PERIODS
from app.sectors import compute_sector_exposure
from app.models import Position
from app.portfolio import load_portfolio, enrich_positions


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Invest Buddy", lifespan=lifespan)


@app.get("/portfolio")
def get_portfolio(db: Session = Depends(get_db)):
    positions = load_portfolio()
    enriched = enrich_positions(positions)

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
    positions = load_portfolio()
    enriched = enrich_positions(positions)
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
    positions = load_portfolio()
    enriched = enrich_positions(positions)
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
    positions = load_portfolio()
    result = compute_performance(positions, period=period)

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


@app.get("/health")
def health():
    return {"status": "ok"}
