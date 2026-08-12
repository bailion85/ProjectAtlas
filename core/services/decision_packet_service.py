from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.models.research import ResearchReport
from core.services.thesis_service import evaluate_thesis


DECISION_PACKET_SERVICE_VERSION = 1


def build_decision_packet(
    ticker: str, report: ResearchReport | None, beginner_guidance: dict[str, Any] | None,
    workflow: dict[str, Any], valuation: dict[str, Any] | None,
    thesis: dict[str, Any] | None, financial_health: dict[str, Any] | None,
    position_plan: dict[str, Any] | None, alerts: list[dict[str, Any]],
    evidence_trust: dict[str, Any] | None = None,
) -> dict[str, Any]:
    symbol = ticker.strip().upper()
    company = report.company if report else symbol
    thesis_evaluation = (
        evaluate_thesis(thesis, report, financial_health=financial_health) if thesis else None
    )
    relevant_alerts = [
        alert for alert in alerts if str(alert.get("ticker")) in {symbol, "ALL"}
    ]
    missing = [
        row["Evidence"] for row in workflow.get("checks", [])
        if row.get("Status") in {"Missing", "Stale", "Review"}
    ]
    view = (beginner_guidance or {}).get("Beginner view", "Research first")
    supports = (beginner_guidance or {}).get("What supports it", "No complete positive evidence is saved.")
    cautions = (beginner_guidance or {}).get("What could go wrong", "Key evidence is missing.")
    technical = report.technical if report else {}
    environment = report.market_environment if report else {}
    catalyst = report.catalyst_calendar if report else {}
    return {
        "ticker": symbol, "company": company, "created_at": datetime.now(timezone.utc).isoformat(),
        "beginner_view": view,
        "evidence_confidence": (beginner_guidance or {}).get("Confidence", "Low"),
        "evidence_score": (beginner_guidance or {}).get("Score"),
        "plain_language_summary": (beginner_guidance or {}).get(
            "Plain-language summary", f"{symbol}: complete the missing research before assigning a decision posture."
        ),
        "supports": supports, "cautions": cautions,
        "next_step": (beginner_guidance or {}).get("Suggested next step", workflow.get("next_step")),
        "workflow": workflow, "missing_evidence": missing,
        "report": report.to_dict() if report else None,
        "committee": {
            "vote": report.committee_vote.title(), "confidence": report.committee_confidence,
            "score": report.committee_score,
        } if report else None,
        "technical": technical,
        "environment": environment,
        "next_catalyst": catalyst.get("next_event") if catalyst else None,
        "valuation": valuation, "thesis": thesis, "thesis_evaluation": thesis_evaluation,
        "financial_health": financial_health, "position_plan": position_plan,
        "alerts": relevant_alerts,
        "evidence_trust": evidence_trust,
        "data_watermark": (evidence_trust or {}).get("watermark", "EVIDENCE TRUST NOT ASSESSED"),
        "sources": _sources(report, financial_health, valuation),
        "disclosure": (
            "Project Atlas is an analysis-only research tool. This decision packet is not personalized investment "
            "advice and does not constitute a recommendation or an instruction to trade."
        ),
    }


def _sources(
    report: ResearchReport | None, financial_health: dict[str, Any] | None,
    valuation: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    sources = []
    if report:
        sources.append({
            "Evidence": "Research report", "Provider": report.provider,
            "Observed": report.data_as_of, "Saved": report.created_at,
        })
        macro_provider = report.macro.get("provider") if report.macro else None
        if macro_provider:
            sources.append({
                "Evidence": "Economic indicators", "Provider": macro_provider,
                "Observed": report.macro.get("observed_at", report.data_as_of), "Saved": report.created_at,
            })
        calendar_provider = report.catalyst_calendar.get("provider") if report.catalyst_calendar else None
        if calendar_provider:
            sources.append({
                "Evidence": "Catalyst calendar", "Provider": calendar_provider,
                "Observed": report.catalyst_calendar.get("retrieved_at", report.data_as_of),
                "Saved": report.created_at,
            })
    if financial_health:
        sources.append({
            "Evidence": "SEC financial health", "Provider": financial_health.get("provider", "SEC EDGAR"),
            "Observed": financial_health.get("retrieved_at"), "Saved": financial_health.get("saved_at"),
        })
    if valuation:
        sources.append({
            "Evidence": "Valuation model", "Provider": "Atlas saved assumptions",
            "Observed": valuation.get("report_created_at"), "Saved": valuation.get("saved_at"),
        })
    return sources
