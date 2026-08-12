from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.providers.market_provider import ProviderError
from core.services.financial_health_service import analyze_financial_health
from core.services.report_repository import ReportRepository


SEC_MONITOR_SERVICE_VERSION = 1


class SecMonitorService:
    def __init__(self, provider, repository: ReportRepository):
        self.provider = provider
        self.repository = repository

    def refresh(self, tickers: list[str]) -> dict[str, Any]:
        symbols = list(dict.fromkeys(ticker.strip().upper() for ticker in tickers if ticker.strip()))
        rows = []
        created = alerts = unchanged = failed = 0
        for ticker in symbols:
            previous = self.repository.financial_health_history(ticker, 1)
            previous_result = previous[0] if previous else None
            try:
                result = analyze_financial_health(self.provider.company_facts(ticker))
                new_filing = _filing_id(result) != _filing_id(previous_result)
                score_change = None if previous_result is None else result["score"] - previous_result["score"]
                version_id = None
                if new_filing or previous_result is None:
                    version_id = self.repository.save_financial_health(result)
                    created += 1
                    alerts += self._create_alerts(result, previous_result, score_change)
                else:
                    unchanged += 1
                row = _status_row(ticker, result, "New filing" if new_filing else "Current", score_change, version_id)
                self.repository.save_sec_monitor_check(row)
                rows.append(row)
            except (ProviderError, ValueError) as exc:
                failed += 1
                row = {
                    "Ticker": ticker, "Status": "Failed", "Form": None, "Filed": None,
                    "Score": None, "Score change": None, "Posture": None, "Version": None,
                    "Message": str(exc), "Checked": datetime.now(timezone.utc).isoformat(),
                }
                self.repository.save_sec_monitor_check(row)
                rows.append(row)
        return {
            "requested": len(symbols), "saved": created, "unchanged": unchanged,
            "alerts_created": alerts, "failed": failed, "rows": rows,
        }

    def _create_alerts(
        self, current: dict[str, Any], previous: dict[str, Any] | None, score_change: float | None,
    ) -> int:
        if previous is None or score_change is None or abs(score_change) < 10:
            return 0
        ticker = current["ticker"]
        filing = current.get("latest_filing") or {}
        direction = "deteriorated" if score_change < 0 else "improved"
        severity = "High" if score_change <= -20 or current["score"] <= 35 else "Moderate"
        alert = {
            "ticker": ticker, "alert_type": "financial_health", "severity": severity,
            "title": f"{ticker}: SEC financial health {direction}",
            "message": (
                f"The saved SEC score changed {score_change:+.0f} points to {current['score']}/100 "
                f"after the {filing.get('form', 'latest filing')}."
            ),
            "fingerprint": f"sec-health:{ticker}:{filing.get('accession', current['retrieved_at'])}:{current['score']}",
            "payload": {"score": current["score"], "score_change": score_change, "filing": filing},
        }
        return int(self.repository.add_alert(alert))


def _filing_id(result: dict[str, Any] | None) -> str | None:
    return str((result or {}).get("latest_filing", {}).get("accession") or "") or None


def _status_row(
    ticker: str, result: dict[str, Any], status: str, score_change: float | None, version_id: int | None,
) -> dict[str, Any]:
    filing = result.get("latest_filing") or {}
    return {
        "Ticker": ticker, "Status": status, "Form": filing.get("form"), "Filed": filing.get("filed"),
        "Score": result.get("score"), "Score change": score_change, "Posture": result.get("posture"),
        "Version": version_id, "Message": result.get("summary"),
        "Checked": datetime.now(timezone.utc).isoformat(),
    }
