from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from core.models.research import ResearchReport


THESIS_SERVICE_VERSION = 1
STANCES = ("Buy candidate", "Watch", "Hold", "Avoid")
CONFIDENCE_LEVELS = ("Low", "Medium", "High")


def validate_thesis(thesis: dict[str, Any]) -> dict[str, Any]:
    ticker = str(thesis.get("ticker", "")).strip().upper()
    if not ticker:
        raise ValueError("Choose a company for the thesis.")
    stance = str(thesis.get("stance", "Watch"))
    confidence = str(thesis.get("confidence", "Medium"))
    if stance not in STANCES:
        raise ValueError("Choose a valid thesis stance.")
    if confidence not in CONFIDENCE_LEVELS:
        raise ValueError("Choose a valid confidence level.")
    entry_low = _optional_number(thesis.get("entry_low"))
    entry_high = _optional_number(thesis.get("entry_high"))
    fair_value = _optional_number(thesis.get("fair_value"))
    if entry_low is not None and entry_high is not None and entry_low > entry_high:
        raise ValueError("The lower entry price cannot exceed the upper entry price.")
    if any(value is not None and value < 0 for value in (entry_low, entry_high, fair_value)):
        raise ValueError("Price values cannot be negative.")
    review_date = str(thesis.get("review_date", "")).strip()
    if review_date:
        date.fromisoformat(review_date)
    max_risk = float(thesis.get("max_risk_score", 70))
    min_readiness = float(thesis.get("min_readiness_score", 50))
    if not 0 <= max_risk <= 100 or not 0 <= min_readiness <= 100:
        raise ValueError("Risk and readiness thresholds must be between 0 and 100.")
    return {
        "ticker": ticker, "stance": stance, "confidence": confidence,
        "entry_low": entry_low, "entry_high": entry_high, "fair_value": fair_value,
        "supporting_reasons": _clean_list(thesis.get("supporting_reasons")),
        "risks": _clean_list(thesis.get("risks")),
        "invalidation_conditions": _clean_list(thesis.get("invalidation_conditions")),
        "catalysts": _clean_list(thesis.get("catalysts")),
        "review_date": review_date, "max_risk_score": max_risk,
        "min_readiness_score": min_readiness,
        "notes": str(thesis.get("notes", "")).strip(),
    }


def evaluate_thesis(
    thesis: dict[str, Any], report: ResearchReport | None, today: date | None = None,
    financial_health: dict[str, Any] | None = None,
) -> dict[str, Any]:
    today = today or datetime.now(timezone.utc).date()
    flags: list[dict[str, str]] = []
    review_date = thesis.get("review_date")
    if review_date and date.fromisoformat(review_date) <= today:
        flags.append({"severity": "Review", "factor": "Review date", "message": f"Review was due {review_date}."})
    if report is None:
        return {"status": "Needs report", "flags": flags, "price": None,
                "summary": "Run a research report to evaluate this thesis against current Atlas evidence."}

    price = _optional_number(report.company_metrics.get("price"))
    low, high = thesis.get("entry_low"), thesis.get("entry_high")
    if price is not None and low is not None and high is not None:
        if low <= price <= high:
            flags.append({"severity": "Opportunity", "factor": "Entry range", "message": f"Price ${price:,.2f} is inside the saved ${low:,.2f}–${high:,.2f} range."})
        elif price < low:
            flags.append({"severity": "Review", "factor": "Entry range", "message": f"Price ${price:,.2f} is below the saved entry range; reassess the assumptions."})

    stance = thesis["stance"]
    invalidated = False
    if stance in {"Buy candidate", "Hold"} and report.committee_vote == "bearish":
        invalidated = True
        flags.append({"severity": "Invalidated", "factor": "Committee vote", "message": "Atlas's latest committee vote is bearish."})
    risk_score = float(report.risk.get("score", 50))
    if risk_score >= float(thesis["max_risk_score"]):
        invalidated = True
        flags.append({"severity": "Invalidated", "factor": "Risk threshold", "message": f"Risk score {risk_score:.1f} reached the saved limit of {thesis['max_risk_score']:.1f}."})
    readiness = float(report.entry_readiness.get("score", 50))
    if stance == "Buy candidate" and readiness < float(thesis["min_readiness_score"]):
        flags.append({"severity": "Caution", "factor": "Entry readiness", "message": f"Readiness {readiness:.1f} is below the saved minimum of {thesis['min_readiness_score']:.1f}."})
    if financial_health:
        health_score = float(financial_health.get("score", 50))
        if stance in {"Buy candidate", "Hold"} and health_score <= 35:
            invalidated = True
            flags.append({
                "severity": "Invalidated", "factor": "Financial health",
                "message": f"SEC financial-health score {health_score:.0f}/100 crossed Atlas's severe-deterioration threshold.",
            })
        elif health_score < 50:
            flags.append({
                "severity": "Caution", "factor": "Financial health",
                "message": f"SEC financial-health score is weakening at {health_score:.0f}/100.",
            })

    status = "Invalidated" if invalidated else "Review due" if any(f["severity"] == "Review" for f in flags) else "Opportunity" if any(f["severity"] == "Opportunity" for f in flags) else "On track"
    return {
        "status": status, "flags": flags, "price": price,
        "summary": f"{thesis['ticker']} is {status.lower()} against report #{report.report_id or 'current'}.",
    }


def _clean_list(value: Any) -> list[str]:
    if isinstance(value, str):
        value = value.splitlines()
    return [str(item).strip() for item in (value or []) if str(item).strip()]


def _optional_number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)
