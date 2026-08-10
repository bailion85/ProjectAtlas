from __future__ import annotations

import os
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

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


class AlphaVantageProvider(MarketDataProvider):
    """Adapter for Alpha Vantage's documented JSON API."""

    name = "Alpha Vantage"
    base_url = "https://www.alphavantage.co/query"

    def __init__(self, api_key: str | None = None, timeout: int = 20):
        self.api_key = api_key or os.getenv("ALPHA_VANTAGE_API_KEY")
        if not self.api_key:
            raise ProviderError("ALPHA_VANTAGE_API_KEY is required for live data.")
        self.timeout = timeout

    def _get(self, **params: str) -> dict[str, Any]:
        try:
            import requests
        except ImportError as exc:
            raise ProviderError("Install the requests package to use Alpha Vantage.") from exc
        try:
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


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
