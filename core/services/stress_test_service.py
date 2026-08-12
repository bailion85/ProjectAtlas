from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.models.research import ResearchReport


STRESS_TEST_SERVICE_VERSION = 1
SCENARIOS: dict[str, dict[str, Any]] = {
    "Recession": {"market_shock": -20, "rate_change_bps": -150, "inflation_change": -1,
                  "oil_change": -15, "sector_shocks": {"Consumer Cyclical": -7, "Industrials": -5, "Financial Services": -5, "Consumer Defensive": 3, "Utilities": 3}},
    "Persistent inflation": {"market_shock": -12, "rate_change_bps": 100, "inflation_change": 2,
                             "oil_change": 20, "sector_shocks": {"Energy": 8, "Basic Materials": 4, "Consumer Cyclical": -5, "Real Estate": -6}},
    "Interest-rate increase": {"market_shock": -10, "rate_change_bps": 150, "inflation_change": 0,
                               "oil_change": 0, "sector_shocks": {"Technology": -7, "Real Estate": -8, "Consumer Cyclical": -4, "Financial Services": 3}},
    "Interest-rate cuts": {"market_shock": 7, "rate_change_bps": -150, "inflation_change": 0,
                            "oil_change": 0, "sector_shocks": {"Technology": 5, "Real Estate": 6, "Financial Services": -3}},
    "Oil and geopolitical shock": {"market_shock": -10, "rate_change_bps": 25, "inflation_change": 1,
                                    "oil_change": 40, "sector_shocks": {"Energy": 15, "Industrials": -5, "Consumer Cyclical": -6, "Airlines": -12}},
    "Technology correction": {"market_shock": -8, "rate_change_bps": 25, "inflation_change": 0,
                               "oil_change": 0, "sector_shocks": {"Technology": -20, "Communication Services": -12}},
    "Broad market decline": {"market_shock": -25, "rate_change_bps": 0, "inflation_change": 0,
                              "oil_change": -10, "sector_shocks": {}},
}


