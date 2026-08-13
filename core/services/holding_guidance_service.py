from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.models.research import ResearchReport


HOLDING_GUIDANCE_SERVICE_VERSION = 2


def build_holding_guidance(
    tickers: list[str], reports: dict[str, ResearchReport],
    freshness_days: int = 7, now: datetime | None = None,
) -> dict[str, Any]:
    """Give evidence-based holding direction without requiring portfolio weights."""
    now = now or datetime.now(timezone.utc)
    rows = []
    for ticker in sorted(set(str(item).strip().upper() for item in tickers if str(item).strip())):
        report = reports.get(ticker)
        if report is None:
            rows.append(_row(
                ticker, "Research needed", "High", None, None, None,
                "No saved company report is available.",
                "Run full company research before changing exposure.",
            ))
            continue
        age = _age_days(report.created_at, now)
        risk = _number(report.risk.get("score"))
        readiness = _number(report.entry_readiness.get("score"))
        vote = str(report.committee_vote).lower()
        confidence = int(report.committee_confidence or 0)
        stale = age > freshness_days
        provider_text = str(report.provider).lower()
        demo = "demo" in provider_text or "synthetic" in provider_text

        if demo:
            direction, caution = "Research needed", "High"
            reason = "The latest report contains demo or synthetic evidence."
            next_step = "Replace simulated evidence with live research before changing exposure."
        elif stale:
            direction, caution = "Research needed", "High"
            reason = f"The latest report is {age:.0f} days old."
            next_step = "Refresh company research before relying on the prior conclusion."
        elif vote == "bearish" and confidence >= 60:
            direction, caution = "Consider less", "High"
            reason = f"The committee is bearish with {confidence}% confidence."
            next_step = "Review the bear case and thesis invalidation evidence before deciding."
        elif risk is not None and risk >= 70:
            direction, caution = "Consider less", "High"
            reason = f"Atlas risk is elevated at {risk:.1f}/100."
            next_step = "Review risk drivers, financial health, and upcoming catalysts."
        elif vote == "bullish" and confidence >= 65 and (risk is None or risk < 55) and (readiness or 0) >= 60:
            direction, caution = "Consider more", "Normal"
            reason = (
                f"The committee is bullish ({confidence}% confidence), risk is "
                f"{_display(risk)}, and entry readiness is {_display(readiness)}."
            )
            next_step = "Confirm valuation, diversification, and thesis conditions before adding exposure."
        elif vote == "bullish" and confidence >= 55:
            direction, caution = "Maintain / monitor", "Moderate"
            reason = (
                f"The committee is bullish, but risk ({_display(risk)}) or entry readiness "
                f"({_display(readiness)}) does not support a stronger signal."
            )
            next_step = "Monitor valuation, catalysts, and changes in committee conviction."
        elif vote == "neutral":
            direction, caution = "Maintain / monitor", "Moderate"
            reason = f"The committee remains neutral with {confidence}% confidence."
            next_step = "Wait for stronger fundamental, valuation, or catalyst confirmation."
        else:
            direction, caution = "Caution", "High"
            reason = "The saved evidence is not strong enough to support increasing exposure."
            next_step = "Review the latest risks and refresh weak or incomplete evidence."

        rows.append(_row(
            ticker, direction, caution, vote.title(), risk, readiness, reason, next_step,
            report.created_at, str(report.company_metrics.get("asset_type") or "Stock"),
        ))

    priority = {"High": 0, "Moderate": 1, "Normal": 2}
    direction_order = {"Consider less": 0, "Research needed": 1, "Caution": 2,
                       "Maintain / monitor": 3, "Consider more": 4}
    rows.sort(key=lambda row: (
        priority.get(row["Caution"], 9), direction_order.get(row["Direction"], 9), row["Ticker"],
    ))
    return {
        "rows": rows,
        "counts": {
            label: sum(row["Direction"] == label for row in rows)
            for label in ("Consider more", "Maintain / monitor", "Consider less", "Research needed", "Caution")
        },
        "summary": (
            f"Atlas reviewed {len(rows)} holding(s): "
            f"{sum(row['Direction'] == 'Consider more' for row in rows)} consider-more, "
            f"{sum(row['Direction'] == 'Consider less' for row in rows)} consider-less, and "
            f"{sum(row['Caution'] == 'High' for row in rows)} high-caution item(s)."
        ),
        "disclosure": (
            "Direction is an evidence-based research prompt, not a target portfolio weight or trade instruction. "
            "Atlas does not know brokerage balances, taxes, cash needs, or personal suitability."
        ),
    }


def _row(
    ticker: str, direction: str, caution: str, committee: str | None,
    risk: float | None, readiness: float | None, reason: str, next_step: str,
    updated: str | None = None, asset_type: str = "Unknown",
) -> dict[str, Any]:
    return {
        "Ticker": ticker, "Asset type": asset_type, "Direction": direction, "Caution": caution,
        "Committee": committee or "Unavailable", "Risk": risk,
        "Entry readiness": readiness, "Why": reason, "Next review": next_step,
        "Research updated": updated or "Never",
    }


def _age_days(value: str, now: datetime) -> float:
    observed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    return max(0.0, (now - observed.astimezone(timezone.utc)).total_seconds() / 86400)


def _number(value: Any) -> float | None:
    try:
        return round(float(value), 1) if value is not None else None
    except (TypeError, ValueError):
        return None


def _display(value: float | None) -> str:
    return "unavailable" if value is None else f"{value:.1f}/100"
