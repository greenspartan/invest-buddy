"""Macro economic indicators dashboard.

Self-contained module that fetches macro indicators from multiple sources:
- FRED API (US: CPI, Core CPI, Unemployment, Fed Funds, ISM, Yield Curve,
  Fed Balance Sheet, Initial Claims, Consumer Sentiment, HY Spread, GDP)
- yfinance (market: US 10Y yield, VIX, EUR/USD, DXY, Gold, BTC, Copper, Oil)
- ECB Data Portal (EU: Main Refi Rate, EUR CPI HICP)
- RSS feeds (news from Reuters, Les Echos, Zone Bourse, Investing.com, BCE, Fed)

Additional context loaded from local files:
- macro_config.yaml: mega-trends, investment plans, sell-side views, news sources, ETF universe
- context/macro/Lyn Alden/*.md: Lyn Alden premium article summaries
- context/macro/sell-side/*.md: sell-side research summaries (JPMorgan, BofA)

Results are cached in macro_outlook.yaml (valid 6 hours).
News feed cached separately in news_cache.yaml (valid 30 min).
"""

from __future__ import annotations

import csv
import datetime
import glob as glob_mod
import io
import os
import re
from dataclasses import dataclass, field
from typing import Optional

import feedparser
import requests
import yaml
import yfinance as yf

from app.config import FRED_API_KEY, MACRO_CONFIG_PATH, LYN_ALDEN_DIR, SELL_SIDE_DIR


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MACRO_OUTLOOK_PATH = "macro_outlook.yaml"
NEWS_CACHE_PATH = "news_cache.yaml"
CACHE_TTL_SECONDS = 6 * 3600  # 6 hours
NEWS_CACHE_TTL_SECONDS = 30 * 60  # 30 minutes

FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"
ECB_BASE_URL = "https://data-api.ecb.europa.eu/service/data"

# FRED series definitions
FRED_INDICATORS = {
    "us_cpi": {
        "series_id": "CPIAUCSL",
        "name": "US CPI (All Items YoY)",
        "name_fr": "IPC US (tous postes, GA)",
        "unit": "%",
        "category": "inflation",
        "extra_params": {"units": "pc1"},
    },
    "us_core_cpi": {
        "series_id": "CPILFESL",
        "name": "US Core CPI (YoY)",
        "name_fr": "IPC Core US (GA)",
        "unit": "%",
        "category": "inflation",
        "extra_params": {"units": "pc1"},
    },
    "us_unemployment": {
        "series_id": "UNRATE",
        "name": "US Unemployment Rate",
        "name_fr": "Taux de chomage US",
        "unit": "%",
        "category": "employment",
        "extra_params": {},
    },
    "fed_funds": {
        "series_id": "FEDFUNDS",
        "name": "Fed Funds Rate",
        "name_fr": "Taux directeur Fed",
        "unit": "%",
        "category": "rates",
        "extra_params": {},
    },
    "ism_manufacturing": {
        "series_id": "IPMAN",
        "name": "Industrial Production: Manufacturing",
        "name_fr": "Production Industrielle Manufacturiere",
        "unit": "Index",
        "category": "activity",
        "extra_params": {},
    },
    "yield_curve": {
        "series_id": "T10Y2Y",
        "name": "US Yield Curve (10Y-2Y Spread)",
        "name_fr": "Courbe de taux US (10A-2A)",
        "unit": "%",
        "category": "rates",
        "extra_params": {},
    },
    "fed_balance_sheet": {
        "series_id": "WALCL",
        "name": "Fed Balance Sheet (Total Assets)",
        "name_fr": "Bilan Fed (Actifs totaux)",
        "unit": "Mrd$",
        "category": "monetary",
        "extra_params": {},
    },
    "initial_claims": {
        "series_id": "ICSA",
        "name": "Initial Jobless Claims",
        "name_fr": "Inscriptions chomage initiales",
        "unit": "K",
        "category": "employment",
        "extra_params": {},
    },
    "consumer_sentiment": {
        "series_id": "UMCSENT",
        "name": "UMich Consumer Sentiment",
        "name_fr": "Sentiment consommateurs (UMich)",
        "unit": "Index",
        "category": "sentiment",
        "extra_params": {},
    },
    "hy_spread": {
        "series_id": "BAMLH0A0HYM2",
        "name": "US HY Credit Spread (OAS)",
        "name_fr": "Spread credit HY US (OAS)",
        "unit": "bp",
        "category": "credit",
        "extra_params": {},
    },
    "gdp": {
        "series_id": "GDP",
        "name": "US GDP (Quarterly)",
        "name_fr": "PIB US (trimestriel)",
        "unit": "Mrd$",
        "category": "activity",
        "extra_params": {},
    },
}

# ECB Data Portal series definitions
ECB_INDICATORS = {
    "ecb_refi_rate": {
        "flow_ref": "FM",
        "key": "B.U2.EUR.4F.KR.MRR.LEV",
        "name": "ECB Main Refinancing Rate",
        "name_fr": "Taux refi BCE",
        "unit": "%",
        "category": "rates",
    },
    "eur_cpi": {
        "flow_ref": "ICP",
        "key": "M.U2.N.000000.4.ANR",
        "name": "Eurozone HICP (YoY)",
        "name_fr": "IPC Zone Euro (IPCH GA)",
        "unit": "%",
        "category": "inflation",
    },
}

