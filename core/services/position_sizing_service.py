from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any


POSITION_SIZING_SERVICE_VERSION = 1
SIZING_PRESETS = {
    "Conservative": {"risk_percent": 0.5, "max_allocation": 5.0},
    "Balanced": {"risk_percent": 1.0, "max_allocation": 10.0},
    "Aggressive": {"risk_percent": 2.0, "max_allocation": 15.0},
}


def build_position_plan(
    ticker: str, portfolio_value: float, entry_price: float, invalidation_price: float,
    risk_percent: float, max_allocation: float, risk_score: float | None = None,
    readiness_score: float | None = None, financial_health_score: float | None = None,
    existing_allocation: float = 0.0, sector_allocation: float = 0.0, preset: str = "Custom",
) -> dict[str, Any]:
    symbol = ticker.strip().upper()
    if not symbol:
        raise ValueError("Choose a company for the position plan.")
    portfolio_value = _between(portfolio_value, "Portfolio value", 1, 1_000_000_000)
    entry_price = _between(entry_price, "Planned entry price", 0.01, 10_000_000)
    invalidation_price = _between(invalidation_price, "Thesis-invalidation price", 0.01, 10_000_000)
    if invalidation_price >= entry_price:
        raise ValueError("The thesis-invalidation price must be below the planned entry price.")
    risk_percent = _between(risk_percent, "Maximum portfolio risk", 0.1, 10)
    max_allocation = _between(max_allocation, "Maximum company allocation", 1, 100)
    existing_allocation = _between(existing_allocation, "Existing allocation", 0, 100)
    sector_allocation = _between(sector_allocation, "Sector allocation", 0, 100)

    modifiers = []
    factor = 1.0
    if risk_score is not None and float(risk_score) >= 70:
        factor *= 0.5
        modifiers.append("Elevated Atlas risk reduced the concentration limit by 50%")
    elif risk_score is not None and float(risk_score) >= 60:
        factor *= 0.75
        modifiers.append("Above-average Atlas risk reduced the concentration limit by 25%")
    if financial_health_score is not None and float(financial_health_score) <= 35:
        factor *= 0.5
        modifiers.append("Severe SEC financial-health weakness reduced the remaining limit by 50%")
    elif financial_health_score is not None and float(financial_health_score) < 50:
        factor *= 0.75
        modifiers.append("Weakening SEC financial health reduced the remaining limit by 25%")
    if readiness_score is not None and float(readiness_score) < 45:
        factor *= 0.75
        modifiers.append("Low entry readiness reduced the remaining limit by 25%")

    adjusted_max_allocation = max(1.0, round(max_allocation * factor, 2))
    per_share_loss = entry_price - invalidation_price
    risk_budget = portfolio_value * risk_percent / 100
    risk_limited_shares = math.floor(risk_budget / per_share_loss)
    allocation_limited_shares = math.floor(portfolio_value * adjusted_max_allocation / 100 / entry_price)
    shares = max(0, min(risk_limited_shares, allocation_limited_shares))
    position_value = shares * entry_price
    allocation = position_value / portfolio_value * 100
    loss_at_invalidation = shares * per_share_loss
    limiting_factor = "Risk budget" if risk_limited_shares <= allocation_limited_shares else "Concentration limit"
    warnings = []
    if existing_allocation >= adjusted_max_allocation:
        warnings.append(
            f"The saved {existing_allocation:.1f}% allocation already meets or exceeds the adjusted "
            f"{adjusted_max_allocation:.1f}% company limit."
        )
    if sector_allocation >= 30:
        warnings.append(f"The related sector already represents {sector_allocation:.1f}% of the saved portfolio.")
    if shares == 0:
        warnings.append("The selected limits do not permit one full share at the planned entry price.")
    return {
        "ticker": symbol, "created_at": datetime.now(timezone.utc).isoformat(), "preset": preset,
        "portfolio_value": round(portfolio_value, 2), "entry_price": round(entry_price, 2),
        "invalidation_price": round(invalidation_price, 2), "risk_percent": risk_percent,
        "risk_budget": round(risk_budget, 2), "per_share_loss": round(per_share_loss, 2),
        "max_allocation": max_allocation, "adjusted_max_allocation": adjusted_max_allocation,
        "risk_limited_shares": risk_limited_shares, "allocation_limited_shares": allocation_limited_shares,
        "suggested_shares": shares, "position_value": round(position_value, 2),
        "portfolio_allocation": round(allocation, 2), "loss_at_invalidation": round(loss_at_invalidation, 2),
        "limiting_factor": limiting_factor, "existing_allocation": existing_allocation,
        "sector_allocation": sector_allocation, "risk_score": risk_score,
        "readiness_score": readiness_score, "financial_health_score": financial_health_score,
        "modifiers": modifiers, "warnings": warnings,
        "summary": (
            f"The modeled ceiling is {shares:,} share(s), worth ${position_value:,.2f} or "
            f"{allocation:.2f}% of the portfolio. Loss at the saved invalidation price would be "
            f"about ${loss_at_invalidation:,.2f}."
        ),
        "disclosure": (
            "This is an educational risk-budget estimate, not personalized investment advice or a trade instruction. "
            "A market gap can cause an actual loss to exceed the estimate."
        ),
    }


def _between(value: Any, label: str, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a number.") from exc
    if not minimum <= number <= maximum:
        raise ValueError(f"{label} must be between {minimum:g} and {maximum:g}.")
    return number
