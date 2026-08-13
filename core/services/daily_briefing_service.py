from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.models.research import ResearchReport


DAILY_BRIEFING_SERVICE_VERSION = 1
_PRIORITY = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}


def build_daily_briefing(
    reports: dict[str, ResearchReport], portfolio_positions: list[dict[str, Any]],
    alerts: list[dict[str, Any]], discovery: dict[str, Any] | None,
    provider_status: dict[str, Any], freshness_days: int = 7,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build a no-request morning brief entirely from saved Atlas evidence."""
    now = now or datetime.now(timezone.utc)
    ordered_reports = sorted(reports.values(), key=lambda report: report.created_at, reverse=True)
    newest = ordered_reports[0] if ordered_reports else None
    age = _age_days(newest.created_at, now) if newest else None
    environment = dict(newest.market_environment) if newest else {}
    live_environment = bool(newest and not _is_demo(newest) and age is not None and age <= freshness_days)
    market_label = str(environment.get("label") or "Unavailable")
    market_score = environment.get("score")
    if not newest:
        market_status = "Missing"
        market_message = "Run company research to save the first market-environment snapshot."
    elif age is not None and age > freshness_days:
        market_status = "Stale"
        market_message = f"The newest saved market evidence is {age:.0f} days old. Refresh research before relying on it."
    elif _is_demo(newest):
        market_status = "Demo"
        market_message = "The market posture is illustrative because the newest report contains demo evidence."
    else:
        market_status = "Live saved evidence"
        market_message = str(environment.get("buying_context") or environment.get("summary") or "Review company-specific evidence.")

    catalysts = []
    for report in ordered_reports:
        calendar = report.catalyst_calendar or {}
        event = calendar.get("next_event") or {}
        days = event.get("days_until")
        if (not event or days is None or int(days) < 0 or int(days) > 30 or calendar.get("live") is not True
                or calendar.get("stale") or event.get("source_live") is not True or event.get("source_stale")):
            continue
        catalysts.append({
            "Ticker": report.ticker, "Event": event.get("title", "Upcoming catalyst"),
            "Date": event.get("date"), "Days": int(days), "Importance": event.get("importance"),
            "Source": event.get("source", calendar.get("provider", "Unknown")),
        })
    catalysts.sort(key=lambda row: (row["Days"], -(float(row["Importance"] or 0))))

    selected_alerts = sorted(alerts, key=lambda item: (
        _PRIORITY.get(str(item.get("severity")), 9), str(item.get("created_at", ""))
    ))[:8]
    alert_rows = [{
        "Severity": item.get("severity", "Low"), "Ticker": item.get("ticker", "ALL"),
        "Alert": item.get("title", "Review alert"), "Why": item.get("message", ""),
    } for item in selected_alerts]

    positions = []
    for position in portfolio_positions:
        ticker = str(position.get("ticker", "")).upper()
        raw_allocation = position.get("allocation")
        allocation = float(raw_allocation) if raw_allocation not in (None, "") else None
        report = reports.get(ticker)
        risk = float(report.risk.get("score", 50)) if report else None
        readiness = float(report.entry_readiness.get("score", 50)) if report else None
        if report is None:
            priority, review = "High", "Run research; this holding has no saved report."
        elif risk is not None and risk >= 70:
            priority, review = "High", "Review elevated risk and the holding thesis."
        elif _age_days(report.created_at, now) > freshness_days:
            priority, review = "Medium", "Refresh stale company evidence."
        else:
            priority, review = "Monitor", "No urgent saved-evidence flag; continue monitoring."
        positions.append({
            "Priority": priority, "Ticker": ticker, "Allocation": round(allocation, 1) if allocation is not None else None,
            "Risk": risk, "Entry readiness": readiness, "Review today": review,
        })
    position_order = {"High": 0, "Medium": 1, "Monitor": 2}
    positions.sort(key=lambda row: (position_order[row["Priority"]], -(row["Allocation"] or 0)))

    ideas = []
    for row in (discovery or {}).get("rows", []):
        if row.get("On radar") is True or row.get("Research label") == "Pass for now":
            continue
        ideas.append({
            "Rank": row.get("Rank"), "Ticker": row.get("Ticker"), "Label": row.get("Research label"),
            "Score": row.get("Discovery score"), "Data status": row.get("Data status"),
            "Why it surfaced": row.get("Why it surfaced"),
        })
    ideas.sort(key=lambda row: (row["Rank"] or 999, -(float(row["Score"] or 0))))
    ideas = ideas[:5]

    quota_remaining = provider_status.get("quota_remaining")
    degraded = quota_remaining == 0 or int(provider_status.get("demo_fallbacks", 0) or 0) > 0
    data_status = "Degraded" if degraded else "Ready"
    data_note = (
        "Live price/history may remain available, but new Alpha Vantage fundamentals or news are capped until reset."
        if degraded else "No current provider blocker is recorded."
    )
    actions = []
    if market_status in {"Missing", "Stale", "Demo"}:
        actions.append({"Priority": "High", "Action": "Refresh market evidence", "Where": "Company research", "Why": market_message})
    for row in alert_rows[:3]:
        actions.append({"Priority": row["Severity"], "Action": f"Review {row['Ticker']} alert", "Where": "Alerts", "Why": row["Alert"]})
    for row in positions:
        if row["Priority"] != "Monitor":
            actions.append({"Priority": row["Priority"], "Action": f"Review {row['Ticker']} holding", "Where": "Holdings guidance", "Why": row["Review today"]})
    if ideas:
        actions.append({"Priority": "Medium", "Action": "Review new Discovery leads", "Where": "Discover", "Why": f"{len(ideas)} saved candidate(s) are outside your radar."})
    actions = sorted(actions, key=lambda row: _PRIORITY.get(row["Priority"], 9))[:8]

    posture = "Cautious" if market_label in {"Defensive", "Highly defensive"} or degraded else (
        "Constructive" if market_label in {"Favorable", "Cautiously favorable"} else "Selective"
    )
    return {
        "generated_at": now.isoformat(), "posture": posture,
        "market": {"label": market_label, "score": market_score, "status": market_status,
                   "message": market_message, "source": newest.provider if newest else "No saved report",
                   "as_of": newest.data_as_of if newest else None, "live": live_environment},
        "data": {"status": data_status, "note": data_note, "quota_remaining": quota_remaining,
                 "last_source": provider_status.get("last_source", "No requests yet")},
        "alerts": alert_rows, "catalysts": catalysts[:8], "portfolio": positions,
        "discovery": ideas, "actions": actions,
        "summary": _summary(posture, len(alert_rows), len(catalysts), len(ideas)),
        "disclosure": "This briefing organizes saved research evidence. It is not investment advice and does not execute trades.",
    }


def _age_days(value: str, now: datetime) -> float:
    observed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    return max(0.0, (now - observed).total_seconds() / 86400)


def _is_demo(report: ResearchReport) -> bool:
    sources = " ".join((report.provider, str(report.market_environment.get("event_provider", "")),
                        str(report.market_environment.get("macro_provider", "")))).lower()
    return "demo" in sources or "not live" in sources


def _summary(posture: str, alerts: int, catalysts: int, ideas: int) -> str:
    return (
        f"Today's saved-evidence posture is {posture.lower()}. Atlas found {alerts} active alert(s), "
        f"{catalysts} verified catalyst(s) within 30 days, and {ideas} Discovery idea(s) outside your radar."
    )