def analyze_stress_scenario(
    positions: list[dict[str, Any]], reports: dict[str, ResearchReport], scenario_name: str,
    custom: dict[str, Any] | None = None, theses: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    scenario = _scenario(scenario_name, custom)
    cleaned = _positions(positions)
    if not cleaned:
        raise ValueError("Save at least one portfolio holding before running a stress test.")
    total = sum(item["allocation"] for item in cleaned)
    rows, missing = [], []
    sector_contributions: dict[str, float] = {}
    for position in cleaned:
        ticker = position["ticker"]
        report = reports.get(ticker)
        weight = position["allocation"] / total * 100
        if report is None:
            missing.append(ticker)
            continue
        sector = str(report.company_metrics.get("sector") or "Unknown")
        beta = _number(report.company_metrics.get("beta"), 1.0)
        risk = _number(report.risk.get("score"), 50)
        estimate, drivers = _holding_impact(scenario, sector, beta, risk)
        uncertainty = max(3.0, abs(estimate) * .25 + 2)
        low, high = estimate - uncertainty, estimate + uncertainty
        contribution = estimate * weight / 100
        sector_contributions[sector] = sector_contributions.get(sector, 0) + contribution
        rows.append({
            "Ticker": ticker, "Company": report.company, "Sector": sector,
            "Portfolio weight": round(weight, 2), "Beta": round(beta, 2), "Risk score": round(risk, 1),
            "Estimated impact": round(estimate, 1), "Lower range": round(low, 1),
            "Upper range": round(high, 1), "Portfolio contribution": round(contribution, 2),
            "Primary drivers": "; ".join(drivers),
        })
    if not rows:
        raise ValueError("Run research for at least one saved holding before stress testing.")
    covered_weight = sum(row["Portfolio weight"] for row in rows)
    estimated = sum(row["Portfolio contribution"] for row in rows)
    lower = sum(row["Lower range"] * row["Portfolio weight"] / 100 for row in rows)
    upper = sum(row["Upper range"] * row["Portfolio weight"] / 100 for row in rows)
    rows.sort(key=lambda row: row["Estimated impact"])
    thesis_map = {item["ticker"]: item for item in (theses or [])}
    thesis_reviews = []
    for row in rows:
        thesis = thesis_map.get(row["Ticker"])
        if thesis and (row["Estimated impact"] <= -12 or thesis.get("stance") in {"Buy candidate", "Hold"} and row["Estimated impact"] <= -8):
            thesis_reviews.append({
                "Ticker": row["Ticker"], "Stance": thesis.get("stance", "Watch"),
                "Reason": f"Scenario impact of {row['Estimated impact']:.1f}% warrants reviewing the saved assumptions and invalidation conditions.",
            })
    return {
        "created_at": datetime.now(timezone.utc).isoformat(), "scenario": scenario_name,
        "assumptions": scenario, "estimated_impact": round(estimated, 1),
        "lower_range": round(lower, 1), "upper_range": round(upper, 1),
        "covered_weight": round(covered_weight, 1), "posture": _posture(estimated),
        "rows": rows, "missing": missing, "thesis_reviews": thesis_reviews,
        "sector_contributions": [
            {"Sector": sector, "Portfolio impact": round(value, 2)}
            for sector, value in sorted(sector_contributions.items(), key=lambda item: item[1])
        ],
        "summary": _summary(scenario_name, estimated, rows, covered_weight),
        "disclosure": "Scenario impacts are transparent sensitivity estimates, not forecasts, price targets, investment advice, or recommendations to trade.",
    }


def _scenario(name: str, custom: dict[str, Any] | None) -> dict[str, Any]:
    if name != "Custom":
        if name not in SCENARIOS:
            raise ValueError("Choose a valid stress scenario.")
        return {**SCENARIOS[name], "sector_shocks": dict(SCENARIOS[name]["sector_shocks"])}
    values = custom or {}
    return {
        "market_shock": _bounded(values.get("market_shock", -10), -80, 80, "Market shock"),
        "rate_change_bps": _bounded(values.get("rate_change_bps", 0), -500, 500, "Rate change"),
        "inflation_change": _bounded(values.get("inflation_change", 0), -10, 10, "Inflation change"),
        "oil_change": _bounded(values.get("oil_change", 0), -80, 200, "Oil-price change"),
        "sector_shocks": {str(key): float(value) for key, value in values.get("sector_shocks", {}).items()},
    }


def _holding_impact(scenario: dict[str, Any], sector: str, beta: float, risk: float) -> tuple[float, list[str]]:
    market = float(scenario["market_shock"]) * max(.3, min(2.5, beta))
    sector_shock = float(scenario["sector_shocks"].get(sector, 0))
    rate_coefficients = {"Technology": -3, "Communication Services": -2, "Consumer Cyclical": -2,
                         "Real Estate": -4, "Utilities": -2, "Financial Services": 1}
    inflation_coefficients = {"Energy": 2, "Basic Materials": 1.5, "Consumer Cyclical": -2,
                              "Consumer Defensive": -1, "Technology": -1}
    oil_coefficients = {"Energy": 2, "Consumer Cyclical": -.8, "Industrials": -.5}
    rate = rate_coefficients.get(sector, -.5) * float(scenario["rate_change_bps"]) / 100
    inflation = inflation_coefficients.get(sector, -.25) * float(scenario["inflation_change"])
    oil = oil_coefficients.get(sector, 0) * float(scenario["oil_change"]) / 10
    estimate = (market + sector_shock + rate + inflation + oil) * (1 + (risk - 50) / 250)
    drivers = [f"market {scenario['market_shock']:+.0f}% × beta {beta:.2f}"]
    if sector_shock:
        drivers.append(f"{sector} shock {sector_shock:+.0f}%")
    if abs(rate) >= .5:
        drivers.append(f"rate sensitivity {rate:+.1f}%")
    if abs(inflation) >= .5:
        drivers.append(f"inflation sensitivity {inflation:+.1f}%")
    if abs(oil) >= .5:
        drivers.append(f"oil sensitivity {oil:+.1f}%")
    return max(-90, min(90, estimate)), drivers


def _positions(positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    combined: dict[str, float] = {}
    for item in positions:
        ticker = str(item.get("ticker") or item.get("Ticker") or "").strip().upper()
        allocation = float(item.get("allocation", item.get("Allocation", 0)) or 0)
        if ticker and allocation > 0:
            combined[ticker] = combined.get(ticker, 0) + allocation
    return [{"ticker": ticker, "allocation": allocation} for ticker, allocation in combined.items()]


def _bounded(value: Any, minimum: float, maximum: float, label: str) -> float:
    number = float(value)
    if not minimum <= number <= maximum:
        raise ValueError(f"{label} must be between {minimum:g} and {maximum:g}.")
    return number


def _number(value: Any, default: float) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _posture(impact: float) -> str:
    if impact <= -20:
        return "Severe stress"
    if impact <= -12:
        return "High stress"
    if impact <= -5:
        return "Moderate stress"
    if impact < 0:
        return "Mild stress"
    return "Positive sensitivity"


def _summary(name: str, impact: float, rows: list[dict[str, Any]], coverage: float) -> str:
    weakest = ", ".join(row["Ticker"] for row in rows[:3])
    return f"Under {name.lower()}, the covered portfolio sensitivity is {impact:+.1f}%. The most adversely exposed holdings are {weakest}. Coverage is {coverage:.1f}%."
