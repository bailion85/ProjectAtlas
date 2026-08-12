from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


PROVIDER_HEALTH_SERVICE_VERSION = 1


def build_provider_health(
    environment: dict[str, Any], market_status: dict[str, Any], macro_status: dict[str, Any],
    calendar_name: str, market_readiness: dict[str, Any] | None,
    macro_readiness: dict[str, Any] | None, discovery_schedule: dict[str, Any],
    sec_configured: bool, cache_entries: int, now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    rows = [
        _market_row(environment, market_status, market_readiness),
        _component(
            "FRED macro data", "Ready" if environment.get("fred_key") and macro_readiness and
            macro_readiness.get("status") == "Ready" else
            "Degraded" if environment.get("fred_key") else "Action required",
            macro_status.get("last_source", "No requests yet"), macro_status.get("last_age_seconds"),
            "Live macro mode is configured." if environment.get("fred_key") else "FRED_API_KEY is missing.",
            "Run the saved FRED readiness test." if environment.get("fred_key") else "Add FRED_API_KEY to .env.",
        ),
        _component(
            "SEC EDGAR", "Ready" if sec_configured else "Action required", "24-hour filing cache", None,
            "SEC contact identity is configured." if sec_configured else "SEC_USER_AGENT is missing or invalid.",
            "No action needed." if sec_configured else "Set SEC_USER_AGENT to an application name and contact email.",
        ),
        _component(
            "Catalyst calendars", "Ready" if "Demo" not in calendar_name else "Degraded",
            calendar_name, None,
            "Official economic and earnings calendar is configured." if "Demo" not in calendar_name else
            "The calendar is using illustrative demo events.",
            "No action needed." if "Demo" not in calendar_name else "Configure the FRED calendar provider.",
        ),
        _scheduler_row(discovery_schedule),
    ]
    action_rows = [row for row in rows if row["Status"] == "Action required"]
    degraded_rows = [row for row in rows if row["Status"] == "Degraded"]
    overall = "Action required" if action_rows else "Degraded" if degraded_rows else "Ready"
    quota_remaining = market_status.get("quota_remaining")
    reset = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    failures = _recent_failures(market_readiness, macro_readiness, discovery_schedule)
    return {
        "overall": overall, "rows": rows, "action_required": len(action_rows),
        "degraded": len(degraded_rows), "ready": sum(row["Status"] == "Ready" for row in rows),
        "cache_entries": int(cache_entries), "quota_remaining": quota_remaining,
        "quota_used": market_status.get("quota_used"),
        "quota_limit": market_status.get("quota_usable_limit") or market_status.get("quota_daily_limit"),
        "quota_reset": reset.isoformat() if quota_remaining is not None else None,
        "failures": failures, "generated_at": now.isoformat(),
        "summary": _summary(overall, action_rows, degraded_rows),
    }


def _market_row(environment, status, readiness):
    mode = str(environment.get("market_mode", "demo"))
    has_alpha = bool(environment.get("alpha_vantage_key"))
    has_tiingo = bool(environment.get("tiingo_key"))
    remaining = status.get("quota_remaining")
    fallback = int(status.get("demo_fallbacks", 0) or 0)
    if mode == "demo":
        state, detail, action = "Degraded", "Market data is in demo mode.", "Configure hybrid live mode."
    elif mode == "hybrid" and not (has_alpha and has_tiingo):
        state, detail, action = "Action required", "Hybrid mode is missing a required API key.", "Add the missing Alpha Vantage or Tiingo key."
    elif remaining == 0 or fallback:
        state, detail, action = "Degraded", "Live prices remain available, but Alpha fundamentals are capped or a demo fallback occurred.", "Use Tiingo + SEC evidence or wait for the UTC quota reset."
    elif readiness and readiness.get("status") == "Blocked":
        state, detail, action = "Degraded", "The last market readiness test was blocked.", "Review its failed checks below."
    else:
        state, detail, action = "Ready", "Hybrid market data is configured and no current blocker is recorded.", "No action needed."
    return _component("Market data", state, status.get("last_source", "No requests yet"),
                      status.get("last_age_seconds"), detail, action)


def _scheduler_row(schedule):
    config = schedule.get("configuration", {})
    last = schedule.get("last_run") or {}
    enabled = bool(config.get("enabled"))
    failed = last.get("status") in {"Failed", "Partial"}
    state = "Degraded" if not enabled or failed else "Ready"
    detail = (f"Enabled; next due {schedule.get('next_run')}." if enabled else "Daily Discovery monitoring is paused.")
    if failed:
        detail = f"The last Discovery job ended {last.get('status', '').lower()}."
    return _component("Discovery scheduler", state, last.get("status", "Never run"), None,
                      detail, "Review the job errors." if failed else
                      "Enable it in Settings." if not enabled else "No action needed.")


def _component(name, status, source, age, detail, action):
    return {"Component": name, "Status": status, "Last source": source,
            "Cache age": None if age is None else round(float(age)),
            "Details": detail, "Recommended action": action}


def _recent_failures(market, macro, schedule):
    failures = []
    for provider, result in (("Market", market), ("FRED", macro)):
        for check in (result or {}).get("checks", []):
            if check.get("status") in {"Failed", "Blocked"}:
                failures.append({"Provider": provider, "Issue": check.get("check"),
                                 "Details": check.get("details"), "Observed": result.get("tested_at")})
    last = schedule.get("last_run") or {}
    for error in last.get("errors", []):
        failures.append({"Provider": "Discovery scheduler", "Issue": last.get("status"),
                         "Details": error, "Observed": last.get("completed_at") or last.get("started_at")})
    return failures[:20]


def _summary(overall, action_rows, degraded_rows):
    if overall == "Ready":
        return "All configured Atlas data systems are ready, with no recorded blockers."
    names = [row["Component"] for row in action_rows + degraded_rows]
    return f"Atlas is {overall.lower()}. Review: {', '.join(names)}."
