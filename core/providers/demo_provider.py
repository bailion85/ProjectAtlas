from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.providers.market_provider import MarketDataProvider, ProviderError


_COMPANIES = {
    "AAPL": ("Apple Inc.", "Technology", "Consumer Electronics", 224.50, 34.2, 0.061, 0.239, 0.31, 1.22),
    "MSFT": ("Microsoft Corporation", "Technology", "Software", 418.79, 35.0, 0.164, 0.354, 0.33, 0.89),
    "NVDA": ("NVIDIA Corporation", "Technology", "Semiconductors", 181.25, 48.5, 0.554, 0.552, 0.76, 1.75),
    "GOOGL": ("Alphabet Inc.", "Communication Services", "Internet Content", 196.31, 25.1, 0.138, 0.286, 0.32, 1.04),
    "AMZN": ("Amazon.com, Inc.", "Consumer Cyclical", "Internet Retail", 213.42, 37.4, 0.110, 0.101, 0.23, 1.31),
}


class DemoProvider(MarketDataProvider):
    name = "Demo data (not live)"

    def search(self, query: str) -> list[dict[str, str]]:
        query = query.strip().lower()
        return [
            {"symbol": symbol, "name": values[0]}
            for symbol, values in _COMPANIES.items()
            if query in symbol.lower() or query in values[0].lower()
        ]

    def snapshot(self, ticker: str) -> dict[str, Any]:
        symbol = ticker.upper()
        if symbol not in _COMPANIES:
            raise ProviderError(f"{symbol} is not included in the demo dataset.")
        name, sector, industry, price, pe, growth, margin, roe, beta = _COMPANIES[symbol]
        observed_at = datetime.now(timezone.utc).isoformat()
        return {
            "symbol": symbol, "name": name, "description": f"Demo profile for {name}.",
            "sector": sector, "industry": industry, "price": price,
            "change_percent": 0.4, "market_cap": None, "pe_ratio": pe,
            "forward_pe": pe * 0.9, "peg_ratio": pe / max(growth * 100, 1),
            "price_to_book": None, "profit_margin": margin, "operating_margin": margin * 0.9,
            "return_on_equity": roe, "revenue_growth": growth, "earnings_growth": growth * 1.15,
            "debt_to_equity": None, "free_cashflow": None, "beta": beta,
            "fifty_two_week_high": price * 1.12, "fifty_two_week_low": price * 0.69,
            "analyst_target": price * 1.08, "observed_at": observed_at, "source": self.name,
        }

    def news(self, ticker: str) -> list[dict[str, Any]]:
        return []
