from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


PORTFOLIO_ACTION_SERVICE_VERSION = 1


def build_portfolio_action_plan(
    portfolio: dict[str, Any], beginner_guidance: list[dict[str, Any]],
    evidence_trust: dict[str, dict[str, Any]], position_plans: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Turn saved portfolio evidence into a prioritized, analysis-only review queue."""
    guidance_map = {str(item.get("Ticker")): item for item in beginner_guidance}
    plan_map = position_plans or {}
    rows = []
    for holding in portfolio.get("rows", []):
        ticker = str(holding.get("Ticker", ""))
        weight = float(holding.get("Portfolio weight", 0))
        risk = float(holding.get("Risk score", 50))
        guidance = guidance_map.get(ticker, {})
        trust = evidence_trust.get(ticker, {})
        sizing = plan_map.get(ticker, {})
        ceiling = _number(sizing.get("portfolio_allocation"))
        view = str(guidance.get("Beginner view", "Research first"))
        trust_status = str(trust.get("status", "Blocked"))

        if view == "Sell / reduce review":
            bucket, action = "Do now", "Reduce / exit thesis review"
            reason = "The saved beginner view contains a serious negative override."
        elif trust_status in {"Blocked", "Stale"} or holding.get("Freshness") == "Stale":
            bucket, action = "Do now", "Refresh evidence"
            reason = trust.get("summary", "Critical evidence is missing or stale.")
        elif ceiling is not None and weight > ceiling + 0.05:
            bucket, action = "Do now", "Trim-size review"
            reason = f"The {weight:.1f}% weight exceeds the saved {ceiling:.1f}% position ceiling."
        elif weight >= 35:
            bucket, action = "Do now", "Concentration review"
            reason = f"The holding represents {weight:.1f}% of covered exposure."
        elif risk >= 70 or view == "Avoid / review":
            bucket, action = "Review soon", "Risk / thesis review"
            reason = f"Risk is {risk:.1f}/100 and the saved view is {view}."
        elif trust_status in {"Demo", "Partial"}:
            bucket, action = "Review soon", "Validate evidence"
            reason = trust.get("summary", "Some evidence is simulated or incomplete.")
        elif view == "Buy candidate" and trust.get("buy_allowed") is True:
            if ceiling is None:
                bucket, action = "Review soon", "Build position ceiling"
                reason = "The evidence is constructive, but no saved sizing ceiling exists."
            elif weight < ceiling - 0.05:
                bucket, action = "Review soon", "Add-size review"
                reason = f"Live evidence is constructive and weight is below the saved {ceiling:.1f}% ceiling."
            else:
                bucket, action = "Monitor", "Hold / monitor"
                reason = "The holding is already near its saved position ceiling."
        else:
            bucket, action = "Monitor", "Hold / monitor"
            reason = guidance.get("Suggested next step", "Continue monitoring for material changes.")

        gap = None if ceiling is None else round(ceiling - weight, 2)
        rows.append({
            "Priority": bucket, "Ticker": ticker, "Action review": action,
            "Current weight": round(weight, 2), "Saved ceiling": ceiling,
            "Room to ceiling": gap, "Beginner view": view,
            "Evidence trust": trust_status, "Trust score": trust.get("score"),
            "Risk score": round(risk, 1), "Sector": holding.get("Sector", "Unknown"),
            "Why": reason, "Next step": _next_step(action, ticker),
        })

    order = {"Do now": 0, "Review soon": 1, "Monitor": 2}
    rows.sort(key=lambda item: (order[item["Priority"]], -item["Risk score"], item["Ticker"]))
    counts = {name: sum(row["Priority"] == name for row in rows) for name in order}
    trust_scores = [float(row["Trust score"]) for row in rows if row["Trust score"] is not None]
    portfolio_trust = round(sum(trust_scores) / len(trust_scores)) if trust_scores else None
    return {
        "created_at": datetime.now(timezone.utc).isoformat(), "rows": rows, "counts": counts,
        "portfolio_posture": portfolio.get("posture", "Unavailable"),
        "weighted_risk": portfolio.get("weighted_risk"), "weighted_beta": portfolio.get("weighted_beta"),
        "effective_positions": portfolio.get("effective_positions"), "sector_exposure": portfolio.get("sector_exposure", []),
        "exposure_warnings": portfolio.get("warnings", []), "portfolio_trust": portfolio_trust,
        "summary": (
            f"Atlas found {counts['Do now']} item(s) to address now, {counts['Review soon']} to review soon, "
            f"and {counts['Monitor']} to monitor."
        ),
        "disclosure": (
            "This is an educational portfolio review queue based on saved Atlas evidence. It is not personalized "
            "investment advice, a recommendation to trade, or an automated rebalancing instruction."
        ),
    }


def _number(value: Any) -> float | None:
    try:
        return round(float(value), 2) if value is not None else None
    except (TypeError, ValueError):
        return None


def _next_step(action: str, ticker: str) -> str:
    steps = {
        "Refresh evidence": f"Refresh {ticker} research and recheck its live-data trust status.",
        "Trim-size review": f"Compare {ticker} with the saved risk budget and concentration limit.",
        "Concentration review": f"Review whether {ticker} and its sector dominate portfolio risk.",
        "Reduce / exit thesis review": f"Review {ticker}'s invalidation evidence before deciding whether exposure should change.",
        "Risk / thesis review": f"Open {ticker}'s risks, SEC health, and thesis conditions.",
        "Validate evidence": f"Replace simulated or incomplete {ticker} evidence before acting on the label.",
        "Build position ceiling": f"Create and save a position-sizing plan for {ticker}.",
        "Add-size review": f"Recheck diversification, valuation, and the saved ceiling before considering additional {ticker} exposure.",
        "Hold / monitor": f"Monitor {ticker} for thesis, catalyst, risk, and trust changes.",
    }
    return steps[action]