# yfinance market indicators
YFINANCE_INDICATORS = {
    "us_10y": {
        "ticker": "^TNX",
        "name": "US 10Y Treasury Yield",
        "name_fr": "Rendement US 10 ans",
        "unit": "%",
        "category": "rates",
    },
    "vix": {
        "ticker": "^VIX",
        "name": "VIX (Volatility Index)",
        "name_fr": "VIX (Indice de volatilite)",
        "unit": "Index",
        "category": "sentiment",
    },
    "eurusd": {
        "ticker": "EURUSD=X",
        "name": "EUR/USD",
        "name_fr": "EUR/USD",
        "unit": "Rate",
        "category": "forex",
    },
    "dxy": {
        "ticker": "DX-Y.NYB",
        "name": "US Dollar Index (DXY)",
        "name_fr": "Indice Dollar US (DXY)",
        "unit": "Index",
        "category": "forex",
    },
    "gold": {
        "ticker": "GC=F",
        "name": "Gold (USD/oz)",
        "name_fr": "Or (USD/oz)",
        "unit": "$/oz",
        "category": "commodity",
    },
    "btc": {
        "ticker": "BTC-USD",
        "name": "Bitcoin",
        "name_fr": "Bitcoin",
        "unit": "$",
        "category": "commodity",
    },
    "copper": {
        "ticker": "HG=F",
        "name": "Copper Futures",
        "name_fr": "Cuivre (Futures)",
        "unit": "$/lb",
        "category": "commodity",
    },
    "oil_wti": {
        "ticker": "CL=F",
        "name": "Oil WTI",
        "name_fr": "Petrole WTI",
        "unit": "$/bbl",
        "category": "commodity",
    },
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class MacroIndicator:
    key: str
    name: str
    name_fr: str
    source: str  # "FRED", "ECB", "yfinance"
    category: str
    unit: str
    value: Optional[float] = None
    previous_value: Optional[float] = None
    date: Optional[str] = None
    trend: Optional[str] = None  # "up", "down", "flat"
    signal: Optional[str] = None  # "bullish", "bearish", "neutral"
    error: Optional[str] = None


@dataclass
class MegaTrend:
    id: str
    name_fr: str
    force: int  # 0-3
    change: str  # "=", "up", "down"
    catalysts: list[str] = field(default_factory=list)
    etfs_sectoriels: list[str] = field(default_factory=list)
    etfs_geo: list[str] = field(default_factory=list)
    etfs_thematiques: list[str] = field(default_factory=list)
    sectors: list[str] = field(default_factory=list)


@dataclass
class InvestmentPlan:
    name: str
    amount: str
    status: str  # "active", "partial", "cut", "proposed"
    status_detail: str
    change: str  # "=", "up", "down"
    sectors: list[str] = field(default_factory=list)
    region: str = ""  # "us" or "eu"


@dataclass
class SellSideView:
    source: str
    date: str
    forecasts: dict = field(default_factory=dict)
    key_themes: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)


@dataclass
class LynAldenArticle:
    filename: str
    date: str
    title: str
    key_points: list[str] = field(default_factory=list)
    portfolio_changes: list[str] = field(default_factory=list)


@dataclass
class SectorSignal:
    sector: str
    signal: str  # "bullish", "bearish", "neutral"
    supporting_trends: list[str] = field(default_factory=list)
    indicator_signals: list[str] = field(default_factory=list)


@dataclass
class NewsItem:
    title: str
    source: str  # "Reuters", "Les Echos", etc.
    date: str  # ISO date
    url: str
    category: str  # "macro", "marches"
    summary: str = ""
    zone: str = ""  # "US", "Europe", "Tech", "Energie", "Geopolitique", "Marches", "Autre"


@dataclass
class MacroOutlook:
    outlook: str = "neutral"
    score: float = 0.0
    indicators: list[MacroIndicator] = field(default_factory=list)
    last_updated: str = ""
    sources_available: list[str] = field(default_factory=list)
    sources_failed: list[str] = field(default_factory=list)
    themes: list[str] = field(default_factory=list)
    mega_trends: list[MegaTrend] = field(default_factory=list)
    investment_plans: list[InvestmentPlan] = field(default_factory=list)
    sell_side_views: list[SellSideView] = field(default_factory=list)
    lyn_alden_insights: list[LynAldenArticle] = field(default_factory=list)
    sector_signals: list[SectorSignal] = field(default_factory=list)


# ---------------------------------------------------------------------------
# FRED fetching
# ---------------------------------------------------------------------------

