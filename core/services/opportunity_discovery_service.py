from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


OPPORTUNITY_DISCOVERY_SERVICE_VERSION = 6
LIVE_UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "BRK.B", "LLY", "AVGO", "JPM",
    "V", "XOM", "UNH", "MA", "COST", "HD", "PG", "JNJ", "ABBV", "WMT",
    "BAC", "KO", "PEP", "MRK", "CRM", "ORCL", "AMD", "NFLX", "CVX", "ADBE",
]
DEMO_UNIVERSE = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN"]


def select_market_candidates(
    movers: dict[str, Any], radar: set[str], limit: int = 5,
    minimum_price: float = 5, minimum_volume: int = 500_000,
) -> list[dict[str, Any]]:
    """Select liquid, unfamiliar candidates while balancing mover categories."""
    cleaned = []
    seen = set()
    for item in movers.get("rows", []):
        ticker = str(item.get("ticker", "")).strip().upper()
        price = _number(item.get("price"))
        volume = int(_number(item.get("volume")) or 0)
        if (not ticker or ticker in radar or ticker in seen or price is None or price < minimum_price
                or volume < minimum_volume or not all(character.isalnum() or character in ".-" for character in ticker)):
            continue
        seen.add(ticker)
        cleaned.append({**item, "ticker": ticker, "price": price, "volume": volume})
    groups = {name: [] for name in ("Most active", "Top gainer", "Top loser")}
    for item in cleaned:
        groups.setdefault(str(item.get("group")), []).append(item)
    for values in groups.values():
        values.sort(key=lambda item: (-item["volume"], -abs(float(item.get("change_percentage") or 0))))
    selected = []
    while len(selected) < limit and any(groups.values()):
        for group in ("Most active", "Top gainer", "Top loser"):
            if groups.get(group) and len(selected) < limit:
                selected.append(groups[group].pop(0))
    return selected


def score_candidate(
    snapshot: dict[str, Any], history: list[dict[str, Any]], provider_name: str,
    financial_health: dict[str, Any] | None = None,
) -> dict[str, Any]:
    closes = [float(row["close"]) for row in history if float(row.get("close", 0)) > 0]
    if len(closes) < 50:
        raise ValueError("At least 50 daily observations are required for discovery scoring.")
    pe = _number(snapshot.get("forward_pe") or snapshot.get("pe_ratio"))
    peg = _number(snapshot.get("peg_ratio"))
    price = _number(snapshot.get("price")) or closes[-1]
    high = _number(snapshot.get("fifty_two_week_high"))
    margin = _number(snapshot.get("profit_margin"))
    roe = _number(snapshot.get("return_on_equity"))
    revenue_growth = _number(snapshot.get("revenue_growth"))
    earnings_growth = _number(snapshot.get("earnings_growth"))
    beta = _number(snapshot.get("beta"))
    valuation = _average([
        _descending(pe, 15, 45), _descending(peg, 1, 4),
        50 if high is None else _clamp((high / price - 1) * 180 + 45),
    ])
    quality = _average([_ascending(margin, .05, .30), _ascending(roe, .08, .35)])
    growth = _average([_ascending(revenue_growth, 0, .25), _ascending(earnings_growth, 0, .30)])
    sec_supported = financial_health is not None
    if sec_supported:
        health_score = _number(financial_health.get("score")) or 50
        quality = health_score if margin is None and roe is None else _average([quality, health_score])
        sec_changes = {
            str(signal.get("Factor")): _number(signal.get("Change"))
            for signal in financial_health.get("signals", [])
        }
        sec_growth = _average([
            _ascending((sec_changes.get("Revenue") or 0) / 100, 0, .25),
            _ascending((sec_changes.get("Net income") or 0) / 100, 0, .30),
        ])
        growth = sec_growth if revenue_growth is None and earnings_growth is None else _average([growth, sec_growth])
    sma50 = sum(closes[-50:]) / 50
    sma200 = sum(closes[-200:]) / 200 if len(closes) >= 200 else None
    momentum_90 = (closes[-1] / closes[max(0, len(closes) - 64)] - 1) * 100
    trend = _clamp(50 + momentum_90 * 2 + (15 if sma200 and sma50 > sma200 else -10 if sma200 else 0))
    risk = 60 if beta is None else _clamp(100 - abs(beta - 1) * 45)
    alpha_fundamentals_available = snapshot.get("fundamentals_status", "Available") == "Available"
    fundamentals_available = alpha_fundamentals_available or sec_supported
    score = round(valuation * .30 + quality * .25 + growth * .20 + trend * .15 + risk * .10, 1)
    if alpha_fundamentals_available:
        label = "Strong research candidate" if score >= 70 else "Worth watching" if score >= 55 else "Pass for now"
    elif sec_supported:
        score = min(score, 69.9)
        label = "SEC-supported lead" if score >= 50 else "Pass for now"
    else:
        score = min(score, 64.9)
        label = "Price-only lead" if trend >= 50 else "Pass for now"
    positives = []
    cautions = []
    if valuation >= 65: positives.append("valuation compares favorably")
    else: cautions.append("valuation support is limited")
    if quality >= 65: positives.append("profitability and returns are comparatively strong")
    else: cautions.append("quality metrics need review")
    if growth >= 60: positives.append("growth is constructive")
    else: cautions.append("growth is modest or negative")
    if trend >= 60: positives.append("price trend is constructive")
    else: cautions.append("price trend is not yet supportive")
    if sec_supported and not alpha_fundamentals_available:
        cautions.insert(0, "forward valuation metrics are unavailable; SEC filing trends support this preliminary lead")
    elif not fundamentals_available:
        cautions.insert(0, "fundamentals were unavailable, so this is a price-and-trend lead only")
    demo = "demo" in provider_name.lower() or "not live" in provider_name.lower()
    return {
        "Ticker": str(snapshot.get("symbol", "")).upper(), "Company": snapshot.get("name", ""),
        "Sector": snapshot.get("sector", "Unknown"), "Discovery score": score, "Research label": label,
        "Price": price, "Forward P/E": pe, "PEG": peg, "Valuation": round(valuation, 1),
        "Quality": round(quality, 1), "Growth": round(growth, 1), "Trend": round(trend, 1),
        "Risk fit": round(risk, 1), "90-day momentum": round(momentum_90, 1),
        "Data status": "Demo" if demo else "Live" if alpha_fundamentals_available else
                       "Live price + SEC" if sec_supported else "Live price only",
        "Evidence coverage": "Full preliminary screen" if alpha_fundamentals_available else
                             "Price, trend, and SEC filing fundamentals" if sec_supported else "Price and trend only",
        "Provider": _provider_label(snapshot.get("source") or provider_name, sec_supported),
        "SEC health": financial_health.get("score") if sec_supported else None,
        "SEC posture": financial_health.get("posture") if sec_supported else None,
        "Latest SEC filing": (financial_health.get("latest_filing") or {}).get("filed") if sec_supported else None,
        "Observed": snapshot.get("observed_at"),
        "Why it surfaced": "; ".join(positives) or "No strong positive factor yet",
        "What could go wrong": "; ".join(cautions) or "Normal company and market risks still apply",
    }



