from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime, timedelta, timezone
from typing import Any


class CatalystCalendarProvider(ABC):
    name: str

    @abstractmethod
    def snapshot(self) -> dict[str, Any]: ...


class DemoCatalystCalendarProvider(CatalystCalendarProvider):
    name = "Demo catalyst calendar (not live)"

    def snapshot(self) -> dict[str, Any]:
        today = date.today()
        events = [
            _event("U.S. employment report", "Jobs", today + timedelta(days=3), 85, 82, "global", [],
                   "Labor-market data can change growth and interest-rate expectations."),
            _event("U.S. consumer price index", "Inflation", today + timedelta(days=6), 92, 88, "global", [],
                   "Inflation surprises can move interest rates and equity valuations."),
            _event("Geopolitical policy update", "Geopolitics", today + timedelta(days=10), 78, 64, "global", ["Energy", "Industrials"],
                   "Policy changes may affect energy prices, trade, and risk appetite."),
            _event("Federal Reserve policy decision", "Federal Reserve", today + timedelta(days=14), 96, 90, "global", [],
                   "Rate guidance can materially affect financing conditions and valuations."),
            _event("U.S. GDP release", "Growth", today + timedelta(days=24), 76, 80, "global", [],
                   "Growth data can alter recession expectations and earnings forecasts."),
        ]
        earnings_offsets = {"AAPL": 12, "MSFT": 5, "NVDA": 2, "GOOGL": 9, "AMZN": 16}
        dividend_offsets = {"AAPL": 28, "MSFT": 21, "NVDA": 25, "GOOGL": 32, "AMZN": 35}
        for ticker, offset in earnings_offsets.items():
            events.append(_event(f"{ticker} quarterly earnings", "Earnings", today + timedelta(days=offset), 94, 72,
                                 "company", [ticker], "Earnings can reset revenue, margin, and guidance expectations."))
        for ticker, offset in dividend_offsets.items():
            events.append(_event(f"{ticker} expected dividend date", "Dividend", today + timedelta(days=offset), 35, 60,
                                 "company", [ticker], "Dividend timing may affect short-term cash-flow expectations."))
        return {"provider": self.name, "retrieved_at": datetime.now(timezone.utc).isoformat(), "events": events}


def _event(title: str, category: str, event_date: date, importance: int, confidence: int,
           scope: str, affected: list[str], rationale: str) -> dict[str, Any]:
    return {
        "title": title, "category": category, "date": event_date.isoformat(),
        "importance": importance, "confidence": confidence, "scope": scope,
        "affected": affected, "rationale": rationale, "source": "Illustrative Atlas schedule",
    }