def _fetch_fred_series(series_id: str, limit: int = 2,
                       extra_params: dict | None = None) -> list[dict]:
    """Fetch latest observations from FRED API."""
    if not FRED_API_KEY:
        return []

    params = {
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "sort_order": "desc",
        "limit": limit,
    }
    if extra_params:
        params.update(extra_params)

    try:
        resp = requests.get(FRED_BASE_URL, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json().get("observations", [])
    except Exception:
        return []


def _fetch_all_fred() -> dict[str, MacroIndicator]:
    results: dict[str, MacroIndicator] = {}
    for key, cfg in FRED_INDICATORS.items():
        obs = _fetch_fred_series(
            cfg["series_id"],
            limit=2,
            extra_params=cfg.get("extra_params"),
        )
        if obs:
            latest = obs[0]
            previous = obs[1] if len(obs) >= 2 else None
            try:
                value = float(latest["value"])
            except (ValueError, TypeError):
                value = None
            try:
                prev_value = float(previous["value"]) if previous and previous["value"] != "." else None
            except (ValueError, TypeError):
                prev_value = None

            trend = _compute_trend(value, prev_value)

            results[key] = MacroIndicator(
                key=key, name=cfg["name"], name_fr=cfg["name_fr"],
                source="FRED", category=cfg["category"], unit=cfg["unit"],
                value=round(value, 2) if value is not None else None,
                previous_value=round(prev_value, 2) if prev_value is not None else None,
                date=latest.get("date"), trend=trend,
            )
        else:
            results[key] = MacroIndicator(
                key=key, name=cfg["name"], name_fr=cfg["name_fr"],
                source="FRED", category=cfg["category"], unit=cfg["unit"],
                error="Donnees FRED indisponibles",
            )
    return results


# ---------------------------------------------------------------------------
# ECB fetching
# ---------------------------------------------------------------------------

def _fetch_ecb_series(flow_ref: str, key: str) -> list[dict]:
    """Fetch latest observations from ECB Data Portal (CSV format)."""
    url = f"{ECB_BASE_URL}/{flow_ref}/{key}"
    try:
        resp = requests.get(
            url,
            params={"lastNObservations": 2, "format": "csvdata"},
            timeout=15,
        )
        resp.raise_for_status()

        reader = csv.DictReader(io.StringIO(resp.text))
        results = []
        for row in reader:
            time_period = row.get("TIME_PERIOD")
            obs_value = row.get("OBS_VALUE")
            if time_period and obs_value:
                try:
                    results.append({"date": time_period, "value": float(obs_value)})
                except ValueError:
                    continue
        return sorted(results, key=lambda x: x["date"], reverse=True)
    except Exception:
        return []


def _fetch_all_ecb() -> dict[str, MacroIndicator]:
    results: dict[str, MacroIndicator] = {}
    for key, cfg in ECB_INDICATORS.items():
        obs = _fetch_ecb_series(cfg["flow_ref"], cfg["key"])
        if obs:
            latest = obs[0]
            previous = obs[1] if len(obs) >= 2 else None
            value = latest["value"]
            prev_value = previous["value"] if previous else None
            trend = _compute_trend(value, prev_value)

            results[key] = MacroIndicator(
                key=key, name=cfg["name"], name_fr=cfg["name_fr"],
                source="ECB", category=cfg["category"], unit=cfg["unit"],
                value=round(value, 2), previous_value=round(prev_value, 2) if prev_value is not None else None,
                date=latest["date"], trend=trend,
            )
        else:
            results[key] = MacroIndicator(
                key=key, name=cfg["name"], name_fr=cfg["name_fr"],
                source="ECB", category=cfg["category"], unit=cfg["unit"],
                error="Donnees ECB indisponibles",
            )
    return results


# ---------------------------------------------------------------------------
# yfinance fetching
# ---------------------------------------------------------------------------

def _fetch_all_yfinance() -> dict[str, MacroIndicator]:
    results: dict[str, MacroIndicator] = {}
    for key, cfg in YFINANCE_INDICATORS.items():
        try:
            t = yf.Ticker(cfg["ticker"])
            info = t.fast_info
            value = info.get("lastPrice") or info.get("previousClose")
            prev_value = info.get("previousClose") if info.get("lastPrice") else None
            trend = _compute_trend(value, prev_value)

            results[key] = MacroIndicator(
                key=key, name=cfg["name"], name_fr=cfg["name_fr"],
                source="yfinance", category=cfg["category"], unit=cfg["unit"],
                value=round(value, 4) if value is not None else None,
                previous_value=round(prev_value, 4) if prev_value is not None else None,
                date=datetime.date.today().isoformat(), trend=trend,
            )
        except Exception as e:
            results[key] = MacroIndicator(
                key=key, name=cfg["name"], name_fr=cfg["name_fr"],
                source="yfinance", category=cfg["category"], unit=cfg["unit"],
                error=str(e),
            )
    return results


# ---------------------------------------------------------------------------
# Macro config loader (mega-trends, plans, sell-side views)
# ---------------------------------------------------------------------------

def load_macro_config() -> dict:
    """Load macro_config.yaml (mega-trends + investment plans + sell-side views)."""
    if not os.path.exists(MACRO_CONFIG_PATH):
        return {"mega_trends": [], "investment_plans": {"us": [], "eu": []}, "sell_side_views": []}
    try:
        with open(MACRO_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data
    except Exception:
        return {"mega_trends": [], "investment_plans": {"us": [], "eu": []}, "sell_side_views": []}


def _parse_mega_trends(config: dict) -> list[MegaTrend]:
    raw = config.get("mega_trends", [])
    return [
        MegaTrend(
            id=t.get("id", ""),
            name_fr=t.get("name_fr", ""),
            force=t.get("force", 1),
            change=t.get("change", "="),
            catalysts=t.get("catalysts", []),
            etfs_sectoriels=t.get("etfs_sectoriels", []),
            etfs_geo=t.get("etfs_geo", []),
            etfs_thematiques=t.get("etfs_thematiques", []),
            sectors=t.get("sectors", []),
        )
        for t in raw
    ]


def _parse_investment_plans(config: dict) -> list[InvestmentPlan]:
    plans_data = config.get("investment_plans", {})
    result = []
    for region in ("us", "eu"):
        for p in plans_data.get(region, []):
            result.append(InvestmentPlan(
                name=p.get("name", ""),
                amount=p.get("amount", ""),
                status=p.get("status", "active"),
                status_detail=p.get("status_detail", ""),
                change=p.get("change", "="),
                sectors=p.get("sectors", []),
                region=region,
            ))
    return result


def _parse_sell_side_views(config: dict) -> list[SellSideView]:
    raw = config.get("sell_side_views", [])
    return [
        SellSideView(
            source=v.get("source", ""),
            date=v.get("date", ""),
            forecasts=v.get("forecasts", {}),
            key_themes=v.get("key_themes", []),
            risks=v.get("risks", []),
        )
        for v in raw
    ]


# ---------------------------------------------------------------------------
# Lyn Alden article parser
# ---------------------------------------------------------------------------

def _parse_lyn_alden_articles() -> list[LynAldenArticle]:
    """Read and parse all .md files in the Lyn Alden directory.

    Extracts: date (from filename YYMMDD), title (first # heading),
    key points (from ## Points Cl section), portfolio changes
    (from ## Mises a Jour du Portefeuille section).
    """
    if not os.path.isdir(LYN_ALDEN_DIR):
        return []

    md_files = sorted(glob_mod.glob(os.path.join(LYN_ALDEN_DIR, "*.md")), reverse=True)
    articles = []

    for filepath in md_files:
        filename = os.path.basename(filepath)
        match = re.match(r"(\d{6})_", filename)
        if not match:
            continue

        yymmdd = match.group(1)
        date_str = f"20{yymmdd[:2]}-{yymmdd[2:4]}-{yymmdd[4:6]}"

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            continue

        title_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        title = title_match.group(1).strip() if title_match else filename.replace(".md", "").replace("_", " ")

        key_points = _extract_section_bullets(content, "Points Cl")
        portfolio_changes = _extract_section_bullets(content, r"Mises?\s.*Jour.*Portefeuille")

        articles.append(LynAldenArticle(
            filename=filename,
            date=date_str,
            title=title,
            key_points=key_points[:8],
            portfolio_changes=portfolio_changes[:6],
        ))

    return articles


def _extract_section_bullets(content: str, section_pattern: str) -> list[str]:
    """Extract bullet points from a section matching the given heading pattern."""
    pattern = rf"^##\s+.*{section_pattern}.*$"
    match = re.search(pattern, content, re.MULTILINE | re.IGNORECASE)
    if not match:
        return []

    start = match.end()
    next_heading = re.search(r"^##\s+", content[start:], re.MULTILINE)
    end = start + next_heading.start() if next_heading else len(content)

    section = content[start:end]
    bullets = []
    for line in section.split("\n"):
        stripped = line.strip()
        if stripped.startswith("- **"):
            bold_match = re.match(r"- \*\*(.+?)\*\*", stripped)
            if bold_match:
                bullets.append(bold_match.group(1))
            else:
                bullets.append(stripped[2:])
        elif stripped.startswith("- "):
            bullets.append(stripped[2:])

    return bullets


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compute_trend(value: float | None, prev_value: float | None) -> str | None:
    if value is None or prev_value is None:
        return None
    if value > prev_value:
        return "up"
    elif value < prev_value:
        return "down"
    return "flat"


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _score_indicator(ind: MacroIndicator) -> float:
    """Score a single indicator: -1 (bearish) to +1 (bullish)."""
    if ind.value is None:
        return 0.0

    key = ind.key

    # Inflation: falling = bullish (disinflation), rising = bearish
    if key in ("us_cpi", "us_core_cpi", "eur_cpi"):
        if ind.trend == "down":
            return 1.0
        elif ind.trend == "up":
            return -1.0
        return 0.0

    # Unemployment: falling = bullish, rising = bearish
    if key == "us_unemployment":
        if ind.trend == "down":
            return 1.0
        elif ind.trend == "up":
            return -1.0
        return 0.0

    # Central bank rates: falling = bullish (easing)
    if key in ("fed_funds", "ecb_refi_rate"):
        if ind.trend == "down":
            return 1.0
        elif ind.trend == "up":
            return -1.0
        return 0.0

    # Industrial Production Manufacturing: trend-based (up = +0.5, down = -0.5)
    if key == "ism_manufacturing":
        if ind.trend == "up":
            return 0.5
        elif ind.trend == "down":
            return -0.5
        return 0.0

    # US 10Y: rising yields = tighter conditions (half weight)
    if key == "us_10y":
        if ind.trend == "down":
            return 0.5
        elif ind.trend == "up":
            return -0.5
        return 0.0

    # VIX: fear gauge
    if key == "vix":
        if ind.value < 15:
            return 1.0
        elif ind.value > 25:
            return -1.0
        return 0.0

    # Yield curve: positive = bullish, inverted (negative) = bearish
    if key == "yield_curve":
        if ind.value > 0.5:
            return 1.0
        elif ind.value < 0:
            return -1.0
        elif ind.value < 0.3:
            return -0.5
        return 0.0

    # Fed balance sheet: growing = bullish (more liquidity)
    if key == "fed_balance_sheet":
        if ind.trend == "up":
            return 0.5
        elif ind.trend == "down":
            return -0.5
        return 0.0

    # Initial claims: low = bullish, high = bearish
    if key == "initial_claims":
        if ind.value < 220000:
            return 1.0
        elif ind.value > 300000:
            return -1.0
        return 0.0

    # Consumer sentiment: absolute level
    if key == "consumer_sentiment":
        if ind.value > 80:
            return 1.0
        elif ind.value < 60:
            return -1.0
        return 0.0

    # HY credit spread: tight = bullish, wide = bearish
    if key == "hy_spread":
        if ind.value < 350:
            return 1.0
        elif ind.value > 600:
            return -1.0
        return 0.0

    # GDP: trend only
    if key == "gdp":
        if ind.trend == "up":
            return 0.5
        elif ind.trend == "down":
            return -0.5
        return 0.0

    # DXY: falling dollar = bullish (for global risk assets)
    if key == "dxy":
        if ind.trend == "down":
            return 0.5
        elif ind.trend == "up":
            return -0.5
        return 0.0

    # Copper: "Dr. Copper" — rising = bullish (growth signal)
    if key == "copper":
        if ind.trend == "up":
            return 0.5
        elif ind.trend == "down":
            return -0.5
        return 0.0

    # Gold, BTC, Oil: informational, no scoring impact
    if key in ("gold", "btc", "oil_wti"):
        return 0.0

    # EUR/USD: informational, no scoring impact
    return 0.0


def _apply_signals(indicators: list[MacroIndicator]) -> None:
    """Set the signal field on each indicator based on its score."""
    for ind in indicators:
        score = _score_indicator(ind)
        if score > 0.3:
            ind.signal = "bullish"
        elif score < -0.3:
            ind.signal = "bearish"
        else:
            ind.signal = "neutral"


def _compute_outlook(indicators: list[MacroIndicator]) -> tuple[str, float]:
    """Compute aggregate outlook from individual scores."""
    scored = [ind for ind in indicators if ind.value is not None]
    if not scored:
        return "neutral", 0.0

    total = sum(_score_indicator(ind) for ind in scored)
    avg = total / len(scored)

    if avg > 0.4:
        outlook = "risk-on"
    elif avg > 0.15:
        outlook = "moderate-risk-on"
    elif avg < -0.4:
        outlook = "risk-off"
    elif avg < -0.15:
        outlook = "moderate-risk-off"
    else:
        outlook = "neutral"

    return outlook, round(avg, 3)


# ---------------------------------------------------------------------------
# Sector signals
# ---------------------------------------------------------------------------

CATEGORY_SECTOR_MAP = {
    "inflation": ["Consumer Staples", "Utilities", "Materials"],
    "rates": ["Financials", "Real Estate"],
    "employment": ["Consumer Discretionary", "Industrials"],
    "activity": ["Industrials", "Materials", "Energy"],
    "monetary": ["Financials", "Materials"],
    "sentiment": ["Consumer Discretionary", "Communication Services"],
    "commodity": ["Energy", "Materials"],
    "credit": ["Financials"],
}

GICS_SECTORS = [
    "Information Technology", "Health Care", "Financials",
    "Industrials", "Energy", "Communication Services",
    "Consumer Discretionary", "Consumer Staples", "Utilities",
    "Materials", "Real Estate",
]


def _compute_sector_signals(
    indicators: list[MacroIndicator],
    mega_trends: list[MegaTrend],
) -> list[SectorSignal]:
    """Compute sector-level signals by aggregating indicator signals
    and mega-trend support."""
    all_sectors = set(GICS_SECTORS)
    for mt in mega_trends:
        all_sectors.update(mt.sectors)

    signals = []
    for sector in sorted(all_sectors):
        supporting = [mt.id for mt in mega_trends if sector in mt.sectors]

        relevant_indicators = []
        for ind in indicators:
            if ind.value is None:
                continue
            mapped_sectors = CATEGORY_SECTOR_MAP.get(ind.category, [])
            if sector in mapped_sectors:
                relevant_indicators.append(f"{ind.name_fr}: {ind.signal or 'neutral'}")

        trend_score = sum(mt.force for mt in mega_trends if sector in mt.sectors)
        ind_scores = [
            _score_indicator(ind) for ind in indicators
            if ind.value is not None and sector in CATEGORY_SECTOR_MAP.get(ind.category, [])
        ]
        ind_avg = sum(ind_scores) / len(ind_scores) if ind_scores else 0

        combined = (trend_score / 3.0 + ind_avg) / 2 if trend_score > 0 else ind_avg

        if combined > 0.3:
            signal = "bullish"
        elif combined < -0.3:
            signal = "bearish"
        else:
            signal = "neutral"

        signals.append(SectorSignal(
            sector=sector,
            signal=signal,
            supporting_trends=supporting,
            indicator_signals=relevant_indicators,
        ))

    return sorted(signals, key=lambda s: {"bullish": 0, "neutral": 1, "bearish": 2}[s.signal])


# ---------------------------------------------------------------------------
# News feed (RSS)
# ---------------------------------------------------------------------------

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _clean_html(text: str) -> str:
    """Strip HTML tags from text."""
    return _HTML_TAG_RE.sub("", text).strip()


# Keyword-based news zone classification
_NEWS_ZONE_KEYWORDS: dict[str, list[str]] = {
    "US": [
        "trump", "fed ", "federal reserve", "fomc", "u.s.", "united states",
        "congress", "senate", "white house", "wall street", "s&p 500", "nasdaq",
        "dow jones", "treasury", "sec ", "dollar", "chips act", "ira ",
        "stargate", "nvidia", "apple", "microsoft", "amazon", "google",
        "meta ", "tesla", "inflation us",
    ],
    "Europe": [
        "ecb", "bce", "lagarde", "europe", "eurozone", "zone euro", "eu ",
        "european", "germany", "france", "merz", "macron",
        "rearm europe", "safe ", "edip", "nextgen", "repowereu",
        "investai", "tsmc dresde", "euro ", "eur/", "bund",
        "commission europeenne", "parlement europeen",
    ],
    "Tech": [
        " ai ", "artificial intelligence", "intelligence artificielle",
        "semiconductor", "chip ", "nvidia", "tsmc", "asml",
        "openai", "deepseek", "chatgpt", "data center",
        "cyber", "software", "saas", "cloud", "robot",
        "big tech", "capex", "hyperscaler",
    ],
    "Energie": [
        "oil", "petrole", "brent", "wti", "opec", "energy", "energie",
        "uranium", "nuclear", "nucleaire", "lng", "gas ", "gaz ",
        "renewable", "renouvelable", "solar", "eolien", "hydrogene",
        "pipeline", "clean energy",
    ],
    "Geopolitique": [
        "ukraine", "russia", "russie", "china", "chine", "taiwan",
        "tariff", "tarif", "trade war", "guerre commerciale",
        "sanction", "geopolit", "missile", "defense", "military",
        "nato", "otan", "war ", "guerre ", "conflict",
        "middle east", "moyen-orient", "iran", "israel",
    ],
    "Marches": [
        "market", "marche", "stock", "action ", "bond ", "obligation",
        "yield", "rendement", "volatil", "vix", "rally", "selloff",
        "correction", "bull", "bear", "ipo ", "earnings", "resultat",
        "buyback", "dividend", "valuation",
        "gold", "or ", "bitcoin", "btc", "copper", "cuivre",
    ],
}

_LOW_VALUE_PATTERNS = [
    "announces approval of application",
    "enforcement action",
    "insurance policy advisory",
    "egrpra",
    "digital euro",
    "cooperativa de ahorro",
    "community development financial",
    "bank merger",
    "supervisory assessment",
]


def _classify_news_zone(title: str, summary: str, source: str) -> str:
    """Classify a news item into a thematic/geographic zone using keywords."""
    text = f" {title} {summary} ".lower()

    # Source-based hints
    if source in ("BCE", "ECB"):
        return "Europe"
    if source in ("Fed", "Federal Reserve"):
        return "US"

    # Keyword scoring
    scores: dict[str, int] = {}
    for zone, keywords in _NEWS_ZONE_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw.lower() in text)
        if score > 0:
            scores[zone] = score

    if not scores:
        return "Autre"

    return max(scores, key=scores.get)


def _is_impactful_news(item: NewsItem) -> bool:
    """Filter out low-impact administrative news items."""
    combined = f"{item.title} {item.summary}".lower()
    return not any(pattern in combined for pattern in _LOW_VALUE_PATTERNS)


def _parse_rss_date(entry) -> str:
    """Extract and normalize date from an RSS entry."""
    for attr in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, attr, None)
        if parsed:
            try:
                return datetime.date(parsed.tm_year, parsed.tm_mon, parsed.tm_mday).isoformat()
            except Exception:
                pass
    for attr in ("published", "updated"):
        raw = getattr(entry, attr, None)
        if raw:
            return raw[:10]
    return datetime.date.today().isoformat()


