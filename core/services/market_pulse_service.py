from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.providers.market_provider import ProviderError


MARKET_PULSE_SERVICE_VERSION = 2
MARKET_SYMBOLS = (
    "DIA", "SPY", "QQQ", "IWM",
    "TLT", "IEF", "SHY", "LQD", "HYG",
    "CL=F", "GC=F", "SI=F", "HG=F", "UUP",
)
_LABELS = {
    "DIA": "Dow (DIA proxy)", "SPY": "S&P 500 (SPY proxy)",
    "QQQ": "Nasdaq-100 (QQQ proxy)", "IWM": "Small caps (IWM)",
    "TLT": "Long Treasuries (TLT)", "IEF": "Intermediate Treasuries (IEF)",
    "SHY": "Short Treasuries (SHY)", "LQD": "Investment-grade credit (LQD)",
    "HYG": "High-yield credit (HYG)", "CL=F": "WTI crude oil futures",
    "GC=F": "Gold futures", "SI=F": "Silver futures", "HG=F": "Copper futures",
    "UUP": "U.S. dollar (UUP proxy)",
}
_CATEGORIES = {
    **{symbol: "Equities" for symbol in ("DIA", "SPY", "QQQ", "IWM")},
    **{symbol: "Bonds" for symbol in ("TLT", "IEF", "SHY", "LQD", "HYG")},
    **{symbol: "Commodities" for symbol in ("CL=F", "GC=F", "SI=F", "HG=F")},
    "UUP": "Currencies",
}


def build_market_pulse(market_provider, macro_provider) -> dict[str, Any]:
    """Build a cached live cross-asset market-at-a-glance snapshot."""
    errors: list[str] = []
    quotes: list[dict[str, Any]] = []
    market_source = getattr(market_provider, "name", "Unknown")
    market_as_of = None
    try:
        snapshot = market_provider.market_dashboard(MARKET_SYMBOLS)
        market_source = snapshot.get("provider", market_source)
        for item in snapshot.get("quotes", []):
            symbol = str(item.get("ticker", "")).upper()
            if symbol not in _LABELS:
                continue
            change = _number(item.get("change_percent"))
            quotes.append({
                "ticker": symbol, "label": _LABELS[symbol], "price": _number(item.get("price")),
                "change_percent": change, "direction": _direction(change),
                "category": _CATEGORIES.get(symbol, "Other"), "observed_at": item.get("observed_at"),
            })
        market_as_of = next((row["observed_at"] for row in quotes if row.get("observed_at")), None)
    except (ProviderError, RuntimeError, ValueError, AttributeError) as exc:
        errors.append(f"Market quotes: {exc}")

    indicators: dict[str, Any] = {}
    macro_source = getattr(macro_provider, "name", "Unknown")
    macro_as_of = None
    try:
        macro = macro_provider.snapshot()
        indicators = macro.get("indicators", {})
        macro_source = macro.get("provider", macro_source)
        macro_as_of = macro.get("retrieved_at")
    except (ProviderError, RuntimeError, ValueError, AttributeError) as exc:
        errors.append(f"Macro indicators: {exc}")

    oil = _indicator(indicators.get("oil_wti"))
    rates = {
        "treasury_10y": _indicator(indicators.get("treasury_10y")),
        "policy_rate": _indicator(indicators.get("policy_rate")),
        "inflation": _indicator(indicators.get("inflation")),
    }
    core_changes = [row["change_percent"] for row in quotes
                    if row["ticker"] in {"DIA", "SPY", "QQQ", "IWM"} and row["change_percent"] is not None]
    positive = sum(change > 0 for change in core_changes)
    average = sum(core_changes) / len(core_changes) if core_changes else None
    tone = ("Risk-on" if average is not None and average >= .5 and positive >= 3 else
            "Risk-off" if average is not None and average <= -.5 and positive <= 1 else "Mixed")
    ranked = sorted([row for row in quotes if row["change_percent"] is not None],
                    key=lambda row: row["change_percent"], reverse=True)
    groups = {category.lower(): [row for row in quotes if row["category"] == category]
              for category in ("Equities", "Bonds", "Commodities", "Currencies")}
    notes = _analyst_notes(tone, groups, rates, oil)
    return {
        "status": "Ready" if quotes and oil else "Partial" if quotes or oil else "Unavailable",
        "tone": tone, "average_core_change": average, "positive_core_markets": positive,
        "core_markets": len(core_changes), "quotes": quotes,
        "equities": groups["equities"], "bonds": groups["bonds"],
        "commodities": groups["commodities"], "currencies": groups["currencies"],
        "leaders": ranked[:3], "laggards": list(reversed(ranked[-3:])),
        "market_summary": _market_summary(tone, ranked), "analyst_notes": notes,
        "oil": oil, "rates": rates, "market_source": market_source, "macro_source": macro_source,
        "market_as_of": market_as_of, "macro_as_of": macro_as_of,
        "generated_at": datetime.now(timezone.utc).isoformat(), "errors": errors,
        "disclosure": ("Dow, S&P 500, Nasdaq, dollar, and bond cards use liquid ETF proxies; commodity cards use "
                       "Yahoo-sourced futures when available. FRED WTI is a slower official benchmark and may differ "
                       "from intraday futures. Analyst notes are deterministic research context, not advice."),
    }


