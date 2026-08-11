from __future__ import annotations

from datetime import date
from typing import Any


def assess_catalysts(ticker: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    symbol = ticker.strip().upper()
    today = date.today()
    relevant = []
    for raw in snapshot.get("events", []):
        if raw.get("scope") != "global" and symbol not in raw.get("affected", []):
            continue
        event = dict(raw)
        days = (date.fromisoformat(event["date"]) - today).days
        if days < 0:
            continue
        timing_weight = 1 if days <= 2 else .82 if days <= 7 else .58 if days <= 14 else .35 if days <= 30 else .18
        timing_risk = float(event.get("importance", 50)) * float(event.get("confidence", 50)) / 100 * timing_weight
        event.update({
            "days_until": days,
            "timing_risk": round(timing_risk, 1),
            "readiness": _event_readiness(days, float(event.get("importance", 50))),
        })
        relevant.append(event)
    relevant.sort(key=lambda item: (item["date"], -item["importance"]))
    high_events = [event for event in relevant if event["importance"] >= 70]
    if any(event["days_until"] <= 2 for event in high_events):
        readiness, risk_score = "Event imminent", 95
    elif any(event["days_until"] <= 7 for event in high_events):
        readiness, risk_score = "Elevated", 75
    elif any(event["days_until"] <= 30 for event in high_events):
        readiness, risk_score = "Watch", 45
    else:
        readiness, risk_score = "Clear", 20
    next_event = relevant[0] if relevant else None
    return {
        "ticker": symbol,
        "readiness": readiness,
        "risk_score": risk_score,
        "next_event": next_event,
        "events": relevant,
        "provider": snapshot.get("provider", "Unknown"),
        "retrieved_at": snapshot.get("retrieved_at", ""),
        "summary": _summary(readiness, next_event),
    }


def global_calendar(snapshot: dict[str, Any], tickers: list[str] | None = None) -> list[dict[str, Any]]:
    allowed = {ticker.upper() for ticker in (tickers or [])}
    rows = []
    today = date.today()
    for raw in snapshot.get("events", []):
        if raw.get("scope") == "company" and allowed and not allowed.intersection(raw.get("affected", [])):
            continue
        event = dict(raw)
        event["days_until"] = (date.fromisoformat(event["date"]) - today).days
        if event["days_until"] >= 0:
            rows.append(event)
    return sorted(rows, key=lambda item: (item["date"], -item["importance"]))


def _event_readiness(days: int, importance: float) -> str:
    if importance >= 70 and days <= 2:
        return "Event imminent"
    if importance >= 70 and days <= 7:
        return "Elevated"
    return "Watch" if days <= 30 else "Clear"


def _summary(readiness: str, event: dict[str, Any] | None) -> str:
    if event is None:
        return "No upcoming catalyst is available from the configured provider."
    return f"Catalyst readiness is {readiness.lower()}. Next event: {event['title']} in {event['days_until']} days."