def _fetch_news(config: dict) -> list[NewsItem]:
    """Fetch and parse RSS feeds from configured news sources."""
    sources = config.get("news_sources", [])
    items: list[NewsItem] = []

    for source in sources:
        url = source.get("url", "")
        if not url:
            continue
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:10]:
                pub_date = _parse_rss_date(entry)
                raw_summary = entry.get("summary", entry.get("description", ""))
                summary = _clean_html(raw_summary)[:200]

                source_name = source.get("name", source.get("id", "?"))
                items.append(NewsItem(
                    title=entry.get("title", "Sans titre"),
                    source=source_name,
                    date=pub_date,
                    url=entry.get("link", ""),
                    category=source.get("category", "macro"),
                    summary=summary,
                    zone=_classify_news_zone(
                        entry.get("title", ""), summary, source_name,
                    ),
                ))
        except Exception:
            continue

    items = [i for i in items if _is_impactful_news(i)]
    items.sort(key=lambda x: x.date, reverse=True)
    return items[:50]


def get_news_feed(force_refresh: bool = False) -> list[NewsItem]:
    """Public function to get news feed (with 30-min YAML cache)."""
    if not force_refresh and os.path.exists(NEWS_CACHE_PATH):
        cached = _load_cached_news()
        if cached is not None:
            return cached

    config = load_macro_config()
    items = _fetch_news(config)
    _save_news_cache(items)
    return items


