"""Smart allocation engine: derives target theme weights from macro signals.

Reads macro_config.yaml (allocation_themes) and MacroOutlook (mega-trends,
sector signals, risk outlook) to compute theme allocation scores.
Each theme gets a weight and a rationale in French.

The user then maps themes to specific ETFs in target_portfolio.yaml.

Does NOT depend on models.py/PostgreSQL. Pure computation module.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.macro import MacroOutlook, MegaTrend, SectorSignal


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ThemeAllocation:
    id: str
    name_fr: str
    type: str  # "thematique", "geo", "secteur"
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
    themes: list[ThemeAllocation] = field(default_factory=list)
    total_weight_pct: float = 0.0
    outlook: str = ""
    score: float = 0.0
    method: str = "smart"
    generation_date: str = ""


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

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
    theme_sectors: list[str],
    sector_signals: list[SectorSignal],
) -> float:
    """Adjust score based on sector signals (bullish +1, bearish -1)."""
    if not theme_sectors:
        return 0.0

    signal_map = {s.sector: s.signal for s in sector_signals}
    adjustments = []
    for sector in theme_sectors:
        sig = signal_map.get(sector, "neutral")
        if sig == "bullish":
            adjustments.append(1.0)
        elif sig == "bearish":
            adjustments.append(-1.0)
        else:
            adjustments.append(0.0)

    return sum(adjustments) / len(adjustments) if adjustments else 0.0


def _compute_risk_adjustment(theme_type: str, outlook_score: float) -> float:
    """Adjust based on overall risk outlook.

    risk-on boosts thematic/sector, risk-off penalizes them.
    """
    multipliers = {"thematique": 1.5, "secteur": 1.0, "geo": 0.5}
    return outlook_score * multipliers.get(theme_type, 0.5)


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

MIN_WEIGHT = 5.0
MAX_WEIGHT = 25.0
MAX_THEMES = 12
SCORE_THRESHOLD = 1.0  # minimum total_score to be included


def _normalize_to_weights(themes: list[ThemeAllocation]) -> None:
    """Convert raw scores to % weights summing to 100.

    Filters by SCORE_THRESHOLD, limits to MAX_THEMES, applies min/max constraints.
    """
    eligible = sorted(
        [t for t in themes if t.total_score >= SCORE_THRESHOLD],
        key=lambda t: t.total_score,
        reverse=True,
    )
    active = eligible[:MAX_THEMES]
    if not active:
        return

    total_score = sum(t.total_score for t in active)

    for t in active:
        t.weight_pct = (t.total_score / total_score) * 100

    # Iterative min/max clamping
    for _ in range(10):
        changed = False
        for t in active:
            if t.weight_pct > MAX_WEIGHT:
                t.weight_pct = MAX_WEIGHT
                changed = True
            elif t.weight_pct < MIN_WEIGHT:
                t.weight_pct = MIN_WEIGHT
                changed = True
        if not changed:
            break
        total = sum(t.weight_pct for t in active)
        if total > 0:
            factor = 100.0 / total
            for t in active:
                t.weight_pct = round(t.weight_pct * factor, 1)

    # Final adjustment to sum exactly to 100
    total = sum(t.weight_pct for t in active)
    if total > 0 and abs(total - 100.0) > 0.05:
        diff = 100.0 - total
        active[0].weight_pct = round(active[0].weight_pct + diff, 1)

    # Assign 0 to excluded
    active_ids = {t.id for t in active}
    for t in themes:
        if t.id not in active_ids:
            t.weight_pct = 0.0


# ---------------------------------------------------------------------------
# Rationale generation
# ---------------------------------------------------------------------------

def _generate_rationale(theme: ThemeAllocation) -> str:
    """Build a human-readable French rationale."""
    parts = []

    if theme.supporting_trends:
        names = theme.supporting_trends
        if len(names) <= 3:
            parts.append(f"Soutenu par {', '.join(names)}")
        else:
            parts.append(f"Soutenu par {', '.join(names[:3])} (+{len(names) - 3} autres)")

    if theme.trend_score > 0:
        parts.append(f"score tendances: {theme.trend_score:.1f}")

    if theme.sector_adjustment > 0.3:
        parts.append("secteurs favorables")
    elif theme.sector_adjustment < -0.3:
        parts.append("secteurs defavorables")

    if theme.risk_adjustment > 0.3:
        parts.append("contexte risk-on")
    elif theme.risk_adjustment < -0.3:
        parts.append("contexte risk-off")

    return ". ".join(parts) + "." if parts else "Diversification."


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def compute_smart_allocation(
    macro_outlook: MacroOutlook,
    allocation_themes: list[dict],
) -> SmartAllocationResult:
    """Compute theme-based allocation from macro signals.

    Args:
        macro_outlook: Full macro outlook with indicators, mega-trends, sector signals
        allocation_themes: List of theme dicts from macro_config.yaml

    Returns:
        SmartAllocationResult with scored theme allocations and rationales
    """
    if not allocation_themes or not macro_outlook.mega_trends:
        return SmartAllocationResult(
            method="smart",
            outlook=macro_outlook.outlook,
            score=macro_outlook.score,
            generation_date=macro_outlook.last_updated,
        )

    # Build mega-trend lookup by ID
    mt_by_id = {mt.id: mt for mt in macro_outlook.mega_trends}

    themes = []
    for cfg in allocation_themes:
        t = ThemeAllocation(
            id=cfg["id"],
            name_fr=cfg["name_fr"],
            type=cfg.get("type", "thematique"),
            sectors=cfg.get("sectors", []),
        )

        # Find supporting mega-trends by ID
        supporting_ids = cfg.get("supporting_mega_trends", [])
        supporting = [mt_by_id[mid] for mid in supporting_ids if mid in mt_by_id]

        # Trend score
        t.trend_score = _compute_trend_score(supporting)
        t.supporting_trends = [mt.name_fr for mt in supporting]

        # Sector adjustment
        t.sector_adjustment = _compute_sector_adjustment(
            t.sectors, macro_outlook.sector_signals
        )

        # Risk adjustment
        t.risk_adjustment = _compute_risk_adjustment(
            t.type, macro_outlook.score
        )

        # Total score
        t.total_score = max(
            t.trend_score + t.sector_adjustment + t.risk_adjustment,
            0.0,
        )

        themes.append(t)

    # Normalize to 100%
    _normalize_to_weights(themes)

    # Generate rationales
    for t in themes:
        t.rationale = _generate_rationale(t)

    # Filter and sort
    active = sorted(
        [t for t in themes if t.weight_pct > 0],
        key=lambda t: t.weight_pct,
        reverse=True,
    )

    return SmartAllocationResult(
        themes=active,
        total_weight_pct=round(sum(t.weight_pct for t in active), 1),
        outlook=macro_outlook.outlook,
        score=macro_outlook.score,
        method="smart",
        generation_date=macro_outlook.last_updated,
    )
