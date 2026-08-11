from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Any


class EconomicEventProvider(ABC):
    name: str

    @abstractmethod
    def snapshot(self) -> dict[str, Any]: ...


class DemoEconomicEventProvider(EconomicEventProvider):
    """Illustrative events for developing Atlas without a live-news dependency."""

    name = "Demo economic event feed (not live)"

    def snapshot(self) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        events = [
            _event("Geopolitical tensions raise energy-supply uncertainty", "Geopolitics", -72, 84, 2,
                   "Weeks to months", ["Energy", "Industrials", "Consumer Cyclical"],
                   "Escalation can lift energy costs and weaken risk appetite.",
                   "Contained disruptions or diplomatic progress could reduce the impact."),
            _event("Inflation continues to moderate gradually", "Inflation", 38, 76, 5,
                   "Several months", ["Technology", "Consumer Cyclical", "Real Estate"],
                   "Cooling inflation can improve the outlook for interest-sensitive assets.",
                   "Sticky services inflation could delay policy relief."),
            _event("Economic growth remains positive but uneven", "Growth", 22, 68, 9,
                   "One to two quarters", ["Technology", "Industrials", "Financials"],
                   "Positive growth supports earnings and reduces immediate recession risk.",
                   "Uneven demand leaves cyclical businesses vulnerable."),
            _event("Interest rates remain restrictive", "Monetary policy", -44, 82, 13,
                   "Several months", ["Technology", "Real Estate", "Consumer Cyclical"],
                   "Higher financing costs pressure valuations and credit-sensitive demand.",
                   "Strong earnings or future rate cuts could offset the pressure."),
        ]
        for event, age in events:
            event["published_at"] = (now - timedelta(days=age)).isoformat()
        return {"provider": self.name, "retrieved_at": now.isoformat(), "events": [event for event, _ in events]}


def _event(title: str, category: str, direction: int, confidence: int, age_days: int,
           duration: str, sectors: list[str], support: str, counterpoint: str) -> tuple[dict[str, Any], int]:
    return ({
        "title": title,
        "category": category,
        "direction": direction,
        "confidence": confidence,
        "duration": duration,
        "affected_sectors": sectors,
        "supporting_evidence": support,
        "counterpoint": counterpoint,
        "source": "Illustrative Atlas scenario",
    }, age_days)