def _load_cached_news() -> list[NewsItem] | None:
    """Load news_cache.yaml if it exists and is less than 30 min old."""
    try:
        with open(NEWS_CACHE_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        last_updated = data.get("last_updated", "")
        if not last_updated:
            return None
        updated_dt = datetime.datetime.fromisoformat(last_updated)
        age = datetime.datetime.now() - updated_dt
        if age.total_seconds() >= NEWS_CACHE_TTL_SECONDS:
            return None
        return [NewsItem(**item) for item in data.get("items", [])]
    except Exception:
        return None


def _save_news_cache(items: list[NewsItem]) -> None:
    """Save news items to news_cache.yaml."""
    data = {
        "last_updated": datetime.datetime.now().isoformat(timespec="seconds"),
        "items": [
            {
                "title": n.title, "source": n.source, "date": n.date,
                "url": n.url, "category": n.category, "summary": n.summary,
                "zone": n.zone,
            }
            for n in items
        ],
    }
    with open(NEWS_CACHE_PATH, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


# ---------------------------------------------------------------------------
# Macro synthesis (multi-source)
# ---------------------------------------------------------------------------

_OUTLOOK_LABELS_FR = {
    "risk-on": "risk-on",
    "moderate-risk-on": "risk-on modere",
    "neutral": "neutre",
    "moderate-risk-off": "risk-off modere",
    "risk-off": "risk-off",
}

_CHANGE_ARROWS = {"up": "\u2191", "down": "\u2193", "=": "="}


def _compute_macro_synthesis(
    outlook: str,
    score: float,
    indicators: list[MacroIndicator],
    mega_trends: list[MegaTrend],
    sector_signals: list[SectorSignal],
    sell_side_views: list[SellSideView],
    lyn_alden_insights: list[LynAldenArticle],
) -> list[str]:
    """Compute a concise multi-source macro synthesis (5-6 bullets in French)."""
    synthesis: list[str] = []
    ind_by_key = {ind.key: ind for ind in indicators if ind.value is not None}

    # 1. Outlook + key indicators
    label = _OUTLOOK_LABELS_FR.get(outlook, "neutre")
    ctx = []
    cpi = ind_by_key.get("us_cpi")
    if cpi:
        d = "en baisse" if cpi.trend == "down" else ("en hausse" if cpi.trend == "up" else "stable")
        ctx.append(f"inflation {d} ({cpi.value}%)")
    fed = ind_by_key.get("fed_funds")
    if fed:
        d = "en baisse" if fed.trend == "down" else ("en hausse" if fed.trend == "up" else "en pause")
        ctx.append(f"Fed {d} ({fed.value}%)")
    bs = ind_by_key.get("fed_balance_sheet")
    if bs:
        d = "en expansion" if bs.trend == "up" else ("en contraction (QT)" if bs.trend == "down" else "stable")
        ctx.append(f"bilan Fed {d}")
    vix = ind_by_key.get("vix")
    if vix:
        if vix.value < 15:
            ctx.append(f"VIX bas ({vix.value:.0f})")
        elif vix.value > 25:
            ctx.append(f"VIX eleve ({vix.value:.0f})")
    b1 = f"Contexte macro {label} ({score:+.2f})"
    if ctx:
        b1 += f": {', '.join(ctx)}"
    synthesis.append(b1)

    # 2. Sector signals
    bullish = [s.sector for s in sector_signals if s.signal == "bullish"]
    bearish = [s.sector for s in sector_signals if s.signal == "bearish"]
    parts = []
    if bullish:
        parts.append(f"porteurs: {', '.join(bullish[:4])}")
    if bearish:
        parts.append(f"sous pression: {', '.join(bearish[:3])}")
    if parts:
        synthesis.append(f"Secteurs {'. '.join(parts)}")

    # 3. Sell-side consensus
    if sell_side_views:
        ss_parts = []
        for sv in sell_side_views:
            fc = sv.forecasts if isinstance(sv.forecasts, dict) else {}
            sp = fc.get("sp500_target", "")
            eps = fc.get("sp500_eps_growth", "")
            if sp:
                ss_parts.append(f"S&P 500 cible {sp} ({sv.source})")
            elif eps:
                ss_parts.append(f"EPS {eps} ({sv.source})")
        if ss_parts:
            synthesis.append(f"Consensus sell-side: {', '.join(ss_parts[:2])}")

    # 4. Dominant mega-trends (force >= 2)
    strong = [mt for mt in mega_trends if mt.force >= 2]
    if strong:
        t_strs = []
        for mt in sorted(strong, key=lambda t: t.force, reverse=True)[:4]:
            arrow = _CHANGE_ARROWS.get(mt.change, "=")
            t_strs.append(f"{mt.name_fr} ({mt.force}{arrow})")
        synthesis.append(f"Mega-trends: {', '.join(t_strs)}")

    # 5. Key markets snapshot
    gold = ind_by_key.get("gold")
    btc = ind_by_key.get("btc")
    dxy = ind_by_key.get("dxy")
    m_parts = []
    if gold:
        m_parts.append(f"Or {gold.value:,.0f} USD")
    if btc:
        m_parts.append(f"BTC {btc.value:,.0f} USD")
    if dxy:
        d = "en baisse" if dxy.trend == "down" else ("en hausse" if dxy.trend == "up" else "stable")
        m_parts.append(f"Dollar {d} ({dxy.value:.1f})")
    if m_parts:
        synthesis.append(f"Marches: {', '.join(m_parts)}")

    # 6. Latest Lyn Alden takeaway
    if lyn_alden_insights:
        latest = lyn_alden_insights[0]
        if latest.key_points:
            synthesis.append(f"Lyn Alden ({latest.date}): {latest.key_points[0]}")

    return synthesis


# ---------------------------------------------------------------------------
# Main computation + YAML cache
# ---------------------------------------------------------------------------

def compute_macro_outlook(force_refresh: bool = False) -> MacroOutlook:
    """Fetch all macro indicators and compute the aggregate outlook.

    Uses a YAML cache (macro_outlook.yaml) valid for 6 hours.
    Pass force_refresh=True to bypass the cache.
    """
    if not force_refresh and os.path.exists(MACRO_OUTLOOK_PATH):
        cached = _load_cached_outlook()
        if cached is not None:
            return cached

    # Fetch from all sources
    sources_available: list[str] = []
    sources_failed: list[str] = []
    all_indicators: list[MacroIndicator] = []

    # FRED
    if FRED_API_KEY:
        fred_results = _fetch_all_fred()
        if any(ind.error is None for ind in fred_results.values()):
            sources_available.append("FRED")
        else:
            sources_failed.append("FRED")
        all_indicators.extend(fred_results.values())
    else:
        sources_failed.append("FRED (pas de cle API)")

    # ECB
    ecb_results = _fetch_all_ecb()
    if any(ind.error is None for ind in ecb_results.values()):
        sources_available.append("ECB")
    else:
        sources_failed.append("ECB")
    all_indicators.extend(ecb_results.values())

    # yfinance
    yf_results = _fetch_all_yfinance()
    if any(ind.error is None for ind in yf_results.values()):
        sources_available.append("yfinance")
    else:
        sources_failed.append("yfinance")
    all_indicators.extend(yf_results.values())

    # Score and compute outlook
    _apply_signals(all_indicators)
    outlook_label, score = _compute_outlook(all_indicators)

    # Load config (mega-trends, investment plans, sell-side views)
    config = load_macro_config()
    mega_trends = _parse_mega_trends(config)
    investment_plans = _parse_investment_plans(config)
    sell_side_views = _parse_sell_side_views(config)

    # Parse Lyn Alden articles
    lyn_alden_insights = _parse_lyn_alden_articles()

    # Compute sector signals
    sector_signals = _compute_sector_signals(all_indicators, mega_trends)

    # Compute multi-source macro synthesis
    themes = _compute_macro_synthesis(
        outlook=outlook_label,
        score=score,
        indicators=all_indicators,
        mega_trends=mega_trends,
        sector_signals=sector_signals,
        sell_side_views=sell_side_views,
        lyn_alden_insights=lyn_alden_insights,
    )

    result = MacroOutlook(
        outlook=outlook_label,
        score=score,
        indicators=all_indicators,
        last_updated=datetime.datetime.now().isoformat(timespec="seconds"),
        sources_available=sources_available,
        sources_failed=sources_failed,
        themes=themes,
        mega_trends=mega_trends,
        investment_plans=investment_plans,
        sell_side_views=sell_side_views,
        lyn_alden_insights=lyn_alden_insights,
        sector_signals=sector_signals,
    )

    _save_outlook_yaml(result)
    return result


def _load_cached_outlook() -> MacroOutlook | None:
    """Load macro_outlook.yaml if it exists and is less than 6 hours old."""
    try:
        with open(MACRO_OUTLOOK_PATH, "r") as f:
            data = yaml.safe_load(f) or {}
        last_updated = data.get("last_updated", "")
        if not last_updated:
            return None
        updated_dt = datetime.datetime.fromisoformat(last_updated)
        age = datetime.datetime.now() - updated_dt
        if age.total_seconds() >= CACHE_TTL_SECONDS:
            return None

        indicators = [MacroIndicator(**ind) for ind in data.get("indicators", [])]
        mega_trends = [MegaTrend(**mt) for mt in data.get("mega_trends", [])]
        investment_plans = [InvestmentPlan(**ip) for ip in data.get("investment_plans", [])]
        sell_side_views = [SellSideView(**sv) for sv in data.get("sell_side_views", [])]
        lyn_alden_insights = [LynAldenArticle(**la) for la in data.get("lyn_alden_insights", [])]
        sector_signals = [SectorSignal(**ss) for ss in data.get("sector_signals", [])]

        return MacroOutlook(
            outlook=data.get("outlook", "neutral"),
            score=data.get("score", 0.0),
            indicators=indicators,
            last_updated=last_updated,
            sources_available=data.get("sources_available", []),
            sources_failed=data.get("sources_failed", []),
            themes=data.get("themes", []),
            mega_trends=mega_trends,
            investment_plans=investment_plans,
            sell_side_views=sell_side_views,
            lyn_alden_insights=lyn_alden_insights,
            sector_signals=sector_signals,
        )
    except Exception:
        return None


def _save_outlook_yaml(result: MacroOutlook) -> None:
    """Persist the macro outlook to YAML for caching."""
    data = {
        "outlook": result.outlook,
        "score": result.score,
        "last_updated": result.last_updated,
        "sources_available": result.sources_available,
        "sources_failed": result.sources_failed,
        "themes": result.themes,
        "indicators": [
            {
                "key": ind.key, "name": ind.name, "name_fr": ind.name_fr,
                "source": ind.source, "category": ind.category, "unit": ind.unit,
                "value": ind.value, "previous_value": ind.previous_value,
                "date": ind.date, "trend": ind.trend, "signal": ind.signal,
                "error": ind.error,
            }
            for ind in result.indicators
        ],
        "mega_trends": [
            {
                "id": mt.id, "name_fr": mt.name_fr, "force": mt.force,
                "change": mt.change, "catalysts": mt.catalysts,
                "etfs_sectoriels": mt.etfs_sectoriels, "etfs_geo": mt.etfs_geo,
                "etfs_thematiques": mt.etfs_thematiques, "sectors": mt.sectors,
            }
            for mt in result.mega_trends
        ],
        "investment_plans": [
            {
                "name": ip.name, "amount": ip.amount, "status": ip.status,
                "status_detail": ip.status_detail, "change": ip.change,
                "sectors": ip.sectors, "region": ip.region,
            }
            for ip in result.investment_plans
        ],
        "sell_side_views": [
            {
                "source": sv.source, "date": sv.date,
                "forecasts": sv.forecasts, "key_themes": sv.key_themes,
                "risks": sv.risks,
            }
            for sv in result.sell_side_views
        ],
        "lyn_alden_insights": [
            {
                "filename": la.filename, "date": la.date, "title": la.title,
                "key_points": la.key_points, "portfolio_changes": la.portfolio_changes,
            }
            for la in result.lyn_alden_insights
        ],
        "sector_signals": [
            {
                "sector": ss.sector, "signal": ss.signal,
                "supporting_trends": ss.supporting_trends,
                "indicator_signals": ss.indicator_signals,
            }
            for ss in result.sector_signals
        ],
    }
    with open(MACRO_OUTLOOK_PATH, "w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
