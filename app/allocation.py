"""Smart allocation engine: derives target ETF weights from macro signals.

Reads macro_config.yaml (etf_universe) and MacroOutlook (mega-trends,
sector signals, risk outlook) to compute ETF allocation scores.
Each ETF gets a weight and a rationale in French.

Does NOT depend on models.py/PostgreSQL. Pure computation module.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.macro import MacroOutlook, MegaTrend, SectorSignal


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ETFCandidate:
    short: str
    ticker: str
    name: str
    type: str  # "secteur", "geo", "thematique"
    sectors: list[str] = field(default_factory=list)
    trend_score: float = 0.0
    sector_adjustment: float = 0.0
    risk_adjustment: float = 0.0
    total_score: float = 0.0
    weight_pct: float = 0.0
    supporting_trends: list[str] = field(default_factory=list)
    rationale: str = ""


@dataclass
class SmartAllocationResult:
    allocations: list[ETFCandidate] = field(default_factory=list)
    total_weight_pct: float = 0.0
    outlook: str = ""
    score: float = 0.0
    method: str = "smart"
    generation_date: str = ""


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def _build_etf_trend_map(
    universe: list[dict],
    mega_trends: list[MegaTrend],
) -> dict[str, list[MegaTrend]]:
    """Map each ETF short ticker to its supporting mega-trends."""
    etf_trends: dict[str, list[MegaTrend]] = {}

    for etf in universe:
        short = etf["short"]
        aliases = {short} | set(etf.get("aliases", []))
        supporting = []
        for mt in mega_trends:
            all_etfs = set(mt.etfs_sectoriels + mt.etfs_geo + mt.etfs_thematiques)
            if aliases & all_etfs:
                supporting.append(mt)
        etf_trends[short] = supporting

    return etf_trends


def _compute_trend_score(trends: list[MegaTrend]) -> float:
    """Sum of force values from supporting mega-trends.

    Change modifier: "up" = +0.5, "down" = -0.5.
    """
    score = 0.0
    for mt in trends:
        base = float(mt.force)
        if mt.change == "up":
            base += 0.5
        elif mt.change == "down":
            base -= 0.5
        score += max(base, 0)
    return score


def _compute_sector_adjustment(
    etf_sectors: list[str],
    sector_signals: list[SectorSignal],
) -> float:
    """Adjust score based on sector signals (bullish +1, bearish -1)."""
    if not etf_sectors:
        return 0.0

    signal_map = {s.sector: s.signal for s in sector_signals}
    adjustments = []
    for sector in etf_sectors:
        sig = signal_map.get(sector, "neutral")
        if sig == "bullish":
            adjustments.append(1.0)
        elif sig == "bearish":
            adjustments.append(-1.0)
        else:
            adjustments.append(0.0)

    return sum(adjustments) / len(adjustments) if adjustments else 0.0


def _compute_risk_adjustment(etf_type: str, outlook_score: float) -> float:
    """Adjust based on overall risk outlook.

    risk-on boosts thematic/sector, risk-off penalizes them.
    """
    multipliers = {"thematique": 1.5, "secteur": 1.0, "geo": 0.5}
    return outlook_score * multipliers.get(etf_type, 0.5)


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

MIN_WEIGHT = 4.0
MAX_WEIGHT = 25.0
MAX_ETFS = 10
SCORE_THRESHOLD = 2.0  # minimum total_score to be included


def _normalize_to_weights(candidates: list[ETFCandidate]) -> None:
    """Convert raw scores to % weights summing to 100.

    Filters by SCORE_THRESHOLD, limits to MAX_ETFS, applies min/max constraints.
    """
    # Filter by score threshold and limit count
    eligible = sorted(
        [c for c in candidates if c.total_score >= SCORE_THRESHOLD],
        key=lambda c: c.total_score,
        reverse=True,
    )
    active = eligible[:MAX_ETFS]
    if not active:
        return

    total_score = sum(c.total_score for c in active)

    for c in active:
        c.weight_pct = (c.total_score / total_score) * 100

    # Iterative min/max clamping
    for _ in range(10):
        changed = False
        for c in active:
            if c.weight_pct > MAX_WEIGHT:
                c.weight_pct = MAX_WEIGHT
                changed = True
            elif c.weight_pct < MIN_WEIGHT:
                c.weight_pct = MIN_WEIGHT
                changed = True
        if not changed:
            break
        # Re-normalize
        total = sum(c.weight_pct for c in active)
        if total > 0:
            factor = 100.0 / total
            for c in active:
                c.weight_pct = round(c.weight_pct * factor, 1)

    # Final adjustment to sum exactly to 100
    total = sum(c.weight_pct for c in active)
    if total > 0 and abs(total - 100.0) > 0.05:
        diff = 100.0 - total
        # Adjust the largest allocation to absorb rounding error
        active[0].weight_pct = round(active[0].weight_pct + diff, 1)

    # Assign 0 to excluded
    active_shorts = {c.short for c in active}
    for c in candidates:
        if c.short not in active_shorts:
            c.weight_pct = 0.0


# ---------------------------------------------------------------------------
# Rationale generation
# ---------------------------------------------------------------------------

def _generate_rationale(candidate: ETFCandidate) -> str:
    """Build a human-readable French rationale."""
    parts = []

    if candidate.supporting_trends:
        names = candidate.supporting_trends
        if len(names) <= 3:
            parts.append(f"Soutenu par {', '.join(names)}")
        else:
            parts.append(f"Soutenu par {', '.join(names[:3])} (+{len(names) - 3} autres)")

    if candidate.trend_score > 0:
        parts.append(f"score tendances: {candidate.trend_score:.1f}")

    if candidate.sector_adjustment > 0.3:
        parts.append("secteurs favorables")
    elif candidate.sector_adjustment < -0.3:
        parts.append("secteurs defavorables")

    if candidate.risk_adjustment > 0.3:
        parts.append("contexte risk-on")
    elif candidate.risk_adjustment < -0.3:
        parts.append("contexte risk-off")

    return ". ".join(parts) + "." if parts else "Diversification."


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def compute_smart_allocation(
    macro_outlook: MacroOutlook,
    etf_universe: list[dict],
) -> SmartAllocationResult:
    """Compute ETF allocation from macro signals.

    Args:
        macro_outlook: Full macro outlook with indicators, mega-trends, sector signals
        etf_universe: List of ETF dicts from macro_config.yaml etf_universe section

    Returns:
        SmartAllocationResult with scored allocations and rationales
    """
    if not etf_universe or not macro_outlook.mega_trends:
        return SmartAllocationResult(
            method="smart",
            outlook=macro_outlook.outlook,
            score=macro_outlook.score,
            generation_date=macro_outlook.last_updated,
        )

    etf_trend_map = _build_etf_trend_map(etf_universe, macro_outlook.mega_trends)

    candidates = []
    for etf_cfg in etf_universe:
        c = ETFCandidate(
            short=etf_cfg["short"],
            ticker=etf_cfg["ticker"],
            name=etf_cfg["name"],
            type=etf_cfg.get("type", "thematique"),
            sectors=etf_cfg.get("sectors", []),
        )

        # Trend score
        supporting = etf_trend_map.get(c.short, [])
        c.trend_score = _compute_trend_score(supporting)
        c.supporting_trends = [mt.name_fr for mt in supporting]

        # Sector adjustment
        c.sector_adjustment = _compute_sector_adjustment(
            c.sectors, macro_outlook.sector_signals
        )

        # Risk adjustment
        c.risk_adjustment = _compute_risk_adjustment(
            c.type, macro_outlook.score
        )

        # Geo base weight (ensures broad diversification)
        base_weight = 1.0 if c.type == "geo" else 0.0

        # Total score
        c.total_score = max(
            c.trend_score + c.sector_adjustment + c.risk_adjustment + base_weight,
            0.0,
        )

        candidates.append(c)

    # Normalize to 100%
    _normalize_to_weights(candidates)

    # Generate rationales
    for c in candidates:
        c.rationale = _generate_rationale(c)

    # Filter and sort
    active = sorted(
        [c for c in candidates if c.weight_pct > 0],
        key=lambda c: c.weight_pct,
        reverse=True,
    )

    return SmartAllocationResult(
        allocations=active,
        total_weight_pct=round(sum(c.weight_pct for c in active), 1),
        outlook=macro_outlook.outlook,
        score=macro_outlook.score,
        method="smart",
        generation_date=macro_outlook.last_updated,
    )
