from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.models.research import ResearchReport


EVIDENCE_TRUST_SERVICE_VERSION = 1
_WEIGHTS = {"Market and fundamentals": 30, "Technical history": 20, "Economic context": 20,
            "Catalyst calendar": 15, "SEC filings": 15}


def assess_evidence_trust(
    report: ResearchReport | None, financial_health: dict[str, Any] | None = None,
    freshness_days: int = 7, now: datetime | None = None,
) -> dict[str, Any]:
    """Score source quality and freshness without treating all missing evidence equally."""
    now = now or datetime.now(timezone.utc)
    rows: list[dict[str, Any]] = []
    observations: list[tuple[str, datetime]] = []

    if report is None:
        rows.extend([
            _row("Market and fundamentals", "Blocked", 0, "No saved company research report."),
            _row("Technical history", "Blocked", 0, "No price history is available."),
            _row("Economic context", "Missing", 0, "No economic context is saved."),
            _row("Catalyst calendar", "Missing", 0, "No event calendar is saved."),
            _row("SEC filings", "Missing", 0, "No SEC financial-health review is saved."),
        ])
    else:
        report_age = _age(report.created_at, now)
        observations += _observations([("Research report", report.data_as_of), ("Report saved", report.created_at)])
        market_demo = _demo(report.provider)
        if market_demo:
            rows.append(_row("Market and fundamentals", "Demo", 25, f"{report.provider}; illustrative, not live."))
        elif report_age > freshness_days * 2:
            rows.append(_row("Market and fundamentals", "Stale", 20, f"Report is {report_age:.0f} days old."))
        elif report_age > freshness_days:
            rows.append(_row("Market and fundamentals", "Stale", 55, f"Report is {report_age:.0f} days old."))
        else:
            rows.append(_row("Market and fundamentals", "Live", 100, f"{report.provider}; saved {report_age:.1f} days ago."))

        technical_status = str(report.technical.get("status", "")).lower()
        technical_insufficient = technical_status in {"", "unknown", "unavailable", "insufficient_history"}
        if technical_insufficient:
            rows.append(_row("Technical history", "Blocked", 0, "The 50/200-day trend lacks sufficient history."))
        elif market_demo:
            rows.append(_row("Technical history", "Demo", 25, "The moving-average result uses demo prices."))
        elif report_age > freshness_days:
            rows.append(_row("Technical history", "Stale", 45, f"Technical evidence is tied to a {report_age:.0f}-day-old report."))
        else:
            rows.append(_row("Technical history", "Live", 100, "The saved report contains a usable 50/200-day trend."))

        macro = report.macro or {}
        macro_provider = str(macro.get("provider", ""))
        observations += _observations([("Economic context", macro.get("observed_at"))])
        macro_stale = bool(macro.get("stale"))
        if not macro:
            rows.append(_row("Economic context", "Missing", 0, "No economic indicators are saved."))
        elif _demo(macro_provider):
            rows.append(_row("Economic context", "Demo", 25, f"{macro_provider}; illustrative, not live."))
        elif macro_stale:
            rows.append(_row("Economic context", "Stale", 45, "One or more economic observations are stale."))
        else:
            rows.append(_row("Economic context", "Live", 100, macro_provider or "Live economic observations are saved."))

        calendar = report.catalyst_calendar or {}
        calendar_provider = str(calendar.get("provider", ""))
        observations += _observations([("Catalyst calendar", calendar.get("retrieved_at"))])
        if not calendar:
            rows.append(_row("Catalyst calendar", "Missing", 0, "No catalyst calendar is saved."))
        elif _demo(calendar_provider) or calendar.get("live") is False:
            rows.append(_row("Catalyst calendar", "Demo", 25, f"{calendar_provider or 'Calendar'} is not live."))
        elif calendar.get("stale"):
            rows.append(_row("Catalyst calendar", "Stale", 45, "The saved catalyst calendar is stale."))
        else:
            rows.append(_row("Catalyst calendar", "Live", 100, calendar_provider or "Live calendar evidence is saved."))

        if financial_health:
            sec_provider = str(financial_health.get("provider", "SEC EDGAR"))
            observations += _observations([("SEC review", financial_health.get("retrieved_at") or financial_health.get("saved_at"))])
            sec_age = _age(financial_health.get("retrieved_at") or financial_health.get("saved_at"), now)
            if _demo(sec_provider):
                rows.append(_row("SEC filings", "Demo", 25, f"{sec_provider}; illustrative, not live."))
            elif sec_age > 30:
                rows.append(_row("SEC filings", "Stale", 55, f"The SEC review was retrieved {sec_age:.0f} days ago."))
            else:
                rows.append(_row("SEC filings", "Live", 100, f"{sec_provider}; retrieved {sec_age:.0f} days ago."))
        else:
            rows.append(_row("SEC filings", "Missing", 0, "No SEC financial-health review is saved."))

    score = round(sum(row["Score"] * _WEIGHTS[row["Evidence"]] for row in rows) / 100)
    row_map = {row["Evidence"]: row for row in rows}
    critical = [row_map[name]["Status"] for name in ("Market and fundamentals", "Technical history", "Economic context")]
    buy_allowed = all(status == "Live" for status in critical)
    statuses = {row["Status"] for row in rows}
    if "Blocked" in critical:
        status = "Blocked"
    elif "Demo" in critical:
        status = "Demo"
    elif "Stale" in critical:
        status = "Stale"
    elif statuses <= {"Live"}:
        status = "Live"
    else:
        status = "Partial"

    warnings = []
    if not buy_allowed:
        warnings.append("Atlas will not show Buy candidate until critical market, technical, and economic evidence is live and current.")
    if observations:
        dates = [item[1] for item in observations]
        spread = (max(dates) - min(dates)).total_seconds() / 86400
        if spread > 30:
            warnings.append(f"Evidence observation dates span {spread:.0f} days; compare sources before relying on the combined view.")
    else:
        spread = None
    confidence_cap = "High" if status == "Live" else "Moderate" if status == "Partial" else "Low"
    return {
        "score": score, "status": status, "components": rows, "buy_allowed": buy_allowed,
        "confidence_cap": confidence_cap, "warnings": warnings, "observation_spread_days": spread,
        "watermark": f"{status.upper()} EVIDENCE - TRUST {score}/100",
        "summary": _summary(status, score),
    }


