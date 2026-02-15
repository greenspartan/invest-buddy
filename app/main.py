from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session

from app.database import init_db, get_db
from app.holdings import compute_top_holdings
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

    # Compute totals per account
    accounts: dict[str, dict] = {}
    for pos in enriched:
        acct = pos["account"]
        if acct not in accounts:
            accounts[acct] = {"cost_basis": 0.0, "market_value": 0.0}
        accounts[acct]["cost_basis"] += pos["avg_price"] * pos["qty"]
        if pos["market_value"] is not None:
            accounts[acct]["market_value"] += pos["market_value"]

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

    # Global totals
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


@app.get("/health")
def health():
    return {"status": "ok"}
