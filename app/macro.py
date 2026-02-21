"""Macro economic indicators dashboard.

Self-contained module that fetches macro indicators from three sources:
- FRED API (US: CPI, Core CPI, Unemployment, Fed Funds, ISM)
- yfinance (market: US 10Y yield, VIX, EUR/USD)
- ECB Data Portal (EU: Main Refi Rate, EUR CPI HICP)

Each source degrades gracefully if unavailable.
Results are cached in macro_outlook.yaml (valid 6 hours).
"""

from __future__ import annotations

import csv
import datetime
import io
import os
from dataclasses import dataclass, field
from typing import Optional

import requests
import yaml
import yfinance as yf

from app.config import FRED_API_KEY


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MACRO_OUTLOOK_PATH = "macro_outlook.yaml"
CACHE_TTL_SECONDS = 6 * 3600  # 6 hours

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
        "extra_params": {"units": "pc1"},  # percent change from year ago
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
        "series_id": "NAPM",
        "name": "ISM Manufacturing PMI",
        "name_fr": "ISM Manufacturier",
        "unit": "Index",
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
class MacroOutlook:
    outlook: str = "neutral"
    score: float = 0.0
    indicators: list[MacroIndicator] = field(default_factory=list)
    last_updated: str = ""
    sources_available: list[str] = field(default_factory=list)
    sources_failed: list[str] = field(default_factory=list)
    themes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# FRED fetching
# ---------------------------------------------------------------------------

def _fetch_fred_series(series_id: str, limit: int = 2,
                       extra_params: dict | None = None) -> list[dict]:
    """Fetch latest observations from FRED API.

    Returns list of {"date": "YYYY-MM-DD", "value": "123.456"} dicts,
    newest first.  Returns [] if FRED_API_KEY is not set or request fails.
    """
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
    """Fetch latest observations from ECB Data Portal (CSV format).

    Returns list of {"date": "YYYY-MM", "value": float} dicts,
    newest first.
    """
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

    # ISM: above 52 = expansion, below 48 = contraction
    if key == "ism_manufacturing":
        if ind.value > 52:
            return 1.0
        elif ind.value < 48:
            return -1.0
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
    """Compute aggregate outlook from individual scores.

    Returns (outlook_label, normalized_score).
    """
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

    result = MacroOutlook(
        outlook=outlook_label,
        score=score,
        indicators=all_indicators,
        last_updated=datetime.datetime.now().isoformat(timespec="seconds"),
        sources_available=sources_available,
        sources_failed=sources_failed,
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
        return MacroOutlook(
            outlook=data.get("outlook", "neutral"),
            score=data.get("score", 0.0),
            indicators=indicators,
            last_updated=last_updated,
            sources_available=data.get("sources_available", []),
            sources_failed=data.get("sources_failed", []),
            themes=data.get("themes", []),
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
    }
    with open(MACRO_OUTLOOK_PATH, "w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