def build_trust_alert(ticker: str, trust: dict[str, Any], anchor: Any) -> dict[str, Any] | None:
    status = trust.get("status")
    if status not in {"Demo", "Stale", "Blocked"}:
        return None
    severity = "High" if status in {"Stale", "Blocked"} else "Moderate"
    symbol = ticker.strip().upper()
    return {
        "ticker": symbol, "alert_type": "evidence_trust", "severity": severity,
        "title": f"{symbol}: evidence trust is {str(status).lower()}",
        "message": trust.get("summary", "Critical evidence needs review."),
        "fingerprint": f"trust:{symbol}:{anchor}:{status}:{trust.get('score')}",
        "payload": {"status": status, "score": trust.get("score"), "components": trust.get("components", [])},
    }


def _row(evidence: str, status: str, score: float, details: str) -> dict[str, Any]:
    return {"Evidence": evidence, "Status": status, "Score": score, "Details": details}


def _demo(value: str) -> bool:
    text = str(value).lower()
    return any(word in text for word in ("demo", "illustrative", "not live", "fallback"))


def _parse(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.strptime(str(value)[:10], "%Y-%m-%d")
        except ValueError:
            return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _age(value: Any, now: datetime) -> float:
    parsed = _parse(value)
    return 9999 if parsed is None else max(0, (now - parsed).total_seconds() / 86400)


def _observations(values: list[tuple[str, Any]]) -> list[tuple[str, datetime]]:
    return [(label, parsed) for label, value in values if (parsed := _parse(value)) is not None]


def _summary(status: str, score: int) -> str:
    meanings = {
        "Live": "Critical evidence is live and current.",
        "Partial": "Critical evidence is usable, but optional evidence is missing or needs review.",
        "Demo": "Critical evidence includes simulated or fallback data.",
        "Stale": "Critical evidence is older than the configured freshness limit.",
        "Blocked": "Critical evidence is missing or technically insufficient.",
    }
    return f"{meanings[status]} Evidence trust is {score}/100."
