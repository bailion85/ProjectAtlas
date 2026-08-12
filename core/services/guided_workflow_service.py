from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.models.research import ResearchReport


GUIDED_WORKFLOW_SERVICE_VERSION = 1


def build_company_workflow(
    ticker: str, watchlist: list[str], report: ResearchReport | None,
    valuation: dict[str, Any] | None, thesis: dict[str, Any] | None,
    financial_health: dict[str, Any] | None, alerts: list[dict[str, Any]],
    freshness_days: int,
) -> dict[str, Any]:
    symbol = ticker.strip().upper()
    checks = []
    _check(checks, "Watchlist", symbol in watchlist, "Company is saved for monitoring.",
           "Add this company to the watchlist.")
    report_fresh = bool(report and _age_days(report.created_at) <= freshness_days)
    if report is None:
        checks.append(_row("Research report", "Missing", "No committee report is saved.", "Run company research."))
    elif report_fresh:
        checks.append(_row("Research report", "Ready", f"Report #{report.report_id} is current.", "Review the decision evidence."))
    else:
        age = _age_days(report.created_at)
        checks.append(_row("Research report", "Stale", f"The report is {age:.0f} days old.", "Refresh company research."))
    _check(checks, "SEC financial health", bool(financial_health),
           f"SEC score {financial_health.get('score')}/100 is saved." if financial_health else "",
           "Analyze the latest SEC filing.")
    _check(checks, "Valuation", bool(valuation),
           f"Saved model status: {valuation.get('status')}." if valuation else "",
           "Build and save a valuation scenario.")
    _check(checks, "Personal thesis", bool(thesis),
           f"Saved stance: {thesis.get('stance')}." if thesis else "",
           "Record your thesis and invalidation conditions.")
    serious = [alert for alert in alerts if alert.get("ticker") in {symbol, "ALL"}
               and str(alert.get("severity")) in {"Critical", "High"}]
    checks.append(_row(
        "Warnings", "Review" if serious else "Ready",
        f"{len(serious)} high-priority or critical alert(s) require review." if serious else "No serious unread alert is saved.",
        "Open Alerts and review the evidence." if serious else "Continue monitoring.",
    ))
    ready = sum(row["Status"] == "Ready" for row in checks)
    completion = round(ready / len(checks) * 100)
    next_row = next((row for row in checks if row["Status"] in {"Missing", "Stale", "Review"}), None)
    return {
        "ticker": symbol, "checks": checks, "completion": completion,
        "ready": ready, "total": len(checks),
        "next_step": next_row["Next step"] if next_row else "Review the saved evidence and keep monitoring for changes.",
        "summary": (
            f"{symbol} has {ready} of {len(checks)} workflow checks ready. "
            f"Next: {next_row['Next step'] if next_row else 'monitor for material changes.'}"
        ),
    }


def build_setup_status(
    market_provider_name: str, macro_provider_name: str, calendar_provider_name: str,
    sec_configured: bool, pdf_available: bool,
) -> list[dict[str, str]]:
    return [
        _setup("Market data", not market_provider_name.startswith("Demo"), market_provider_name),
        _setup("Economic data", not macro_provider_name.startswith("Demo"), macro_provider_name),
        _setup("Event calendar", not calendar_provider_name.startswith("Demo"), calendar_provider_name),
        _setup("SEC filings", sec_configured, "Configured" if sec_configured else "SEC_USER_AGENT is missing"),
        _setup("PDF reports", pdf_available, "Available" if pdf_available else "PDF dependency is missing"),
    ]


def _check(rows: list[dict[str, str]], evidence: str, ready: bool, details: str, missing_action: str) -> None:
    rows.append(_row(evidence, "Ready" if ready else "Missing", details if ready else missing_action, missing_action))


def _row(evidence: str, status: str, details: str, next_step: str) -> dict[str, str]:
    return {"Evidence": evidence, "Status": status, "Details": details, "Next step": next_step}


def _setup(component: str, live: bool, details: str) -> dict[str, str]:
    return {"Component": component, "Status": "Live" if live else "Demo / setup needed", "Details": details}


def _age_days(value: str) -> float:
    observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    return max(0, (datetime.now(timezone.utc) - observed).total_seconds() / 86400)
