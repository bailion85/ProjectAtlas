from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from core.services.alert_service import AlertService
from core.services.committee_service import PRESETS
from core.services.market_regime_service import analyze_market_environment


SCHEDULER_SERVICE_VERSION = 1
DEFAULT_SCHEDULE = {
    "enabled": False,
    "interval_hours": 24,
    "scope": "Watchlist and portfolio",
    "preset": "Balanced",
    "retry_limit": 1,
    "scan_alerts": True,
}
SCOPES = ("Watchlist", "Portfolio", "Watchlist and portfolio")


class ScheduledResearchService:
    def __init__(
        self, analysis, repository, market_provider, macro_provider, event_provider, calendar_provider,
        clock: Callable[[], datetime] | None = None,
    ):
        self.analysis = analysis
        self.repository = repository
        self.market_provider = market_provider
        self.macro_provider = macro_provider
        self.event_provider = event_provider
        self.calendar_provider = calendar_provider
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def configuration(self) -> dict[str, Any]:
        return {**DEFAULT_SCHEDULE, **(self.repository.configuration("scheduler") or {})}

    def save_configuration(self, configuration: dict[str, Any]) -> dict[str, Any]:
        validated = validate_schedule(configuration)
        self.repository.save_configuration("scheduler", validated)
        return validated

    def status(self) -> dict[str, Any]:
        configuration = self.configuration()
        runs = self.repository.scheduler_runs(1)
        last = runs[0] if runs else None
        now = self.clock()
        running = bool(last and last["status"] == "Running" and now - _time(last["started_at"]) < timedelta(minutes=30))
        completed = next((run for run in self.repository.scheduler_runs(25) if run["completed_at"]), None)
        next_run = None
        due = False
        if configuration["enabled"]:
            if completed:
                next_run_dt = _time(completed["completed_at"]) + timedelta(hours=configuration["interval_hours"])
            else:
                next_run_dt = now
            next_run = next_run_dt.isoformat()
            due = now >= next_run_dt and not running
        return {"configuration": configuration, "last_run": last, "next_run": next_run, "due": due, "running": running}

    def run(self, trigger: str = "Manual") -> dict[str, Any]:
        configuration = self.configuration()
        symbols = self._symbols(configuration["scope"])
        started = self.clock().isoformat()
        run_id = self.repository.start_scheduler_run(started, configuration["scope"], len(symbols))
        errors: list[str] = []
        analyzed = 0
        alerts_created = 0
        if not symbols:
            errors.append("No companies are available in the selected schedule scope.")
            self.repository.finish_scheduler_run(run_id, self.clock().isoformat(), "Skipped", 0, 0, errors)
            return self.repository.scheduler_runs(1)[0]
        try:
            macro = self.macro_provider.snapshot()
            environment = analyze_market_environment(self.event_provider.snapshot(), macro)
            calendar = self.calendar_provider.snapshot()
            benchmark = self.market_provider.history("SPY")
            benchmark_daily = self.market_provider.daily_history("SPY")
            for symbol in symbols:
                succeeded = False
                for attempt in range(configuration["retry_limit"] + 1):
                    try:
                        self.analysis.analyze(
                            symbol, PRESETS[configuration["preset"]], macro_snapshot=macro,
                            benchmark_history=benchmark, market_environment=environment,
                            calendar_snapshot=calendar, benchmark_daily_history=benchmark_daily,
                        )
                        analyzed += 1
                        succeeded = True
                        break
                    except Exception as exc:
                        if attempt == configuration["retry_limit"]:
                            errors.append(f"{symbol}: {exc}")
                if not succeeded:
                    continue
            if configuration["scan_alerts"]:
                alerts_created = AlertService(self.repository).scan(symbols)["created"]
        except Exception as exc:
            errors.append(f"{trigger} refresh setup failed: {exc}")
        status = "Complete" if not errors else "Partial" if analyzed else "Failed"
        self.repository.finish_scheduler_run(
            run_id, self.clock().isoformat(), status, analyzed, alerts_created, errors,
        )
        return self.repository.scheduler_runs(1)[0]

    def _symbols(self, scope: str) -> list[str]:
        watchlist = self.repository.watchlist() if scope in {"Watchlist", "Watchlist and portfolio"} else []
        portfolio = [item["ticker"] for item in self.repository.portfolio_positions()] if scope in {"Portfolio", "Watchlist and portfolio"} else []
        return list(dict.fromkeys(watchlist + portfolio))


def validate_schedule(configuration: dict[str, Any]) -> dict[str, Any]:
    result = {**DEFAULT_SCHEDULE, **configuration}
    if result["scope"] not in SCOPES:
        raise ValueError("Choose a valid scheduled-research scope.")
    if result["preset"] not in PRESETS:
        raise ValueError("Choose a valid committee preset.")
    interval = int(result["interval_hours"])
    retries = int(result["retry_limit"])
    if not 1 <= interval <= 168:
        raise ValueError("Refresh interval must be between 1 and 168 hours.")
    if not 0 <= retries <= 3:
        raise ValueError("Retry limit must be between 0 and 3.")
    return {
        "enabled": bool(result["enabled"]), "interval_hours": interval, "scope": result["scope"],
        "preset": result["preset"], "retry_limit": retries, "scan_alerts": bool(result["scan_alerts"]),
    }


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
