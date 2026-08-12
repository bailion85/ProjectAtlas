from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo


DISCOVERY_SCHEDULER_SERVICE_VERSION = 1
EASTERN = ZoneInfo("America/New_York")
DEFAULT_DISCOVERY_SCHEDULE = {
    "enabled": False, "hour_et": 18, "minute_et": 15,
    "weekdays_only": True, "candidate_limit": 5,
}


class ScheduledDiscoveryService:
    def __init__(self, scanner, repository, clock: Callable[[], datetime] | None = None):
        if not callable(getattr(repository, "discovery_scheduler_runs", None)):
            # Streamlit may retain a resource created from an older repository class
            # across an app-only hot reload. Recreate only that lightweight handle.
            from core.services.report_repository import ReportRepository
            repository = ReportRepository(repository.path)
        self.scanner = scanner
        self.repository = repository
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def configuration(self) -> dict[str, Any]:
        return {**DEFAULT_DISCOVERY_SCHEDULE,
                **(self.repository.configuration("discovery_scheduler") or {})}

    def save_configuration(self, configuration: dict[str, Any]) -> dict[str, Any]:
        validated = validate_discovery_schedule(configuration)
        self.repository.save_configuration("discovery_scheduler", validated)
        return validated

    def status(self) -> dict[str, Any]:
        configuration = self.configuration()
        runs = self.repository.discovery_scheduler_runs(25)
        last = runs[0] if runs else None
        now = self.clock()
        running = bool(last and last["status"] == "Running" and
                       now - _time(last["started_at"]) < timedelta(minutes=30))
        completed = next((run for run in runs if run["completed_at"]), None)
        next_run = None
        if configuration["enabled"]:
            next_run = (_next_after(_time(completed["completed_at"]), configuration)
                        if completed else _today_schedule(now, configuration))
        due = bool(next_run and now >= next_run and not running)
        return {"configuration": configuration, "last_run": last,
                "next_run": next_run.isoformat() if next_run else None,
                "due": due, "running": running}

    def run(self, trigger: str = "Manual", force: bool = False) -> dict[str, Any]:
        state = self.status()
        if not force and (not state["configuration"]["enabled"] or not state["due"]):
            return {"status": "Not due", "trigger": trigger, "candidates": 0,
                    "alerts_created": 0, "errors": []}
        now = self.clock()
        run_id = self.repository.start_discovery_scheduler_run(now.isoformat(), trigger)
        errors = []
        candidates = alerts_created = 0
        try:
            result = self.scanner.run(state["configuration"]["candidate_limit"])
            candidates = len(result.get("rows", []))
            alerts_created = int(result.get("alerts_created", 0))
            errors = [f"{item['Ticker']}: {item['Error']}" for item in result.get("failures", [])]
        except Exception as exc:
            errors.append(str(exc))
        status = "Complete" if not errors else "Partial" if candidates else "Failed"
        self.repository.finish_discovery_scheduler_run(
            run_id, self.clock().isoformat(), status, candidates, alerts_created, errors,
        )
        return self.repository.discovery_scheduler_runs(1)[0]


def validate_discovery_schedule(configuration: dict[str, Any]) -> dict[str, Any]:
    result = {**DEFAULT_DISCOVERY_SCHEDULE, **configuration}
    hour, minute, limit = int(result["hour_et"]), int(result["minute_et"]), int(result["candidate_limit"])
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("Choose a valid Eastern Time discovery schedule.")
    if not 1 <= limit <= 8:
        raise ValueError("Discovery candidate limit must be between 1 and 8.")
    return {"enabled": bool(result["enabled"]), "hour_et": hour, "minute_et": minute,
            "weekdays_only": bool(result["weekdays_only"]), "candidate_limit": limit}


def _today_schedule(now: datetime, configuration: dict[str, Any]) -> datetime:
    local_now = now.astimezone(EASTERN)
    candidate = local_now.replace(hour=configuration["hour_et"], minute=configuration["minute_et"],
                                  second=0, microsecond=0)
    while configuration["weekdays_only"] and candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate.astimezone(timezone.utc)


def _next_after(completed: datetime, configuration: dict[str, Any]) -> datetime:
    local = completed.astimezone(EASTERN)
    candidate = local.replace(hour=configuration["hour_et"], minute=configuration["minute_et"],
                              second=0, microsecond=0)
    if candidate <= local:
        candidate += timedelta(days=1)
    while configuration["weekdays_only"] and candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate.astimezone(timezone.utc)


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