def _analyst_notes(tone, groups, rates, oil) -> list[dict[str, str]]:
    notes: list[dict[str, str]] = []
    equities = {row["ticker"]: row for row in groups["equities"]}
    bonds = {row["ticker"]: row for row in groups["bonds"]}
    commodities = {row["ticker"]: row for row in groups["commodities"]}
    qqq, iwm = equities.get("QQQ"), equities.get("IWM")
    tlt, hyg = bonds.get("TLT"), bonds.get("HYG")
    gold, silver, copper, crude = (commodities.get(key) for key in ("GC=F", "SI=F", "HG=F", "CL=F"))
    if qqq and iwm and qqq.get("change_percent") is not None and iwm.get("change_percent") is not None:
        spread = qqq["change_percent"] - iwm["change_percent"]
        notes.append({"Theme": "Equity breadth", "Note": (
            f"Nasdaq-100 is outperforming small caps by {spread:+.2f} percentage points. "
            + ("Leadership is concentrated in larger growth stocks." if spread > .5 else
               "Participation is reasonably broad across growth and smaller companies." if spread > -.5 else
               "Smaller companies are leading, which can signal improving risk breadth."))})
    if tlt and hyg and tlt.get("change_percent") is not None and hyg.get("change_percent") is not None:
        notes.append({"Theme": "Bonds and credit", "Note": (
            f"Long Treasuries are {tlt['change_percent']:+.2f}% while high-yield credit is {hyg['change_percent']:+.2f}%. "
            + ("Both are firm, suggesting rates and credit are not currently fighting the equity move." if tlt["change_percent"] >= 0 and hyg["change_percent"] >= 0 else
               "Weak high-yield credit is a caution flag for risk appetite." if hyg["change_percent"] < 0 else
               "Falling long bonds imply upward yield pressure that can weigh on long-duration valuations."))})
    if crude and crude.get("price") is not None:
        notes.append({"Theme": "Oil and inflation", "Note": (
            f"WTI futures are ${crude['price']:.2f} and {crude.get('change_percent') or 0:+.2f}% today. "
            "A sustained rise can support energy producers but pressure transportation, consumer margins, and inflation expectations." )})
    elif oil and oil.get("value") is not None:
        notes.append({"Theme": "Oil and inflation", "Note": f"Official FRED WTI is ${oil['value']:.2f} per barrel and trending {str(oil.get('trend')).lower()}."})
    if gold and silver:
        notes.append({"Theme": "Precious metals", "Note": (
            f"Gold is {gold.get('change_percent') or 0:+.2f}% and silver is {silver.get('change_percent') or 0:+.2f}% today. "
            + ("Joint strength can reflect defensive demand, inflation hedging, or dollar weakness." if (gold.get("change_percent") or 0) > 0 and (silver.get("change_percent") or 0) > 0 else
               "The metals are diverging, so the signal is not broadly confirmed."))})
    if copper and copper.get("change_percent") is not None:
        notes.append({"Theme": "Industrial demand", "Note": f"Copper is {copper['change_percent']:+.2f}% today; persistent strength often aligns with firmer global industrial expectations."})
    notes.insert(0, {"Theme": "Cross-asset setup", "Note": f"Atlas classifies the current setup as {tone.lower()}. Confirm this with breadth, credit, yields, and commodities rather than equities alone."})
    return notes


def _market_summary(tone: str, ranked: list[dict[str, Any]]) -> str:
    if not ranked:
        return "Market direction is unavailable because no current quote changes were returned."
    return (f"The cross-asset setup is {tone.lower()}. {ranked[0]['label']} leads at "
            f"{ranked[0]['change_percent']:+.2f}%, while {ranked[-1]['label']} trails at "
            f"{ranked[-1]['change_percent']:+.2f}%.")


def _indicator(item: dict[str, Any] | None) -> dict[str, Any] | None:
    if not item:
        return None
    return {"label": item.get("label"), "value": _number(item.get("value")), "unit": item.get("unit"),
            "observed_at": item.get("observed_at"), "change_percent": _number(item.get("change_percent")),
            "trend": item.get("trend", "Unavailable"), "stale": bool(item.get("stale")),
            "source": item.get("source"), "series_id": item.get("series_id")}


def _direction(change: float | None) -> str:
    if change is None:
        return "Unavailable"
    return "Up" if change > .01 else "Down" if change < -.01 else "Flat"


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None