def score_market_feed_candidate(source: dict[str, Any], provider_name: str, limitation: str) -> dict[str, Any]:
    """Keep a verified live mover visible when deeper enrichment is temporarily unavailable."""
    ticker = str(source.get("ticker", "")).strip().upper()
    price = _number(source.get("price"))
    change = _number(source.get("change_percentage"))
    volume = int(_number(source.get("volume")) or 0)
    if not ticker or price is None:
        raise ValueError("The live market feed did not include a usable ticker and price.")
    activity = _clamp(35 + min(volume / 1_000_000, 40))
    direction = 50 if change is None else _clamp(50 + change * 4)
    score = round(min(activity * .55 + direction * .45, 54.9), 1)
    return {
        "Ticker": ticker, "Company": ticker, "Sector": "Pending research",
        "Discovery score": score, "Research label": "Market-feed lead",
        "Price": price, "Forward P/E": None, "PEG": None,
        "Valuation": 50.0, "Quality": 50.0, "Growth": 50.0,
        "Trend": round(direction, 1), "Risk fit": 50.0, "90-day momentum": None,
        "Data status": "Live market feed only", "Evidence coverage": "Live price, daily move, and volume",
        "Provider": provider_name, "SEC health": None, "SEC posture": None,
        "Latest SEC filing": None, "Observed": None,
        "Why it surfaced": "unusual market activity in the live movers feed",
        "What could go wrong": "historical trend and company fundamentals could not be refreshed; treat this as an attention signal only",
        "Research limitation": limitation,
    }
def build_discovery_result(rows: list[dict[str, Any]], failures: list[dict[str, str]], radar: set[str]) -> dict[str, Any]:
    ranked = sorted(rows, key=lambda row: (-row["Discovery score"], row["Ticker"]))
    for index, row in enumerate(ranked, 1):
        row["Rank"] = index
        row["On radar"] = row["Ticker"] in radar
    outside = [row for row in ranked if not row["On radar"]]
    return {
        "created_at": datetime.now(timezone.utc).isoformat(), "rows": ranked, "failures": failures,
        "outside_radar": len(outside), "strong_candidates": sum(row["Research label"] == "Strong research candidate" for row in outside),
        "summary": f"Screened {len(ranked)} company or companies; {len(outside)} are outside the current watchlist and portfolio.",
        "disclosure": "Discovery scores are preliminary research filters, not investment recommendations. Confirm live evidence, valuation assumptions, diversification, and risks before making any decision.",
    }


def _provider_label(source: str, sec_supported: bool) -> str:
    return source if not sec_supported or "SEC EDGAR" in source else f"{source} + SEC EDGAR"

def _number(value: Any) -> float | None:
    try: return float(value) if value is not None else None
    except (TypeError, ValueError): return None


def _clamp(value: float, low: float = 0, high: float = 100) -> float:
    return min(max(value, low), high)


def _ascending(value: float | None, low: float, high: float) -> float:
    return 50 if value is None else _clamp((value - low) / (high - low) * 100)


def _descending(value: float | None, low: float, high: float) -> float:
    return 50 if value is None else 100 - _ascending(value, low, high)


def _average(values: list[float]) -> float:
    return sum(values) / len(values)
