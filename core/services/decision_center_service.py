from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.models.research import ResearchReport
from core.services.change_tracking_service import compare_reports
from core.services.thesis_service import evaluate_thesis


DECISION_CENTER_SERVICE_VERSION = 4
PRIORITIES = ("Critical", "High", "Medium", "Monitor")
_ORDER = {priority: index for index, priority in enumerate(PRIORITIES)}


def build_decision_center(
    watchlist: list[str], reports: dict[str, ResearchReport], report_histories: dict[str, list[ResearchReport]],
    theses: list[dict[str, Any]], alerts: list[dict[str, Any]], portfolio_positions: list[dict[str, Any]],
    stress_result: dict[str, Any] | None, provider_status: dict[str, Any], freshness_days: int = 7,
    valuations: list[dict[str, Any]] | None = None,
    financial_health: list[dict[str, Any]] | None = None,
    evidence_trust: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    remaining = provider_status.get("quota_remaining")
    if remaining == 0:
        _add(items, "Critical", "Data provider", "ALL", "Daily Alpha Vantage budget exhausted",
             "New fundamentals and news are unavailable until the UTC reset.", "Use cached research or review Data readiness.")
    elif remaining is not None and remaining <= 4:
        _add(items, "High", "Data provider", "ALL", "Alpha Vantage budget is nearly exhausted",
             f"Only {remaining} tracked request(s) remain today.", "Prioritize essential research or wait for the UTC reset.")

    thesis_map = {item["ticker"]: item for item in theses}
    health_map = {item["ticker"]: item for item in (financial_health or [])}
    for ticker, trust in (evidence_trust or {}).items():
        if trust.get("status") in {"Demo", "Stale", "Blocked"}:
            priority = "High" if trust.get("status") in {"Stale", "Blocked"} else "Medium"
            _add(items, priority, "Evidence trust", ticker, f"Evidence is {str(trust['status']).lower()}",
                 trust.get("summary", "Critical evidence needs review."), "Refresh missing or stale evidence before relying on the label.")
    for ticker, thesis in thesis_map.items():
        evaluation = evaluate_thesis(thesis, reports.get(ticker), financial_health=health_map.get(ticker))
        priority = {"Invalidated": "Critical", "Review due": "High", "Opportunity": "Medium", "Needs report": "High"}.get(evaluation["status"])
        if priority:
            _add(items, priority, "Thesis", ticker, f"Thesis is {evaluation['status'].lower()}",
                 evaluation["summary"], "Open Thesis tracker and review the saved assumptions.")

    for alert in alerts:
        severity = str(alert.get("severity", "Moderate"))
        priority = "Critical" if severity == "Critical" else "High" if severity == "High" else "Medium"
        _add(items, priority, "Alert", alert.get("ticker", "ALL"), alert.get("title", "Atlas alert"),
             alert.get("message", "An alert condition was detected."), "Open Alerts and inspect the supporting report.")

    for valuation in valuations or []:
        ticker = str(valuation.get("ticker", "ALL"))
        margin = float(valuation.get("margin_of_safety", 0))
        status = str(valuation.get("status", ""))
        if status == "Above base value" or margin <= -20:
            _add(items, "High" if margin <= -20 else "Medium", "Valuation", ticker, "Price is above base valuation",
                 f"The latest saved model shows a {margin:+.1f}% margin of safety.", "Open Valuation lab and review the assumptions.")
        elif status == "Within research entry range":
            _add(items, "Medium", "Valuation", ticker, "Price is within the modeled entry range",
                 f"The latest saved range is ${float(valuation.get('entry_low', 0)):,.2f} to ${float(valuation.get('entry_high', 0)):,.2f}.",
                 "Open Valuation lab and compare the model with the saved thesis.")

    for health in financial_health or []:
        ticker = str(health.get("ticker", "ALL"))
        score = float(health.get("score", 50))
        coverage = float(health.get("coverage", 0))
        if score < 50:
            priority = "High" if score <= 35 else "Medium"
            _add(items, priority, "Financial health", ticker, "SEC financial health is weakening",
                 f"The latest saved SEC trend score is {score:.0f}/100.",
                 "Open Financial health and review the deteriorating filing trends.")
        elif coverage < 50:
            _add(items, "Medium", "Financial health", ticker, "SEC metric coverage is limited",
                 f"Only {coverage:.0f}% of Atlas financial-health metrics were available.",
                 "Open Financial health and confirm the issuer's available SEC facts.")

    positions = {item["ticker"]: float(item["allocation"]) for item in portfolio_positions}
    valuation_symbols = [str(item.get("ticker")) for item in (valuations or []) if item.get("ticker")]
    health_symbols = [str(item.get("ticker")) for item in (financial_health or []) if item.get("ticker")]
    symbols = list(dict.fromkeys(watchlist + list(positions) + list(thesis_map) + valuation_symbols + health_symbols))
    for ticker in symbols:
        report = reports.get(ticker)
        if report is None:
            _add(items, "High", "Research coverage", ticker, "No saved research report",
                 "Atlas cannot rank or monitor this company without a report.", "Run Research for this ticker.")
            continue
        age = _age_days(report.created_at)
        if age > freshness_days:
            _add(items, "Medium", "Research freshness", ticker, "Research is stale",
                 f"The latest report is {age:.0f} days old; the configured limit is {freshness_days} days.", "Refresh the company research.")
        event = (report.catalyst_calendar.get("next_event") or {})
        days = event.get("days_until")
        if (days is not None and int(days) <= 30 and report.catalyst_calendar.get("live") is True
                and not report.catalyst_calendar.get("stale") and event.get("source_live") is True
                and not event.get("source_stale")):
            priority = "High" if int(days) <= 7 else "Medium"
            _add(items, priority, "Catalyst", ticker, event.get("title", "Catalyst approaching"),
                 f"The event is scheduled in {days} day(s).", "Review the catalyst evidence and thesis conditions.")
        risk = float(report.risk.get("score", 50))
        if ticker in positions and risk >= 60:
            priority = "High" if risk >= 70 else "Medium"
            _add(items, priority, "Portfolio risk", ticker, "Elevated holding risk",
                 f"Risk is {risk:.1f}/100 and the saved allocation is {positions[ticker]:.1f}%.", "Review Portfolio exposure and the holding thesis.")
        history = report_histories.get(ticker, [])
        if len(history) >= 2:
            change = compare_reports(history[0], history[1])
            if change["thesis_status"] in {"Invalidated", "Weakening"}:
                priority = "Critical" if change["thesis_status"] == "Invalidated" else "High"
                _add(items, priority, "Research change", ticker, f"Research is {change['thesis_status'].lower()}",
                     change["summary"], "Open Changes and inspect the material evidence movement.")

    if stress_result:
        for row in stress_result.get("rows", []):
            impact = float(row.get("Estimated impact", 0))
            if impact <= -12:
                priority = "High" if impact <= -20 else "Medium"
                _add(items, priority, "Stress exposure", row["Ticker"], f"{stress_result['scenario']} vulnerability",
                     f"Estimated scenario sensitivity is {impact:+.1f}%.", "Open Stress test and review the scenario drivers.")

    unique = {}
    for item in items:
        unique[(item["Category"], item["Ticker"], item["Signal"])] = item
    ordered = sorted(unique.values(), key=lambda item: (_ORDER[item["Priority"]], item["Ticker"], item["Category"]))
    counts = {priority: sum(item["Priority"] == priority for item in ordered) for priority in PRIORITIES}
    guidance = build_beginner_guidance(
        symbols, reports, theses, alerts, portfolio_positions, valuations or [], freshness_days,
        financial_health or [],
        evidence_trust,
    )
    return {
        "created_at": datetime.now(timezone.utc).isoformat(), "items": ordered, "counts": counts,
        "beginner_guidance": guidance,
        "companies": len({item["Ticker"] for item in ordered if item["Ticker"] != "ALL"}),
        "summary": "No immediate research follow-ups were detected." if not ordered else
                   f"Atlas found {len(ordered)} follow-up item(s), including {counts['Critical']} critical and {counts['High']} high priority.",
        "disclosure": "The Decision Center prioritizes research follow-ups. It does not recommend or execute trades.",
    }


def build_beginner_guidance(
    symbols: list[str], reports: dict[str, ResearchReport], theses: list[dict[str, Any]],
    alerts: list[dict[str, Any]], portfolio_positions: list[dict[str, Any]],
    valuations: list[dict[str, Any]], freshness_days: int = 7,
    financial_health: list[dict[str, Any]] | None = None,
    evidence_trust: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Translate Atlas evidence into conservative, educational research postures."""
    thesis_map = {item["ticker"]: item for item in theses}
    valuation_map = {item["ticker"]: item for item in valuations}
    health_map = {item["ticker"]: item for item in (financial_health or [])}
    owned = {item["ticker"] for item in portfolio_positions if float(item.get("allocation", 0)) > 0}
    alert_map: dict[str, list[dict[str, Any]]] = {}
    for alert in alerts:
        alert_map.setdefault(str(alert.get("ticker", "ALL")), []).append(alert)

    results = []
    for ticker in dict.fromkeys(symbols):
        report = reports.get(ticker)
        if report is None:
            results.append({
                "Ticker": ticker, "Beginner view": "Research first", "Confidence": "Low",
                "Score": None, "Owned": ticker in owned,
                "Plain-language summary": "Atlas does not have enough saved evidence to assess this company.",
                "What supports it": "None yet",
                "What could go wrong": "Price, valuation, risk, and trend have not been reviewed.",
                "Suggested next step": "Run Research, then build and save a Valuation lab scenario.",
            })
            continue

        age = _age_days(report.created_at)
        risk = float(report.risk.get("score", 50))
        readiness = float(report.entry_readiness.get("score", 50))
        committee = float(getattr(report, "committee_score", 50))
        valuation = valuation_map.get(ticker)
        thesis = thesis_map.get(ticker)
        health = health_map.get(ticker)
        thesis_evaluation = evaluate_thesis(thesis, report, financial_health=health) if thesis else None
        technical = str(report.technical.get("status", "unknown"))
        ticker_alerts = alert_map.get(ticker, []) + alert_map.get("ALL", [])
        serious_alert = any(str(item.get("severity")) in {"Critical", "High"} for item in ticker_alerts)
        trust = (evidence_trust or {}).get(ticker)

        evidence_scores = [committee, readiness, 100 - risk]
        positives: list[str] = []
        cautions: list[str] = []
        if committee >= 55:
            positives.append(f"Committee score is constructive at {committee:.0f}/100")
        elif committee < 45:
            cautions.append(f"Committee score is weak at {committee:.0f}/100")
        if readiness >= 60:
            positives.append(f"Entry readiness is {readiness:.0f}/100")
        elif readiness < 45:
            cautions.append(f"Entry readiness is only {readiness:.0f}/100")
        if risk < 50:
            positives.append(f"Risk score is comparatively lower at {risk:.0f}/100")
        elif risk >= 65:
            cautions.append(f"Risk score is elevated at {risk:.0f}/100")
        if technical == "bullish":
            positives.append("The 50-day average is above the 200-day average")
        elif technical == "bearish":
            cautions.append("The 50-day average is below the 200-day average")
        if health:
            health_score = float(health.get("score", 50))
            evidence_scores.append(health_score)
            if health_score >= 65:
                positives.append(f"SEC financial-health score is strong at {health_score:.0f}/100")
            elif health_score < 50:
                cautions.append(f"SEC financial-health score is weakening at {health_score:.0f}/100")
        else:
            cautions.append("No SEC financial-health analysis has been saved")

        valuation_favorable = False
        if valuation:
            margin = float(valuation.get("margin_of_safety", 0))
            evidence_scores.append(_clamp(50 + margin, 0, 100))
            valuation_favorable = str(valuation.get("status")) in {
                "Below bear value", "Within research entry range", "Below base value",
            } and margin >= 0
            if valuation_favorable:
                positives.append(f"Saved valuation shows a {margin:+.0f}% margin of safety")
            else:
                cautions.append(f"Saved valuation shows a {margin:+.0f}% margin of safety")
        else:
            cautions.append("No valuation version has been saved")
        if thesis_evaluation:
            if thesis_evaluation["status"] == "Invalidated":
                cautions.append("The saved thesis is invalidated")
            elif thesis_evaluation["status"] in {"On track", "Opportunity"}:
                positives.append(f"The saved thesis is {thesis_evaluation['status'].lower()}")
        else:
            cautions.append("No personal thesis has been saved")
        if serious_alert:
            cautions.append("A high-priority or critical alert needs review")
        if age > freshness_days:
            cautions.append(f"The report is {age:.0f} days old")
        if trust and trust.get("status") != "Live":
            cautions.append(trust.get("summary", "Evidence quality needs review"))

        score = round(sum(evidence_scores) / len(evidence_scores))
        negative_override = (
            report.committee_vote == "bearish" or risk >= 70 or serious_alert
            or bool(thesis_evaluation and thesis_evaluation["status"] == "Invalidated")
            or bool(health and float(health.get("score", 50)) <= 35)
        )
        stale_override = age > freshness_days * 2
        if stale_override:
            view = "Research first"
            next_step = "Refresh Research before making a decision from this screen."
        elif negative_override:
            view = "Sell / reduce review" if ticker in owned else "Avoid / review"
            next_step = "Review the negative evidence and your thesis before adding, holding, or reducing exposure."
        elif score >= 62 and readiness >= 55 and valuation_favorable:
            view = "Buy candidate"
            next_step = "Check diversification and position size, then confirm the valuation assumptions and risks."
        else:
            view = "Hold" if ticker in owned else "Watch"
            next_step = "Wait for stronger valuation, readiness, or trend evidence; define what would change your view."

        if view == "Buy candidate" and trust and not trust.get("buy_allowed", False):
            view = "Hold" if ticker in owned else "Watch"
            next_step = "Refresh missing or stale evidence before treating this company as a Buy candidate."

        coverage = (3 + int(technical in {"bullish", "bearish", "neutral"}) + int(bool(valuation))
                    + int(bool(thesis)) + int(bool(health)))
        confidence = "High" if coverage >= 6 and age <= freshness_days else "Moderate" if coverage >= 4 else "Low"
        if trust:
            levels = {"Low": 0, "Moderate": 1, "High": 2}
            cap = trust.get("confidence_cap", "Low")
            confidence = min((confidence, cap), key=lambda item: levels.get(item, 0))
        results.append({
            "Ticker": ticker, "Beginner view": view, "Confidence": confidence, "Score": score,
            "Owned": ticker in owned,
            "Plain-language summary": _beginner_summary(view, ticker),
            "What supports it": "; ".join(positives) if positives else "No strong positive signal yet",
            "What could go wrong": "; ".join(cautions) if cautions else "No major flag detected; normal market risk still applies",
            "Suggested next step": next_step,
            "Trust status": trust.get("status") if trust else "Not assessed",
            "Trust score": trust.get("score") if trust else None,
        })
    return results


def _beginner_summary(view: str, ticker: str) -> str:
    explanations = {
        "Buy candidate": "The saved evidence is constructive and valuation is not above the model, but this still needs your review.",
        "Hold": "The evidence does not currently justify a strong change to a saved position.",
        "Watch": "The evidence is mixed or the price does not yet offer enough valuation support.",
        "Sell / reduce review": "One or more serious warning signs conflict with continuing to hold the position unchanged.",
        "Avoid / review": "One or more serious warning signs make this a poor candidate until the evidence improves.",
        "Research first": "The saved information is missing or too old for a responsible label.",
    }
    return f"{ticker}: {explanations[view]}"


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return min(max(value, minimum), maximum)


def _add(items: list[dict[str, Any]], priority: str, category: str, ticker: str, signal: str, why: str, follow_up: str) -> None:
    items.append({"Priority": priority, "Category": category, "Ticker": ticker,
                  "Signal": signal, "Why flagged": why, "Research follow-up": follow_up})


def _age_days(value: str) -> float:
    observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    return max(0, (datetime.now(timezone.utc) - observed).total_seconds() / 86400)
