from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.models.research import ResearchReport


VALUATION_SERVICE_VERSION = 1


def suggested_assumptions(
    report: ResearchReport, financial_health: dict[str, Any] | None = None,
) -> dict[str, float]:
    """Create conservative, transparent defaults from a saved research report."""
    metrics = report.company_metrics
    growth = _rate(metrics.get("earnings_growth"), _rate(metrics.get("revenue_growth"), 0.08))
    margin = _rate(metrics.get("profit_margin"), 0.10)
    roe = _rate(metrics.get("return_on_equity"), 0.12)
    quality_adjustment = _clamp((margin - 0.10) * 12 + (roe - 0.12) * 8, -4, 6)
    health_adjustment = _health_adjustment(financial_health)
    base = _clamp(15 + growth * 60 + quality_adjustment + health_adjustment, 8, 40)
    return {
        "bear_multiple": round(_clamp(base * 0.72, 5, 30), 1),
        "base_multiple": round(base, 1),
        "bull_multiple": round(_clamp(base * 1.25, 10, 50), 1),
        "eps_adjustment": 0.0,
        "desired_margin": 20.0,
        "financial_health_adjustment": health_adjustment,
    }


def build_valuation(
    report: ResearchReport, assumptions: dict[str, Any] | None = None,
    financial_health: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metrics = report.company_metrics
    price = _positive(metrics.get("price"), "Current price")
    forward_pe = _optional_positive(metrics.get("forward_pe"))
    trailing_pe = _optional_positive(metrics.get("pe_ratio"))
    if forward_pe:
        forward_eps = price / forward_pe
        eps_source = "Current price divided by saved forward P/E"
    elif trailing_pe:
        growth = _rate(metrics.get("earnings_growth"), 0.0)
        forward_eps = price / trailing_pe * (1 + growth)
        eps_source = "Trailing implied EPS grown by the saved earnings-growth rate"
    else:
        raise ValueError("Valuation requires a current price and either forward or trailing P/E in the saved report.")

    defaults = suggested_assumptions(report, financial_health)
    values = {**defaults, **(assumptions or {})}
    bear = _bounded(values["bear_multiple"], "Bear multiple", 1, 100)
    base = _bounded(values["base_multiple"], "Base multiple", 1, 100)
    bull = _bounded(values["bull_multiple"], "Bull multiple", 1, 100)
    if not bear <= base <= bull:
        raise ValueError("Multiples must be ordered from bear to base to bull.")
    eps_adjustment = _bounded(values.get("eps_adjustment", 0), "EPS adjustment", -50, 100)
    desired_margin = _bounded(values.get("desired_margin", 20), "Desired margin of safety", 0, 60)
    adjusted_eps = forward_eps * (1 + eps_adjustment / 100)

    scenario_values = {"Bear": adjusted_eps * bear, "Base": adjusted_eps * base, "Bull": adjusted_eps * bull}
    scenario_multiples = {"Bear": bear, "Base": base, "Bull": bull}
    scenarios = [
        {
            "Scenario": name,
            "Forward EPS": round(adjusted_eps, 2),
            "P/E multiple": multiple,
            "Estimated value": round(scenario_values[name], 2),
            "Upside / downside": round((scenario_values[name] / price - 1) * 100, 1),
        }
        for name, multiple in scenario_multiples.items()
    ]
    base_value = scenario_values["Base"]
    margin_of_safety = (base_value - price) / base_value * 100
    entry_high = base_value * (1 - desired_margin / 100)
    entry_low = min(scenario_values["Bear"], entry_high)
    status = _status(price, scenario_values["Bear"], base_value, entry_high)

    sensitivity = []
    for change in (-10, 0, 10):
        scenario_eps = adjusted_eps * (1 + change / 100)
        for name, multiple in scenario_multiples.items():
            sensitivity.append({
                "EPS change": f"{change:+d}%",
                "Multiple": name,
                "Estimated value": round(scenario_eps * multiple, 2),
                "Upside / downside": round((scenario_eps * multiple / price - 1) * 100, 1),
            })

    available = sum(metrics.get(key) is not None for key in (
        "price", "forward_pe", "pe_ratio", "earnings_growth", "revenue_growth",
        "profit_margin", "return_on_equity",
    ))
    return {
        "ticker": report.ticker,
        "company": report.company,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "report_id": report.report_id,
        "report_created_at": report.created_at,
        "provider": report.provider,
        "current_price": round(price, 2),
        "forward_eps": round(forward_eps, 4),
        "adjusted_eps": round(adjusted_eps, 4),
        "eps_source": eps_source,
        "assumptions": {
            "bear_multiple": bear, "base_multiple": base, "bull_multiple": bull,
            "eps_adjustment": eps_adjustment, "desired_margin": desired_margin,
        },
        "financial_health_score": financial_health.get("score") if financial_health else None,
        "financial_health_adjustment": defaults["financial_health_adjustment"],
        "scenarios": scenarios,
        "bear_value": round(scenario_values["Bear"], 2),
        "base_value": round(base_value, 2),
        "bull_value": round(scenario_values["Bull"], 2),
        "margin_of_safety": round(margin_of_safety, 1),
        "entry_low": round(entry_low, 2),
        "entry_high": round(entry_high, 2),
        "implied_multiple": round(price / adjusted_eps, 1),
        "status": status,
        "sensitivity": sensitivity,
        "data_coverage": round(available / 7 * 100),
        "summary": (
            f"{report.ticker} is {status.lower()} under the selected assumptions. The base scenario is "
            f"${base_value:,.2f}, versus a saved report price of ${price:,.2f}."
        ),
        "disclosure": (
            "This assumption-driven earnings-multiple model is a research aid, not a forecast or investment advice. "
            "Small changes in earnings or the selected multiple can materially change the result."
        ),
    }


def _status(price: float, bear_value: float, base_value: float, entry_high: float) -> str:
    if price <= bear_value:
        return "Below bear value"
    if price <= entry_high:
        return "Within research entry range"
    if price <= base_value:
        return "Below base value"
    return "Above base value"


def _rate(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number / 100 if abs(number) > 2 else number


def _positive(value: Any, label: str) -> float:
    number = _optional_positive(value)
    if number is None:
        raise ValueError(f"{label} is missing from the saved report.")
    return number


def _optional_positive(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _bounded(value: Any, label: str, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a number.") from exc
    if not minimum <= number <= maximum:
        raise ValueError(f"{label} must be between {minimum:g} and {maximum:g}.")
    return number


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return min(max(value, minimum), maximum)


def _health_adjustment(financial_health: dict[str, Any] | None) -> float:
    if not financial_health:
        return 0.0
    try:
        score = float(financial_health.get("score", 50))
    except (TypeError, ValueError):
        return 0.0
    return round(_clamp((score - 50) / 10, -3, 3), 1)
