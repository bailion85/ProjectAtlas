from __future__ import annotations

from typing import Any


WEIGHTS = {
    "Committee conviction": 25,
    "Risk profile": 20,
    "Market environment": 15,
    "Technical trend": 15,
    "Catalyst timing": 10,
    "Backtest evidence": 10,
    "Data quality": 5,
}


def analyze_entry_readiness(
    committee_score: float,
    risk: dict[str, Any],
    environment: dict[str, Any],
    technical: dict[str, Any],
    catalyst: dict[str, Any],
    backtest: dict[str, Any],
    company_metrics: dict[str, Any],
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    active_weights = weights or WEIGHTS
    components = [
        _component("Committee conviction", committee_score, f"Committee score is {committee_score:.1f}/100.", active_weights),
        _component("Risk profile", 100 - float(risk.get("score", 50)),
                   f"Inverse of the {risk.get('score', 50):.1f}/100 risk score.", active_weights),
        _component("Market environment", _number(environment.get("score")), environment.get("summary", "Market evidence is unavailable."), active_weights),
        _component("Technical trend", _technical_score(technical), technical.get("message", "Technical evidence is unavailable."), active_weights),
        _component("Catalyst timing", _catalyst_score(catalyst), catalyst.get("summary", "Catalyst evidence is unavailable."), active_weights),
        _component("Backtest evidence", _backtest_score(backtest), _backtest_text(backtest), active_weights),
        _component("Data quality", _data_quality(risk, company_metrics), _data_quality_text(company_metrics), active_weights),
    ]
    available_weight = sum(item["weight"] for item in components if item["score"] is not None)
    weighted = sum(item["score"] * item["weight"] for item in components if item["score"] is not None)
    score = round(weighted / available_weight, 1) if available_weight else 50.0
    coverage = round(available_weight, 1)
    posture = _posture(score, coverage)
    positives = [f"{item['factor']}: {item['score']:.1f}/100" for item in components if item["score"] is not None and item["score"] >= 60]
    negatives = [f"{item['factor']}: {item['score']:.1f}/100" for item in components if item["score"] is not None and item["score"] <= 40]
    improvements = [_improvement(item["factor"]) for item in components if item["score"] is None or item["score"] < 58]
    invalidations = _invalidations(committee_score, risk, environment, technical, catalyst, backtest)
    return {
        "score": score,
        "posture": posture,
        "coverage_percent": coverage,
        "components": components,
        "positive_contributors": positives or ["No factor currently provides strong positive confirmation."],
        "negative_contributors": negatives or ["No factor currently creates a strong negative signal."],
        "improvement_conditions": list(dict.fromkeys(improvements)),
        "invalidation_conditions": invalidations,
        "research_horizon": _horizon(technical, catalyst),
        "position_sizing_caution": _sizing_caution(risk, catalyst, coverage),
        "summary": f"Entry readiness is {posture.lower()} at {score:.1f}/100 with {coverage:.0f}% evidence coverage.",
        "disclosure": "This is a research posture, not a recommendation to buy, sell, or size a position.",
    }


def _component(factor: str, score: float | None, explanation: str, weights: dict[str, float]) -> dict[str, Any]:
    return {
        "factor": factor,
        "score": None if score is None else round(max(0, min(100, score)), 1),
        "weight": weights[factor],
        "explanation": explanation,
    }


def _posture(score: float, coverage: float) -> str:
    if coverage < 70:
        return "Insufficient evidence"
    if score >= 72:
        return "Favorable setup"
    if score >= 58:
        return "Cautiously favorable"
    if score >= 43:
        return "Wait for confirmation"
    return "Elevated risk"


def _technical_score(technical: dict[str, Any]) -> float | None:
    if technical.get("status") == "insufficient_history":
        return None
    spread = float(technical.get("spread_percent", 0))
    if technical.get("status") == "bullish":
        return min(90, 70 + max(0, spread) * 2)
    if technical.get("status") == "bearish":
        return max(10, 30 - abs(spread) * 2)
    return 50


def _catalyst_score(catalyst: dict[str, Any]) -> float | None:
    return {"Clear": 82, "Watch": 62, "Elevated": 35, "Event imminent": 15}.get(catalyst.get("readiness"))


def _backtest_score(backtest: dict[str, Any]) -> float | None:
    if backtest.get("status") != "complete":
        return None
    relative = float(backtest.get("total_return", 0)) - float(backtest.get("buy_hold_return", 0))
    drawdown = abs(float(backtest.get("max_drawdown", 0)))
    return max(0, min(100, 50 + relative * 2 - max(0, drawdown - 20)))


def _backtest_text(backtest: dict[str, Any]) -> str:
    if backtest.get("status") != "complete":
        return backtest.get("message", "Backtest evidence is unavailable.")
    return (f"Strategy returned {backtest.get('total_return', 0):+.2f}% versus "
            f"{backtest.get('buy_hold_return', 0):+.2f}% for buy and hold.")


def _data_quality(risk: dict[str, Any], metrics: dict[str, Any]) -> float:
    keys = (("price", "return_1y", "relative_return_1y", "annualized_volatility", "max_drawdown")
            if metrics.get("asset_type") == "ETF" else
            ("price", "pe_ratio", "profit_margin", "revenue_growth", "beta", "fifty_two_week_high", "fifty_two_week_low"))
    completeness = sum(metrics.get(key) is not None for key in keys) / len(keys) * 100
    return completeness * .6 + float(risk.get("coverage_percent", 0)) * .4


def _data_quality_text(metrics: dict[str, Any]) -> str:
    relevant = (("price", "return_1y", "relative_return_1y", "annualized_volatility", "max_drawdown")
                if metrics.get("asset_type") == "ETF" else metrics.keys())
    missing = [key.replace("_", " ") for key in relevant if metrics.get(key) is None]
    label = "ETF market metrics" if metrics.get("asset_type") == "ETF" else "company metrics"
    return f"All tracked {label} are available." if not missing else f"Missing {label}: " + ", ".join(missing) + "."


def _improvement(factor: str) -> str:
    return {
        "Committee conviction": "Stronger agreement across independent strategy assessments would improve readiness.",
        "Risk profile": "Lower volatility, drawdown, valuation, or event risk would improve readiness.",
        "Market environment": "A more supportive growth, inflation, rate, or geopolitical backdrop would improve readiness.",
        "Technical trend": "A confirmed Golden Cross or stronger price trend would improve readiness.",
        "Catalyst timing": "Allowing a high-impact catalyst to pass or become less uncertain would improve readiness.",
        "Backtest evidence": "Stronger out-of-sample-like historical results with controlled drawdowns would improve readiness.",
        "Data quality": "More complete and current provider data would improve confidence in the score.",
    }[factor]


def _invalidations(committee: float, risk: dict[str, Any], environment: dict[str, Any], technical: dict[str, Any],
                   catalyst: dict[str, Any], backtest: dict[str, Any]) -> list[str]:
    conditions = ["A material deterioration in company fundamentals or data quality would invalidate the current posture."]
    if committee >= 50:
        conditions.append("Committee score falling below 40 would invalidate current strategy support.")
    if float(risk.get("score", 50)) < 70:
        conditions.append("Risk rising above 70/100 would invalidate the current risk assumption.")
    if technical.get("status") == "bullish":
        conditions.append("A Death Cross would invalidate the current bullish technical confirmation.")
    if environment.get("label") not in {"Defensive", "Highly defensive"}:
        conditions.append("A defensive market-environment shift would weaken the setup.")
    if catalyst.get("readiness") != "Event imminent":
        conditions.append("A new high-impact event within 48 hours would require reassessment.")
    if backtest.get("status") == "complete" and float(backtest.get("total_return", 0)) >= 0:
        conditions.append("Backtest results turning materially negative would weaken historical support.")
    return conditions


def _horizon(technical: dict[str, Any], catalyst: dict[str, Any]) -> str:
    if catalyst.get("readiness") in {"Elevated", "Event imminent"}:
        return "Reassess after the near-term catalyst before relying on a longer-horizon setup."
    if technical.get("status") == "bullish":
        return "Medium term (approximately 3–12 months), with periodic reassessment."
    return "Short to medium term, pending stronger confirmation."


def _sizing_caution(risk: dict[str, Any], catalyst: dict[str, Any], coverage: float) -> str:
    if coverage < 70 or float(risk.get("score", 50)) >= 70 or catalyst.get("readiness") == "Event imminent":
        return "Evidence supports heightened caution; avoid treating the score as justification for a full-sized position."
    if float(risk.get("score", 50)) >= 50 or catalyst.get("readiness") == "Elevated":
        return "Moderate risk remains; staged research decisions may be more appropriate than a single entry assumption."
    return "Measured risk appears lower, but position size still depends on personal objectives, constraints, and loss tolerance."


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
