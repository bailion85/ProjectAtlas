from __future__ import annotations

from typing import Any

from core.providers.market_provider import AlphaVantageProvider, MarketDataProvider, ProviderError


HYBRID_PROVIDER_VERSION = 8


class HybridMarketDataProvider(MarketDataProvider):
    """Alpha Vantage fundamentals/news with Tiingo prices and history."""

    name = "Tiingo + Alpha Vantage"

    supports_no_credit_research = True
    snapshot_schema_version = 2

    def __init__(self, alpha: AlphaVantageProvider, prices: MarketDataProvider, sec=None):
        self.alpha = alpha
        self.prices = prices
        self.sec = sec

    def search(self, query: str) -> list[dict[str, str]]:
        return self.alpha.search(query)

    def market_movers(self) -> dict[str, Any]:
        try:
            return self.alpha.market_movers()
        except ProviderError:
            return self.prices.market_movers()

    def market_dashboard(self, tickers: tuple[str, ...]) -> dict[str, Any]:
        reader = getattr(self.prices, "market_dashboard", None)
        if reader is None:
            raise ProviderError(f"{self.prices.name} does not provide batched dashboard quotes.")
        return reader(tickers)
    def snapshot(self, ticker: str) -> dict[str, Any]:
        price_reader = getattr(self.prices, "price_snapshot", None) or self.prices.snapshot
        price_snapshot = price_reader(ticker)
        metadata_reader = getattr(self.prices, "security_metadata", None)
        metadata = metadata_reader(ticker) if metadata_reader else {}
        if metadata.get("asset_type") == "ETF":
            fundamentals = {
                "symbol": ticker.upper(), "name": metadata.get("name") or ticker.upper(),
                "description": metadata.get("description") or "", "asset_type": "ETF",
                "sector": "Diversified fund", "industry": "ETF", "market_cap": None,
                "pe_ratio": None, "forward_pe": None, "peg_ratio": None,
                "price_to_book": None, "profit_margin": None, "operating_margin": None,
                "return_on_equity": None, "revenue_growth": None, "earnings_growth": None,
                "debt_to_equity": None, "free_cashflow": None, "beta": None,
                "fifty_two_week_high": None, "fifty_two_week_low": None,
                "analyst_target": None,
            }
            fundamentals_status = "ETF market-data analysis"
        else:
            try:
                fundamentals = self.alpha.fundamentals(ticker)
                fundamentals["asset_type"] = "Stock"
                fundamentals_status = "Alpha Vantage live fundamentals"
            except ProviderError as exc:
                try:
                    if self.sec is None:
                        raise ProviderError("SEC EDGAR fallback is not configured.")
                    fundamentals = self.sec.fundamentals(ticker, price_snapshot.get("price"))
                    fundamentals["asset_type"] = "Stock"
                    fundamentals_status = "SEC EDGAR fallback"
                except (ProviderError, ValueError) as sec_exc:
                    fundamentals = {
                        "symbol": ticker.upper(), "name": metadata.get("name") or ticker.upper(),
                        "description": metadata.get("description") or "", "asset_type": "Stock",
                        "sector": "Unknown", "industry": "Unknown",
                    }
                    fundamentals_status = f"Price only: Alpha Vantage: {exc}; SEC EDGAR: {sec_exc}"
        price_source = price_snapshot.get("source") or "Tiingo"
        if "demo" in price_source.lower():
            price_source = "Tiingo"
        fundamentals.update({
            "price": price_snapshot.get("price"),
            "change_percent": price_snapshot.get("change_percent"),
            "observed_at": price_snapshot.get("observed_at") or fundamentals.get("observed_at"),
            "source": (
                f"{price_source} ETF market data" if fundamentals_status == "ETF market-data analysis"
                else f"{price_source} + Alpha Vantage" if fundamentals_status == "Alpha Vantage live fundamentals"
                else f"{price_source} + SEC EDGAR" if fundamentals_status == "SEC EDGAR fallback"
                else f"{price_source} price-only fallback"
            ),
            "fundamentals_status": fundamentals_status,
        })
        return fundamentals
    def market_news(self, limit: int = 50) -> dict[str, Any]:
        return self.alpha.market_news(limit)
    def news(self, ticker: str) -> list[dict[str, Any]]:
        try:
            return self.alpha.news(ticker)
        except ProviderError:
            return []

    def history(self, ticker: str) -> list[dict[str, Any]]:
        return self.prices.history(ticker)

    def daily_history(self, ticker: str) -> list[dict[str, Any]]:
        return self.prices.daily_history(ticker)

    def usage_status(self) -> dict[str, Any]:
        return self.alpha.usage_status()

    @staticmethod
    def quota_cost(operation: str) -> int:
        return {"search": 1, "market_movers": 1, "snapshot": 1, "news": 1, "market_news": 1, "history": 0, "daily_history": 0}.get(operation, 0)
