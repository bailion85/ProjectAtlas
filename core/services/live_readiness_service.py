from __future__ import annotations

import os
from datetime import date, datetime, timezone
from time import perf_counter
from typing import Any, Callable


LIVE_READINESS_SERVICE_VERSION = 1
SNAPSHOT_FIELDS = (
    "symbol", "name", "price", "sector", "industry", "pe_ratio", "forward_pe", "profit_margin",
    "operating_margin", "return_on_equity", "revenue_growth", "earnings_growth", "beta",
    "fifty_two_week_high", "fifty_two_week_low", "observed_at", "source",
)


def environment_readiness() -> dict[str, Any]:
    return {
        "market_mode": os.getenv("ATLAS_DATA_PROVIDER", "demo").lower(),
        "macro_mode": os.getenv("ATLAS_MACRO_PROVIDER", "demo").lower(),
        "alpha_vantage_key": bool(os.getenv("ALPHA_VANTAGE_API_KEY")),
        "fred_key": bool(os.getenv("FRED_API_KEY")),
    }


def test_market_provider(provider, ticker: str, required_daily_points: int = 200) -> dict[str, Any]:
    symbol = ticker.strip().upper()
    if not symbol:
        raise ValueError("Enter a ticker for the market-data test.")
    checks = []
    search = _check("Symbol search", lambda: provider.search(symbol))
    if search["status"] == "Pass" and not search["value"]:
        search.update(status="Warning", details="The provider returned no symbol matches.")
    elif search["status"] == "Pass":
        search["details"] = f"Returned {len(search['value'])} match(es)."
    checks.append(search)

    snapshot = _check("Quote and fundamentals", lambda: provider.snapshot(symbol))
    coverage = 0.0
    missing_fields = []
    if snapshot["status"] == "Pass":
        missing_fields = [field for field in SNAPSHOT_FIELDS if snapshot["value"].get(field) in (None, "")]
        coverage = round((len(SNAPSHOT_FIELDS) - len(missing_fields)) / len(SNAPSHOT_FIELDS) * 100, 1)
        snapshot["status"] = "Pass" if coverage >= 80 else "Warning"
        observed_at = snapshot["value"].get("observed_at", "Unavailable")
        snapshot["details"] = (
            f"{coverage:.1f}% field coverage. Data as of {observed_at}. "
            f"Missing: {', '.join(missing_fields) if missing_fields else 'none'}."
        )
    checks.append(snapshot)

    news = _check("Company news", lambda: provider.news(symbol))
    if news["status"] == "Pass":
        news["status"] = "Pass" if news["value"] else "Warning"
        news["details"] = f"Returned {len(news['value'])} article(s)."
    checks.append(news)

    monthly = _check("Monthly performance history", lambda: provider.history(symbol))
    if monthly["status"] == "Pass":
        observations = len(monthly["value"])
        monthly["status"] = "Pass" if observations >= 61 else "Warning"
        latest = monthly["value"][-1].get("date", "Unavailable") if monthly["value"] else "Unavailable"
        monthly["details"] = f"Returned {observations} monthly observation(s); Atlas targets 61. Latest: {latest}."
    checks.append(monthly)

    daily = _check("Daily technical history", lambda: provider.daily_history(symbol))
    daily_points = 0
    if daily["status"] == "Pass":
        daily_points = len(daily["value"])
        daily["status"] = "Pass" if daily_points >= required_daily_points else "Blocked"
        daily["details"] = (
            f"Returned {daily_points} daily observation(s); Atlas requires {required_daily_points}. "
            "Alpha Vantage compact history supplies 100 observations; full history requires premium access."
            if daily_points < required_daily_points else
            f"Returned {daily_points} daily observation(s), enough for the configured long moving average. "
            f"Latest: {daily['value'][-1].get('date', 'Unavailable')}."
        )
    checks.append(daily)
    public_checks = [{key: value for key, value in check.items() if key != "value"} for check in checks]
    overall = _overall(public_checks)
    return {
        "provider": provider.name, "ticker": symbol, "tested_at": datetime.now(timezone.utc).isoformat(),
        "status": overall, "checks": public_checks, "snapshot_coverage": coverage,
        "missing_snapshot_fields": missing_fields, "daily_observations": daily_points,
        "required_daily_observations": required_daily_points,
        "provider_status": provider.status() if hasattr(provider, "status") else {},
    }


def test_macro_provider(provider) -> dict[str, Any]:
    check = _check("Economic snapshot", provider.snapshot)
    stale = 0
    coverage = 0.0
    if check["status"] == "Pass":
        indicators = check["value"].get("indicators", {})
        stale = sum(bool(item.get("stale")) for item in indicators.values())
        coverage = round(len(indicators) / 5 * 100, 1)
        check["status"] = "Pass" if len(indicators) >= 5 and stale == 0 else "Warning"
        check["details"] = f"Returned {len(indicators)}/5 expected indicators; {stale} marked stale."
    public_check = {key: value for key, value in check.items() if key != "value"}
    return {
        "provider": provider.name, "tested_at": datetime.now(timezone.utc).isoformat(),
        "status": _overall([public_check]), "checks": [public_check], "indicator_coverage": coverage,
        "stale_indicators": stale, "provider_status": provider.status() if hasattr(provider, "status") else {},
    }


def readiness_summary(environment: dict[str, Any], market: dict[str, Any] | None, macro: dict[str, Any] | None) -> dict[str, Any]:
    market_ready = bool(environment["alpha_vantage_key"] and market and market["status"] in {"Ready", "Limited"})
    macro_ready = bool(environment["fred_key"] and macro and macro["status"] in {"Ready", "Limited"})
    blockers = []
    if not environment["alpha_vantage_key"]:
        blockers.append("Alpha Vantage API key is missing.")
    if market and market["status"] != "Ready":
        blockers.extend(check["details"] for check in market["checks"] if check["status"] in {"Failed", "Blocked"})
    if not environment["fred_key"]:
        blockers.append("FRED API key is missing.")
    if macro and macro["status"] != "Ready":
        blockers.extend(check["details"] for check in macro["checks"] if check["status"] in {"Failed", "Blocked"})
    return {
        "market_ready": market_ready, "macro_ready": macro_ready,
        "overall": "Ready for live mode" if market_ready and macro_ready else "Not ready for full live mode",
        "blockers": list(dict.fromkeys(blockers)),
    }


def _check(name: str, action: Callable[[], Any]) -> dict[str, Any]:
    started = perf_counter()
    try:
        value = action()
        return {"check": name, "status": "Pass", "details": "Request completed.", "duration_ms": round((perf_counter() - started) * 1000), "value": value}
    except Exception as exc:
        return {"check": name, "status": "Failed", "details": str(exc), "duration_ms": round((perf_counter() - started) * 1000), "value": None}


def _overall(checks: list[dict[str, Any]]) -> str:
    statuses = {check["status"] for check in checks}
    if "Failed" in statuses or "Blocked" in statuses:
        return "Blocked"
    if "Warning" in statuses:
        return "Limited"
    return "Ready"
