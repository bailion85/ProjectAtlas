from __future__ import annotations

from typing import Any

from core.services.macro_service import score_macro_environment


WEIGHTS = {
    "Volatility": 17,
    "Drawdown": 17,
    "Valuation": 13,
    "Business quality": 13,
    "Beta": 9,
    "Price position": 7,
    "Technical trend": 9,
    "Macro conditions": 8,
    "Catalyst timing": 7,
}


def analyze_risk(stock: dict[str, Any], performance: dict[str, Any], technical: dict[str, Any], macro: dict[str, Any], market_environment: dict[str, Any] | None = None, catalyst_calendar: dict[str, Any] | None = None, weights: dict[str, float] | None = None) -> dict[str, Any]:
    active_weights = weights or WEIGHTS
    components: list[dict[str, Any]] = []
    _add(components, "Volatility", _volatility(performance.get("annualized_volatility")),
         f"Annualized volatility is {performance.get('annualized_volatility', 0):.1f}%.")
    _add(components, "Drawdown", _drawdown(performance.get("max_drawdown")),
         f"Maximum observed drawdown is {performance.get('max_drawdown', 0):.1f}%.")
    _add(components, "Valuation", _valuation(stock.get("pe_ratio")),
         _value_text("Trailing P/E", stock.get("pe_ratio")))
    _add(components, "Business quality", _quality(stock.get("profit_margin"), stock.get("revenue_growth")),
         _quality_text(stock.get("profit_margin"), stock.get("revenue_growth")))
    _add(components, "Beta", _beta(stock.get("beta")), _value_text("Historical beta", stock.get("beta")))
    _add(components, "Price position", _price_position(stock.get("price"), stock.get("fifty_two_week_high"), stock.get("fifty_two_week_low")),
         _price_text(stock.get("price"), stock.get("fifty_two_week_high"), stock.get("fifty_two_week_low")))
    _add(components, "Technical trend", _technical(technical), technical.get("message", "Technical history is unavailable."))
    macro_score, macro_text = score_macro_environment(stock.get("sector"), macro)
    environment_score = market_environment.get("score") if market_environment else macro_score
    environment_text = market_environment.get("summary") if market_environment else macro_text
    _add(components, "Macro conditions", 100 - (macro_score * .6 + environment_score * .4), environment_text)
    _add(components, "Catalyst timing", catalyst_calendar.get("risk_score") if catalyst_calendar else None,
         catalyst_calendar.get("summary", "Catalyst timing is unavailable.") if catalyst_calendar else "Catalyst timing is unavailable.")

    available_weight = sum(active_weights[item["factor"]] for item in components if item["score"] is not None)
    weighted_score = sum(item["score"] * active_weights[item["factor"]] for item in components if item["score"] is not None)
    score = round(weighted_score / available_weight, 1) if available_weight else 50.0
    for item in components:
        item["weight"] = active_weights[item["factor"]]
        item["severity"] = severity(item["score"]) if item["score"] is not None else "Unavailable"
    flags = [
        {"severity": item["severity"], "factor": item["factor"], "message": item["explanation"]}
        for item in sorted(components, key=lambda value: value["score"] if value["score"] is not None else -1, reverse=True)
        if item["score"] is not None and item["score"] >= 56
    ]
    return {
        "score": score,
        "severity": severity(score),
        "coverage_percent": round(available_weight, 1),
        "components": components,
        "flags": flags,
        "summary": f"Overall risk is {severity(score).lower()} at {score:.1f}/100 based on {available_weight:.0f}% factor coverage.",
    }


def severity(score: float) -> str:
    if score <= 30:
        return "Low"
    if score <= 55:
        return "Moderate"
    if score <= 75:
        return "High"
    return "Critical"


def _add(items: list[dict[str, Any]], factor: str, score: float | None, explanation: str) -> None:
    items.append({"factor": factor, "score": None if score is None else round(_clamp(score), 1), "explanation": explanation})


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


def _volatility(value: Any) -> float | None:
    return None if value is None else (float(value) - 10) / 0.4


def _drawdown(value: Any) -> float | None:
    return None if value is None else (abs(float(value)) - 5) / 0.4


def _valuation(pe: Any) -> float | None:
    return None if pe is None else (float(pe) - 12) * 2.2


def _quality(margin: Any, growth: Any) -> float | None:
    scores = []
    if margin is not None:
        scores.append(80 - float(margin) * 220)
    if growth is not None:
        scores.append(65 - float(growth) * 220)
    return sum(scores) / len(scores) if scores else None


def _beta(value: Any) -> float | None:
    return None if value is None else (float(value) - .65) / .0135


def _price_position(price: Any, high: Any, low: Any) -> float | None:
    if price is None or high is None or low is None or float(high) <= float(low):
        return None
    position = (float(price) - float(low)) / (float(high) - float(low))
    return 100 - position * 100


def _technical(technical: dict[str, Any]) -> float | None:
    status = technical.get("status")
    if status == "bullish":
        return max(10, 30 - float(technical.get("spread_percent", 0)) * 2)
    if status == "bearish":
        return min(95, 70 + abs(float(technical.get("spread_percent", 0))) * 2)
    return None if status == "insufficient_history" else 50


def _value_text(label: str, value: Any) -> str:
    return f"{label} is unavailable." if value is None else f"{label} is {float(value):.2f}."


def _quality_text(margin: Any, growth: Any) -> str:
    parts = []
    if margin is not None:
        parts.append(f"profit margin {float(margin) * 100:.1f}%")
    if growth is not None:
        parts.append(f"revenue growth {float(growth) * 100:.1f}%")
    return "Business-quality inputs are unavailable." if not parts else "Business quality reflects " + " and ".join(parts) + "."


def _price_text(price: Any, high: Any, low: Any) -> str:
    if price is None or high is None or low is None:
        return "The 52-week price position is unavailable."
    return f"Price ${float(price):,.2f} is compared with the 52-week range of ${float(low):,.2f} to ${float(high):,.2f}."
