from __future__ import annotations

from abc import ABC, abstractmethod
import csv
import io
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from core.providers.market_provider import ProviderError


CALENDAR_PROVIDER_VERSION = 3
FRED_RELEASE_DATES_URL = "https://api.stlouisfed.org/fred/release/dates"
FRED_CALENDAR_URL = "https://fred.stlouisfed.org/releases/calendar"

_RELEASE_IDS = {
    50: "Employment Situation",
    10: "Consumer Price Index",
    46: "Producer Price Index",
    53: "Gross Domestic Product",
    54: "Personal Income and Outlays",
    9: "Advance Monthly Sales for Retail and Food Services",
}

_RELEASE_RULES = {
    "Employment Situation": ("U.S. employment report", "Jobs", 92,
                               "Labor-market data can change growth and interest-rate expectations.",
                               "https://www.bls.gov/schedule/news_release/empsit.htm"),
    "Consumer Price Index": ("U.S. consumer price index", "Inflation", 96,
                              "Inflation surprises can move interest rates and equity valuations.",
                              "https://www.bls.gov/schedule/news_release/cpi.htm"),
    "Producer Price Index": ("U.S. producer price index", "Inflation", 82,
                              "Producer-price changes can signal future inflation pressure.",
                              "https://www.bls.gov/schedule/news_release/ppi.htm"),
    "Gross Domestic Product": ("U.S. GDP release", "Growth", 88,
                                "Growth data can alter recession expectations and earnings forecasts.",
                                "https://www.bea.gov/news/schedule"),
    "Personal Income and Outlays": ("U.S. personal income and spending", "Consumer", 78,
                                    "Income, spending, and inflation data provide evidence about consumer demand.",
                                    "https://www.bea.gov/news/schedule"),
    "Advance Monthly Sales for Retail and Food Services": ("U.S. retail sales", "Consumer", 80,
                                                             "Retail sales provide evidence about household demand.",
                                                             "https://www.census.gov/retail/index.html"),
}


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
        return {"provider": self.name, "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "live": False, "stale": False, "events": events}


class FredReleaseCalendarProvider(CatalystCalendarProvider):
    """Official economic release dates published through the FRED API."""

    name = "FRED official economic release calendar"

    def __init__(
        self, cache, api_key: str | None = None, timeout: int = 20,
        today: Callable[[], date] | None = None,
    ):
        self.cache = cache
        self.api_key = api_key or os.getenv("FRED_API_KEY")
        if not self.api_key:
            raise ProviderError("FRED_API_KEY is required for the live economic calendar.")
        self.timeout = timeout
        self.today = today or date.today

    def snapshot(self) -> dict[str, Any]:
        cache_parameters = {"version": 2, "release_ids": sorted(_RELEASE_IDS)}
        cached = self.cache.get("fred_calendar", "release_dates", cache_parameters)
        if cached:
            return {**cached.value, "cache_status": "Fresh cache", "cache_age_seconds": round(cached.age_seconds)}
        try:
            snapshot = self._request()
            self.cache.put("fred_calendar", "release_dates", cache_parameters, snapshot, 6 * 60 * 60)
            return {**snapshot, "cache_status": "Fresh live response", "cache_age_seconds": 0}
        except ProviderError as exc:
            stale = self.cache.get("fred_calendar", "release_dates", cache_parameters, allow_expired=True)
            if stale and stale.age_seconds <= 14 * 86400:
                return {
                    **stale.value, "stale": True, "cache_status": "Stale cached fallback",
                    "cache_age_seconds": round(stale.age_seconds), "error": str(exc),
                }
            return {
                "provider": self.name, "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "live": False, "stale": True, "events": [], "cache_status": "Unavailable",
                "cache_age_seconds": None, "error": str(exc),
            }

    def _request(self) -> dict[str, Any]:
        try:
            import requests
        except ImportError as exc:
            raise ProviderError("Install the requests package to use the FRED calendar.") from exc
        today = self.today()
        cutoff = today + timedelta(days=180)
        events = []
        seen = set()
        errors = []
        for release_id, release_name in _RELEASE_IDS.items():
            params = {
                "api_key": self.api_key, "file_type": "json", "release_id": release_id,
                "sort_order": "desc", "include_release_dates_with_no_data": "true", "limit": "1000",
            }
            try:
                response = requests.get(FRED_RELEASE_DATES_URL, params=params, timeout=self.timeout)
                response.raise_for_status()
                payload = response.json()
                if payload.get("error_message"):
                    raise ProviderError(str(payload["error_message"]))
            except (requests.RequestException, ValueError, ProviderError) as exc:
                errors.append(f"{release_name}: {exc}")
                continue
            rule = _RELEASE_RULES[release_name]
            for item in payload.get("release_dates", []):
                try:
                    release_date = date.fromisoformat(str(item["date"]))
                except (KeyError, TypeError, ValueError):
                    continue
                if not today <= release_date <= cutoff:
                    continue
                title, category, importance, rationale, agency_url = rule
                identity = (title, release_date.isoformat())
                if identity in seen:
                    continue
                seen.add(identity)
                events.append({
                    "title": title, "category": category, "date": release_date.isoformat(),
                    "importance": importance, "confidence": 95, "scope": "global", "affected": [],
                    "rationale": rationale, "source": f"FRED release calendar — {release_name}",
                    "source_url": agency_url, "calendar_url": FRED_CALENDAR_URL,
                    "source_live": True, "release_id": release_id,
                })
        events.sort(key=lambda event: (event["date"], -event["importance"], event["title"]))
        if not events:
            raise ProviderError("FRED returned no recognized upcoming economic releases.")
        result = {
            "provider": self.name, "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "live": True, "stale": False, "events": events, "source_url": FRED_CALENDAR_URL,
        }
        if errors:
            result["error"] = "Some releases were unavailable: " + "; ".join(errors)
        return result


class AlphaVantageEarningsCalendarProvider(CatalystCalendarProvider):
    name = "Alpha Vantage earnings calendar"
    base_url = "https://www.alphavantage.co/query"

    def __init__(self, cache, api_key: str | None = None, timeout: int = 20):
        self.cache = cache
        self.api_key = api_key or os.getenv("ALPHA_VANTAGE_API_KEY")
        self.timeout = timeout

    def snapshot(self) -> dict[str, Any]:
        if not self.api_key:
            return self._unavailable("ALPHA_VANTAGE_API_KEY is missing.")
        parameters = {"version": 1, "horizon": "3month"}
        cached = self.cache.get("alpha_vantage_earnings", "calendar", parameters)
        if cached:
            return {**cached.value, "cache_status": "Fresh cache", "cache_age_seconds": round(cached.age_seconds)}
        daily_limit = int(os.getenv("ALPHA_VANTAGE_DAILY_LIMIT", "25"))
        daily_reserve = int(os.getenv("ALPHA_VANTAGE_DAILY_RESERVE", "2"))
        if not self.cache.claim_request("alpha_vantage", daily_limit, daily_reserve):
            return self._stale_or_unavailable(parameters, "Alpha Vantage daily request budget is exhausted.")
        try:
            snapshot = self._request()
            self.cache.put("alpha_vantage_earnings", "calendar", parameters, snapshot, 24 * 60 * 60)
            return {**snapshot, "cache_status": "Fresh live response", "cache_age_seconds": 0}
        except ProviderError as exc:
            return self._stale_or_unavailable(parameters, str(exc))

    def _request(self) -> dict[str, Any]:
        try:
            import requests
        except ImportError as exc:
            raise ProviderError("Install requests to use the Alpha Vantage earnings calendar.") from exc
        try:
            response = requests.get(self.base_url, params={
                "function": "EARNINGS_CALENDAR", "horizon": "3month", "apikey": self.api_key,
            }, timeout=self.timeout)
            response.raise_for_status()
            text = response.text.strip()
        except requests.RequestException as exc:
            raise ProviderError(f"Alpha Vantage earnings request failed: {exc}") from exc
        if not text or text.startswith("{"):
            try:
                payload = response.json()
                message = payload.get("Information") or payload.get("Note") or payload.get("Error Message")
            except ValueError:
                message = None
            raise ProviderError(str(message or "Alpha Vantage returned an invalid earnings calendar."))
        rows = csv.DictReader(io.StringIO(text))
        events = []
        today = date.today()
        for row in rows:
            symbol = str(row.get("symbol", "")).strip().upper()
            try:
                report_date = date.fromisoformat(str(row.get("reportDate", "")))
            except ValueError:
                continue
            if not symbol or report_date < today:
                continue
            estimate = _optional_float(row.get("estimate"))
            events.append({
                "title": f"{symbol} quarterly earnings", "category": "Earnings",
                "date": report_date.isoformat(), "importance": 94, "confidence": 75,
                "scope": "company", "affected": [symbol],
                "rationale": "Quarterly results can reset revenue, margin, earnings, and guidance expectations.",
                "source": "Alpha Vantage earnings calendar", "source_url": "https://www.alphavantage.co/documentation/",
                "source_live": True, "source_stale": False, "timing_status": "Estimated",
                "fiscal_date_ending": row.get("fiscalDateEnding") or None,
                "eps_estimate": estimate, "currency": row.get("currency") or None,
            })
        if not events:
            raise ProviderError("Alpha Vantage returned no upcoming earnings events.")
        return {"provider": self.name, "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "live": True, "stale": False, "events": events}

    def _stale_or_unavailable(self, parameters: dict[str, Any], error: str) -> dict[str, Any]:
        stale = self.cache.get("alpha_vantage_earnings", "calendar", parameters, allow_expired=True)
        if stale and stale.age_seconds <= 30 * 86400:
            events = [{**event, "source_stale": True} for event in stale.value.get("events", [])]
            return {**stale.value, "events": events, "stale": True, "error": error,
                    "cache_status": "Stale cached fallback", "cache_age_seconds": round(stale.age_seconds)}
        return self._unavailable(error)

    def _unavailable(self, error: str) -> dict[str, Any]:
        return {"provider": self.name, "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "live": False, "stale": True, "events": [], "error": error,
                "cache_status": "Unavailable", "cache_age_seconds": None}


class CombinedCatalystCalendarProvider(CatalystCalendarProvider):
    name = "Official economic and earnings calendars"

    def __init__(self, *providers: CatalystCalendarProvider):
        self.providers = providers

    def snapshot(self) -> dict[str, Any]:
        snapshots = [provider.snapshot() for provider in self.providers]
        events = [event for snapshot in snapshots for event in snapshot.get("events", [])]
        errors = [snapshot["error"] for snapshot in snapshots if snapshot.get("error")]
        return {
            "provider": self.name, "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "live": any(snapshot.get("live") for snapshot in snapshots),
            "stale": all(snapshot.get("stale") for snapshot in snapshots),
            "events": events, "components": snapshots,
            "error": "; ".join(errors) if errors else None,
            "cache_status": " · ".join(str(snapshot.get("cache_status", "Direct")) for snapshot in snapshots),
        }


def _event(title: str, category: str, event_date: date, importance: int, confidence: int,
           scope: str, affected: list[str], rationale: str) -> dict[str, Any]:
    return {
        "title": title, "category": category, "date": event_date.isoformat(),
        "importance": importance, "confidence": confidence, "scope": scope,
        "affected": affected, "rationale": rationale, "source": "Illustrative Atlas schedule",
        "source_live": False,
    }


def _optional_float(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "", "None") else None
    except (TypeError, ValueError):
        return None
