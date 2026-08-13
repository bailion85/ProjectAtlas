from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.models.research import ResearchReport


RANKING_MODES = ("Best opportunity", "Entry readiness", "Lowest risk", "Strongest momentum")


def rank_watchlist(tickers: list[str], reports: dict[str, ResearchReport], mode: str = "Best opportunity", weights: dict[str, float] | None = None, freshness_days: int = 7) -> dict[str, Any]:
    if mode not in RANKING_MODES:
        raise ValueError(f"Unsupported ranking mode: {mode}")
    active_weights = weights or {"committee": 45, "inverse_risk": 25, "momentum": 20, "environment": 10}
    rows = []
    missing = []
    for ticker in tickers:
        report = reports.get(ticker)
        if report is None:
            missing.append(ticker)
            continue
        risk_score = float(report.risk.get("score", 50))
        environment_score = float(report.market_environment.get("score", 50))
        relative = float(report.performance.get("periods", {}).get("1Y", {}).get("relative", 0))
        spread = float(report.technical.get("spread_percent", 0))
        momentum_score = _clamp(50 + relative * 1.25 + spread * 2)
        opportunity_score = round(sum((
            report.committee_score * active_weights["committee"],
            (100 - risk_score) * active_weights["inverse_risk"],
            momentum_score * active_weights["momentum"],
            environment_score * active_weights["environment"],
        )) / 100, 1)
        age_days = _age_days(report.created_at)
        cross = report.technical.get("latest_cross") or {}
        technical_label = cross.get("label") or report.technical.get("label", "Unavailable")
        catalyst = report.catalyst_calendar or {}
        next_event = catalyst.get("next_event") or {}
        readiness = report.entry_readiness or {}
        explanation = (
            f"Committee {report.committee_score:.1f}, risk {risk_score:.1f}, momentum {momentum_score:.1f}, "
            f"and market environment {environment_score:.1f}."
            f" Catalyst readiness is {catalyst.get('readiness', 'unavailable').lower()}."
        )
        rows.append({
            "Rank": 0,
            "Ticker": ticker,
            "Company": report.company,
            "Asset type": report.company_metrics.get("asset_type", "Stock"),
            "Opportunity score": opportunity_score,
            "Entry readiness": readiness.get("score"),
            "Entry posture": readiness.get("posture", "Unavailable"),
            "Committee score": report.committee_score,
            "Vote": report.committee_vote.title(),
            "Risk score": risk_score,
            "Risk level": report.risk.get("severity", "Unavailable"),
            "Momentum score": round(momentum_score, 1),
            "Technical signal": technical_label,
            "1Y vs S&P 500": round(relative, 2),
            "Market environment": round(environment_score, 1),
            "Catalyst readiness": catalyst.get("readiness", "Unavailable"),
            "Next catalyst": next_event.get("title", "Unavailable"),
            "Days to catalyst": next_event.get("days_until"),
            "Last analyzed": report.created_at[:19].replace("T", " ") + " UTC",
            "Freshness": "Stale" if age_days > freshness_days else "Current",
            "Why": explanation,
            "report_id": report.report_id,
        })
    key = {
        "Best opportunity": lambda row: row["Opportunity score"],
        "Entry readiness": lambda row: row["Entry readiness"] if row["Entry readiness"] is not None else -1,
        "Lowest risk": lambda row: -row["Risk score"],
        "Strongest momentum": lambda row: row["Momentum score"],
    }[mode]
    rows.sort(key=key, reverse=True)
    for rank, row in enumerate(rows, start=1):
        row["Rank"] = rank
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "rows": rows,
        "missing": missing,
        "stale": [row["Ticker"] for row in rows if row["Freshness"] == "Stale"],
    }


def _age_days(value: str) -> float:
    observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    return max(0, (datetime.now(timezone.utc) - observed).total_seconds() / 86400)


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, value))
