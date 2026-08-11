from __future__ import annotations

import os
import threading
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Callable


MARKET_PROVIDER_VERSION = 2

class ProviderError(RuntimeError):
    pass


class MarketDataProvider(ABC):
    name: str

    @abstractmethod
    def search(self, query: str) -> list[dict[str, str]]: ...

    @abstractmethod
    def snapshot(self, ticker: str) -> dict[str, Any]: ...

    @abstractmethod
    def news(self, ticker: str) -> list[dict[str, Any]]: ...

    @abstractmethod
    def history(self, ticker: str) -> list[dict[str, Any]]: ...

    def daily_history(self, ticker: str) -> list[dict[str, Any]]:
        """Daily closes used by technical studies.

        Providers without a dedicated daily feed may return their regular history;
        callers must validate that enough observations are available.
        """
        return self.history(ticker)


class AlphaVantageProvider(MarketDataProvider):
    """Adapter for Alpha Vantage's documented JSON API."""

    name = "Alpha Vantage"
    base_url = "https://www.alphavantage.co/query"

    def __init__(
        self, api_key: str | None = None, timeout: int = 20,
        min_interval_seconds: float = 1.05,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.api_key = api_key or os.getenv("ALPHA_VANTAGE_API_KEY")
        if not self.api_key:
            raise ProviderError("ALPHA_VANTAGE_API_KEY is required for live data.")
        self.timeout = timeout
        self.min_interval_seconds = max(0.0, min_interval_seconds)
        self.sleeper = sleeper
        self.clock = clock
        self._last_request_started: float | None = None
        self._request_lock = threading.Lock()

    def _get(self, **params: str) -> dict[str, Any]:
        try:
            import requests
        except ImportError as exc:
            raise ProviderError("Install the requests package to use Alpha Vantage.") from exc
        try:
            with self._request_lock:
                self._wait_for_request_slot()
                response = requests.get(
                    self.base_url,
                    params={**params, "apikey": self.api_key},
                    timeout=self.timeout,
                )
                response.raise_for_status()
                payload = response.json()
        except requests.RequestException as exc:
            raise ProviderError(f"Alpha Vantage request failed: {exc}") from exc
        except ValueError as exc:
            raise ProviderError("Alpha Vantage returned an invalid response.") from exc
        if not isinstance(payload, dict):
            raise ProviderError("Alpha Vantage returned an unexpected response.")
        message = payload.get("Error Message") or payload.get("Information") or payload.get("Note")
        if message:
            raise ProviderError(str(message))
        return payload

    def _wait_for_request_slot(self) -> None:
        now = self.clock()
        if self._last_request_started is not None:
            delay = self.min_interval_seconds - (now - self._last_request_started)
            if delay > 0:
                self.sleeper(delay)
                now = self.clock()
        self._last_request_started = now

    def search(self, query: str) -> list[dict[str, str]]:
        matches = self._get(function="SYMBOL_SEARCH", keywords=query).get("bestMatches", [])
        return [
            {"symbol": item.get("1. symbol", ""), "name": item.get("2. name", "")}
            for item in matches[:10]
        ]

    def snapshot(self, ticker: str) -> dict[str, Any]:
        overview = self._get(function="OVERVIEW", symbol=ticker)
        quote = self._get(function="GLOBAL_QUOTE", symbol=ticker).get("Global Quote", {})
        if not overview:
            raise ProviderError(f"No company overview found for {ticker}.")
        now = datetime.now(timezone.utc).isoformat()

        def number(key: str, percent: bool = False) -> float | None:
            raw = overview.get(key)
            if raw in (None, "", "None", "-"):
                return None
            try:
                value = float(str(raw).rstrip("%"))
                return value / 100 if percent and str(raw).endswith("%") else value
            except ValueError:
                return None

        return {
            "symbol": overview.get("Symbol", ticker).upper(),
            "name": overview.get("Name") or ticker.upper(),
            "description": overview.get("Description", ""),
            "sector": overview.get("Sector"),
            "industry": overview.get("Industry"),
            "price": _float(quote.get("05. price")),
            "change_percent": _float(str(quote.get("10. change percent", "")).rstrip("%")),
            "market_cap": number("MarketCapitalization"),
            "pe_ratio": number("PERatio"),
            "forward_pe": number("ForwardPE"),
            "peg_ratio": number("PEGRatio"),
            "price_to_book": number("PriceToBookRatio"),
            "profit_margin": number("ProfitMargin"),
            "operating_margin": number("OperatingMarginTTM"),
            "return_on_equity": number("ReturnOnEquityTTM"),
            "revenue_growth": number("QuarterlyRevenueGrowthYOY"),
            "earnings_growth": number("QuarterlyEarningsGrowthYOY"),
            "debt_to_equity": None,
            "free_cashflow": None,
            "beta": number("Beta"),
            "fifty_two_week_high": number("52WeekHigh"),
            "fifty_two_week_low": number("52WeekLow"),
            "analyst_target": number("AnalystTargetPrice"),
            "observed_at": now,
            "source": self.name,
        }

    def news(self, ticker: str) -> list[dict[str, Any]]:
        feed = self._get(function="NEWS_SENTIMENT", tickers=ticker, limit="10").get("feed", [])
        return [
            {
                "title": item.get("title", ""),
                "summary": item.get("summary", ""),
                "url": item.get("url", ""),
                "source": item.get("source", self.name),
                "published_at": item.get("time_published", ""),
                "sentiment": item.get("overall_sentiment_score"),
            }
            for item in feed
        ]

    def history(self, ticker: str) -> list[dict[str, Any]]:
        series = self._get(function="TIME_SERIES_MONTHLY_ADJUSTED", symbol=ticker).get(
            "Monthly Adjusted Time Series", {}
        )
        points = []
        for observed_on, values in series.items():
            close = _float(values.get("5. adjusted close") or values.get("4. close"))
            if close is not None:
                points.append({"date": observed_on, "close": close})
        if not points:
            raise ProviderError(f"No price history found for {ticker.upper()}.")
        return sorted(points, key=lambda point: point["date"])[-61:]

    def daily_history(self, ticker: str) -> list[dict[str, Any]]:
        series = self._get(function="TIME_SERIES_DAILY", symbol=ticker, outputsize="compact").get(
            "Time Series (Daily)", {}
        )
        points = []
        for observed_on, values in series.items():
            close = _float(values.get("4. close"))
            if close is not None:
                points.append({"date": observed_on, "close": close})
        if not points:
            raise ProviderError(f"No daily price history found for {ticker.upper()}.")
        return sorted(points, key=lambda point: point["date"])

def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
