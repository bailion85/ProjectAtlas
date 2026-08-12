from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.models.research import ResearchReport
from core.services.report_repository import ReportRepository
from core.services.watchlist_service import rank_watchlist
from core.services.settings_service import load_configuration


ALERT_TYPES = {
    "crossover": "Golden/Death Cross",
    "committee": "Committee vote/confidence",
    "risk": "Risk threshold",
    "environment": "Market environment change",
    "catalyst": "Upcoming catalyst",
    "rank": "Watchlist rank change",
    "backtest": "Backtest threshold",
    "readiness": "Entry-readiness change",
    "stale": "Stale report",
    "financial_health": "SEC financial-health change",
    "evidence_trust": "Evidence trust/freshness",
    "discovery": "Opportunity discovery change",
}

DEFAULT_RULE = {
    "enabled": list(ALERT_TYPES),
    "risk_threshold": 65.0,
    "confidence_change": 10.0,
    "catalyst_days": 7,
    "rank_change": 2,
    "backtest_floor": 0.0,
    "stale_days": 7,
}


class AlertService:
    def __init__(self, repository: ReportRepository):
        self.repository = repository
        self.configuration = load_configuration(repository)
        configured = self.configuration["alert_defaults"]
        self.default_rule = {
            **DEFAULT_RULE, **configured,
            "catalyst_days": self.configuration["catalyst_warning_days"],
            "stale_days": configured.get("stale_days", self.configuration["freshness_days"]),
        }

    def rule(self, ticker: str) -> dict[str, Any]:
        saved = self.repository.alert_rule(ticker) or {}
        return {**self.default_rule, **saved}

    def save_rule(self, ticker: str, rule: dict[str, Any]) -> None:
        enabled = [name for name in rule.get("enabled", []) if name in ALERT_TYPES]
        self.repository.save_alert_rule(ticker, {**self.default_rule, **rule, "enabled": enabled})

    def scan(self, tickers: list[str]) -> dict[str, Any]:
        symbols = list(dict.fromkeys(ticker.strip().upper() for ticker in tickers if ticker.strip()))
        histories = {ticker: self.repository.recent_reports(ticker, 2) for ticker in symbols}
        latest = {ticker: reports[0] for ticker, reports in histories.items() if reports}
        previous = {ticker: reports[1] for ticker, reports in histories.items() if len(reports) > 1}
        current_ranks = _ranks(symbols, latest, self.configuration)
        previous_ranks = _ranks(symbols, previous, self.configuration)
        created = 0
        evaluated = 0
        missing = []
        for ticker in symbols:
            current = latest.get(ticker)
            if current is None:
                missing.append(ticker)
                continue
            evaluated += 1
            rule = self.rule(ticker)
            candidates = self._candidates(
                current, previous.get(ticker), rule, current_ranks.get(ticker), previous_ranks.get(ticker)
            )
            for alert in candidates:
                created += int(self.repository.add_alert(alert))
        return {"evaluated": evaluated, "created": created, "missing": missing}

    def simulate_demo_alert(self, ticker: str) -> bool:
        symbol = ticker.strip().upper()
        anchor = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M")
        return self.repository.add_alert(_alert(
            symbol, "demo", "Moderate", "Demo alert: market condition changed",
            "This illustrative alert demonstrates how Atlas will display a newly detected condition.",
            f"demo:{symbol}:{anchor}", {"demo": True},
        ))

    def _candidates(
        self, current: ResearchReport, previous: ResearchReport | None, rule: dict[str, Any],
        current_rank: int | None, previous_rank: int | None,
    ) -> list[dict[str, Any]]:
        enabled = set(rule["enabled"])
        ticker = current.ticker
        report_anchor = current.report_id or current.created_at
        alerts = []
        cross = current.technical.get("latest_cross") or {}
        previous_cross = previous.technical.get("latest_cross") if previous else None
        if "crossover" in enabled and cross and cross != previous_cross:
            severity = "High" if cross.get("type") == "death_cross" else "Moderate"
            alerts.append(_alert(ticker, "crossover", severity, f"{ticker}: {cross.get('label')} detected",
                                 f"The latest crossover is dated {cross.get('date')}.",
                                 f"cross:{ticker}:{cross.get('type')}:{cross.get('date')}", cross))

        if "committee" in enabled and previous:
            if current.committee_vote != previous.committee_vote:
                alerts.append(_alert(ticker, "committee", "High", f"{ticker}: committee vote changed",
                                     f"Vote changed from {previous.committee_vote.title()} to {current.committee_vote.title()}.",
                                     f"vote:{ticker}:{report_anchor}:{current.committee_vote}"))
            confidence_change = current.committee_confidence - previous.committee_confidence
            if abs(confidence_change) >= float(rule["confidence_change"]):
                alerts.append(_alert(ticker, "committee", "Moderate", f"{ticker}: confidence moved materially",
                                     f"Committee confidence changed by {confidence_change:+.0f} points to {current.committee_confidence}%.",
                                     f"confidence:{ticker}:{report_anchor}:{current.committee_confidence}"))

        risk_score = float(current.risk.get("score", 0))
        previous_risk = float(previous.risk.get("score", 0)) if previous else 0
        threshold = float(rule["risk_threshold"])
        if "risk" in enabled and risk_score >= threshold and previous_risk < threshold:
            alerts.append(_alert(ticker, "risk", "High", f"{ticker}: risk threshold reached",
                                 f"Risk is {risk_score:.1f}/100, above the configured {threshold:.1f} threshold.",
                                 f"risk:{ticker}:{report_anchor}:{threshold}"))

        environment = current.market_environment.get("label")
        previous_environment = previous.market_environment.get("label") if previous else None
        if "environment" in enabled and previous and environment != previous_environment:
            severity = "High" if environment in {"Defensive", "Highly defensive"} else "Moderate"
            alerts.append(_alert(ticker, "environment", severity, f"{ticker}: market environment changed",
                                 f"Environment changed from {previous_environment} to {environment}.",
                                 f"environment:{ticker}:{report_anchor}:{environment}"))

        readiness = current.entry_readiness.get("posture")
        previous_readiness = previous.entry_readiness.get("posture") if previous else None
        if "readiness" in enabled and previous and readiness != previous_readiness:
            severity = "High" if readiness in {"Elevated risk", "Insufficient evidence"} else "Moderate"
            alerts.append(_alert(ticker, "readiness", severity, f"{ticker}: entry posture changed",
                                 f"Entry readiness changed from {previous_readiness} to {readiness}.",
                                 f"readiness:{ticker}:{report_anchor}:{readiness}"))

        next_event = current.catalyst_calendar.get("next_event") or {}
        if ("catalyst" in enabled and next_event and current.catalyst_calendar.get("live") is True and
                not current.catalyst_calendar.get("stale") and next_event.get("source_live") is True and
                not next_event.get("source_stale") and
                int(next_event.get("days_until", 999)) <= int(rule["catalyst_days"]) and
                current.catalyst_calendar.get("readiness") in {"Elevated", "Event imminent"}):
            severity = "Critical" if current.catalyst_calendar.get("readiness") == "Event imminent" else "High"
            alerts.append(_alert(ticker, "catalyst", severity, f"{ticker}: catalyst approaching",
                                 f"{next_event.get('title')} is in {next_event.get('days_until')} days.",
                                 f"catalyst:{ticker}:{next_event.get('title')}:{next_event.get('date')}", next_event))

        if ("rank" in enabled and current_rank is not None and previous_rank is not None and
                abs(current_rank - previous_rank) >= int(rule["rank_change"])):
            alerts.append(_alert(ticker, "rank", "Moderate", f"{ticker}: watchlist rank changed",
                                 f"Rank moved from #{previous_rank} to #{current_rank}.",
                                 f"rank:{ticker}:{report_anchor}:{current_rank}"))

        backtest_return = current.backtest.get("total_return")
        if "backtest" in enabled and backtest_return is not None and float(backtest_return) < float(rule["backtest_floor"]):
            alerts.append(_alert(ticker, "backtest", "Moderate", f"{ticker}: backtest below threshold",
                                 f"Backtest return is {float(backtest_return):+.2f}%, below {float(rule['backtest_floor']):+.2f}%.",
                                 f"backtest:{ticker}:{report_anchor}:{rule['backtest_floor']}"))

        created = datetime.fromisoformat(current.created_at.replace("Z", "+00:00"))
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - created).total_seconds() / 86400
        if "stale" in enabled and age_days > int(rule["stale_days"]):
            alerts.append(_alert(ticker, "stale", "Moderate", f"{ticker}: report is stale",
                                 f"The latest report is {age_days:.0f} days old.",
                                 f"stale:{ticker}:{report_anchor}:{rule['stale_days']}"))
        return alerts


def _ranks(tickers: list[str], reports: dict[str, ResearchReport], configuration: dict[str, Any]) -> dict[str, int]:
    if not reports:
        return {}
    ranking = rank_watchlist(
        tickers, reports, weights=configuration["ranking_weights"], freshness_days=configuration["freshness_days"]
    )
    return {row["Ticker"]: row["Rank"] for row in ranking["rows"]}


def _alert(ticker: str, alert_type: str, severity: str, title: str, message: str,
           fingerprint: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "ticker": ticker, "alert_type": alert_type, "severity": severity, "title": title,
        "message": message, "fingerprint": fingerprint, "payload": payload or {},
    }
