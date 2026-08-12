from __future__ import annotations

from typing import Any

from core.providers.market_provider import AlphaVantageProvider, MarketDataProvider, ProviderError


HYBRID_PROVIDER_VERSION = 3


class HybridMarketDataProvider(MarketDataProvider):
    """Alpha Vantage fundamentals/news with Tiingo prices and history."""

    name = "Tiingo + Alpha Vantage"

    def __init__(self, alpha: AlphaVantageProvider, prices: MarketDataProvider):
        self.alpha = alpha
        self.prices = prices

    def search(self, query: str) -> list[dict[str, str]]:
        return self.alpha.search(query)

    def market_movers(self) -> dict[str, Any]:
        try:
            return self.alpha.market_movers()
        except ProviderError:
            return self.prices.market_movers()

    def snapshot(self, ticker: str) -> dict[str, Any]:
        price_reader = getattr(self.prices, "price_snapshot", None) or self.prices.snapshot
        try:
            fundamentals = self.alpha.fundamentals(ticker)
            fundamentals_status = "Available"
        except ProviderError as exc:
            fundamentals = {
                "symbol": ticker.upper(), "name": ticker.upper(), "description": "",
                "sector": "Unknown", "industry": "Unknown",
            }
            fundamentals_status = f"Unavailable: {exc}"
        price_snapshot = price_reader(ticker)
        fundamentals.update({
            "price": price_snapshot.get("price"),
            "change_percent": price_snapshot.get("change_percent"),
            "observed_at": price_snapshot.get("observed_at") or fundamentals.get("observed_at"),
            "source": self.name if fundamentals_status == "Available" else "Tiingo price-only fallback",
            "fundamentals_status": fundamentals_status,
        })
        return fundamentals

    def news(self, ticker: str) -> list[dict[str, Any]]:
        return self.alpha.news(ticker)

    def history(self, ticker: str) -> list[dict[str, Any]]:
        return self.prices.history(ticker)

    def daily_history(self, ticker: str) -> list[dict[str, Any]]:
        return self.prices.daily_history(ticker)

    def usage_status(self) -> dict[str, Any]:
        return self.alpha.usage_status()

    @staticmethod
    def quota_cost(operation: str) -> int:
        return {"search": 1, "market_movers": 1, "snapshot": 1, "news": 1, "history": 0, "daily_history": 0}.get(operation, 0)
