from __future__ import annotations

from typing import Any


MACRO_SERVICE_VERSION = 2


RATE_SENSITIVE = {"Technology", "Communication Services", "Consumer Cyclical", "Real Estate", "Utilities"}
CYCLICAL = {"Technology", "Communication Services", "Consumer Cyclical", "Industrials", "Materials"}
OIL_SENSITIVE = {"Consumer Cyclical", "Industrials", "Materials", "Utilities"}


def score_macro_environment(sector: str | None, macro: dict[str, Any]) -> tuple[int, str]:
    indicators = macro["indicators"]
    inflation = indicators["inflation"]["value"]
    policy_rate = indicators["policy_rate"]["value"]
    treasury = indicators["treasury_10y"]["value"]
    unemployment = indicators["unemployment"]["value"]
    growth = indicators["gdp_growth"]["value"]
    oil = indicators.get("oil_wti", {}).get("value")

    score = 50
    score += 6 if 1 <= inflation <= 3 else -8 if inflation > 4 else 0
    score += 7 if growth >= 2 else -12 if growth < 0 else 0
    score += 5 if unemployment < 5 else -8 if unemployment > 7 else 0
    score += 4 if treasury < 4 else -5 if treasury > 5 else 0

    if sector in RATE_SENSITIVE:
        score += 6 if policy_rate < 3 else -10 if policy_rate > 5 else -3
    elif sector == "Financials":
        score += 6 if 3 <= policy_rate <= 5.5 else 0
    if sector in CYCLICAL:
        score += 5 if growth >= 2 else -8 if growth < 1 else 0
    if sector == "Energy" and inflation > 3:
        score += 6
    if oil is not None:
        score += _oil_score(sector, float(oil))
    if sector == "Consumer Defensive" and unemployment > 5:
        score += 4

    stale_count = sum(indicator["stale"] for indicator in indicators.values())
    score -= min(stale_count * 3, 12)
    score = max(0, min(100, score))
    context = "supportive" if score >= 65 else "challenging" if score <= 35 else "mixed"
    thesis = f"The macro environment appears {context} for {sector or 'this company'} based on growth, inflation, labor conditions, interest rates, and energy costs."
    if oil is not None:
        thesis += f" WTI crude is ${float(oil):.2f} per barrel; {oil_market_impact(sector, float(oil)).lower()}."
    if stale_count:
        thesis += f" {stale_count} macro series may be stale."
    return score, thesis


def _oil_score(sector: str | None, price: float) -> int:
    if sector == "Energy":
        return 12 if price >= 80 else -10 if price < 50 else 4 if price >= 65 else -3
    if sector in OIL_SENSITIVE:
        return -10 if price >= 100 else -5 if price >= 85 else 4 if price < 65 else 0
    return -7 if price >= 110 else -3 if price >= 95 else 0


def oil_market_impact(sector: str | None, price: float) -> str:
    if sector == "Energy":
        return "a tailwind for energy-sector cash flow" if price >= 65 else "a headwind for energy-sector cash flow"
    if sector in OIL_SENSITIVE:
        return "a material input-cost headwind" if price >= 85 else "a manageable input-cost backdrop"
    return "an inflation and consumer-spending headwind" if price >= 95 else "not currently an acute broad-market pressure"