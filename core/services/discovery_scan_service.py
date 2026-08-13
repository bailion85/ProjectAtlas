from __future__ import annotations

import os
from typing import Any

from core.providers.market_provider import ProviderError
from core.providers.sec_provider import SecCompanyFactsProvider
from core.services.discovery_monitor_service import compare_discovery_runs, discovery_alerts
from core.services.financial_health_service import analyze_financial_health
from core.services.opportunity_discovery_service import (
    build_discovery_result, score_candidate, score_market_feed_candidate, select_market_candidates,
)


class DiscoveryScanService:
    def __init__(self, provider, repository, provider_cache):
        self.provider = provider
        self.repository = repository
        self.provider_cache = provider_cache

    def run(self, limit: int = 5) -> dict[str, Any]:
        radar = set(self.repository.watchlist()) | {
            item["ticker"] for item in self.repository.portfolio_positions()
        }
        market_pulse = self.provider.market_movers()
        candidates = select_market_candidates(market_pulse, radar, int(limit))
        if not candidates:
            source = market_pulse.get("provider", self.provider.name)
            if "demo" in str(source).lower():
                raise ValueError(
                    "Live market discovery was unavailable and every company in the demo feed is already on your radar."
                )
            raise ValueError(f"{source} returned no liquid companies outside your watchlist and portfolio.")
        rows, failures = [], []
        for source in candidates:
            symbol = source["ticker"]
            try:
                snapshot = self.provider.snapshot(symbol)
                sec_health, sec_note = self._sec_health(symbol, snapshot)
                row = score_candidate(
                    snapshot, self.provider.daily_history(symbol), self.provider.name,
                    financial_health=sec_health,
                )
                if sec_note:
                    row["SEC note"] = sec_note
                row.update({
                    "Market signal": source.get("group"),
                    "Market change": source.get("change_percentage"),
                    "Market volume": source.get("volume"),
                    "Market feed as of": market_pulse.get("last_updated"),
                })
                rows.append(row)
            except (ProviderError, RuntimeError, TypeError, ValueError) as exc:
                try:
                    row = score_market_feed_candidate(
                        source, market_pulse.get("provider", self.provider.name), str(exc),
                    )
                    row.update({
                        "Market signal": source.get("group"),
                        "Market change": source.get("change_percentage"),
                        "Market volume": source.get("volume"),
                        "Market feed as of": market_pulse.get("last_updated"),
                        "Observed": market_pulse.get("last_updated"),
                    })
                    rows.append(row)
                except (TypeError, ValueError) as fallback_exc:
                    failures.append({"Ticker": symbol, "Error": str(fallback_exc)})
        previous = self.repository.latest_discovery_run()
        result = build_discovery_result(rows, failures, radar)
        result["market_source"] = market_pulse.get("provider", self.provider.name)
        result["market_as_of"] = market_pulse.get("last_updated")
        result["monitor"] = compare_discovery_runs(previous, result)
        run_id = self.repository.save_discovery_run(result)
        result["id"] = run_id
        alerts_created = 0
        for alert in discovery_alerts(result["monitor"], run_id):
            alerts_created += int(self.repository.add_alert(alert))
        result["alerts_created"] = alerts_created
        return result

    def _sec_health(self, symbol: str, snapshot: dict[str, Any]):
        if snapshot.get("fundamentals_status", "Available") == "Available" or not os.getenv("SEC_USER_AGENT"):
            return None, None
        try:
            return analyze_financial_health(
                SecCompanyFactsProvider(self.provider_cache).company_facts(symbol)
            ), None
        except (ProviderError, RuntimeError, TypeError, ValueError) as exc:
            return None, str(exc)
