from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.services.macro_service import score_macro_environment


def analyze_market_environment(event_snapshot: dict[str, Any], macro: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    scored_events = []
    weighted_direction = 0.0
    total_weight = 0.0
    for raw in event_snapshot.get("events", []):
        event = dict(raw)
        published = datetime.fromisoformat(str(event["published_at"]).replace("Z", "+00:00"))
        age_days = max(0, (now - published).total_seconds() / 86400)
        recency = max(.2, 1 - age_days / 45)
        confidence = max(0, min(100, float(event.get("confidence", 50)))) / 100
        weight = recency * confidence
        contribution = float(event.get("direction", 0)) * weight
        event.update({
            "age_days": round(age_days, 1),
            "recency_weight": round(recency, 3),
            "weighted_impact": round(contribution, 1),
            "impact": _impact(abs(float(event.get("direction", 0)))),
            "expected_direction": _direction(float(event.get("direction", 0))),
        })
        scored_events.append(event)
        weighted_direction += contribution
        total_weight += weight
    event_signal = weighted_direction / total_weight if total_weight else 0
    event_score = max(0, min(100, 50 + event_signal / 2))
    macro_score, macro_thesis = score_macro_environment(None, macro)
    score = round(event_score * .55 + macro_score * .45, 1)
    label, context = _regime(score)
    scored_events.sort(key=lambda item: abs(item["weighted_impact"]), reverse=True)
    return {
        "score": score,
        "label": label,
        "buying_context": context,
        "event_score": round(event_score, 1),
        "macro_score": macro_score,
        "macro_thesis": macro_thesis,
        "events": scored_events,
        "event_provider": event_snapshot.get("provider", "Unknown"),
        "macro_provider": macro.get("provider", "Unknown"),
        "data_as_of": event_snapshot.get("retrieved_at", now.isoformat()),
        "summary": f"The market environment is {label.lower()} at {score:.1f}/100. {context}",
    }


def _impact(value: float) -> str:
    return "Critical" if value >= 80 else "High" if value >= 60 else "Moderate" if value >= 35 else "Low"


def _direction(value: float) -> str:
    return "Market supportive" if value >= 15 else "Market negative" if value <= -15 else "Mixed"


def _regime(score: float) -> tuple[str, str]:
    if score >= 72:
        return "Favorable", "Broad conditions may support measured buying, subject to company-specific valuation and risk."
    if score >= 58:
        return "Cautiously favorable", "Selective buying may be reasonable, but position sizing and company quality remain important."
    if score >= 43:
        return "Neutral", "There is no strong market-level advantage; prioritize company-specific evidence and gradual entries."
    if score >= 28:
        return "Defensive", "Elevated uncertainty favors patience, smaller positions, and stronger margins of safety."
    return "Highly defensive", "Severe market-level risk favors capital preservation and waiting for clearer evidence."
