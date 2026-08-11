from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import math
from typing import Any

from core.providers.market_provider import MarketDataProvider, ProviderError


DEMO_PROVIDER_VERSION = 2


_COMPANIES = {
    "AAPL": ("Apple Inc.", "Technology", "Consumer Electronics", 224.50, 34.2, 0.061, 0.239, 0.31, 1.22),
    "MSFT": ("Microsoft Corporation", "Technology", "Software", 418.79, 35.0, 0.164, 0.354, 0.33, 0.89),
    "NVDA": ("NVIDIA Corporation", "Technology", "Semiconductors", 181.25, 48.5, 0.554, 0.552, 0.76, 1.75),
    "GOOGL": ("Alphabet Inc.", "Communication Services", "Internet Content", 196.31, 25.1, 0.138, 0.286, 0.32, 1.04),
    "GOOG": ("Alphabet Inc. Class C", "Communication Services", "Internet Content", 197.04, 25.2, 0.138, 0.286, 0.32, 1.04),
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

    def history(self, ticker: str) -> list[dict[str, Any]]:
        symbol = ticker.upper()
        if symbol != "SPY" and symbol not in _COMPANIES:
            raise ProviderError(f"{symbol} is not included in the demo dataset.")
        target = 642.69 if symbol == "SPY" else _COMPANIES[symbol][3]
        drift = {"SPY": 0.009, "AAPL": 0.012, "MSFT": 0.013, "NVDA": 0.022, "GOOGL": 0.011, "GOOG": 0.011, "AMZN": 0.010}[symbol]
        closes = [100.0]
        phase = sum(ord(character) for character in symbol) % 11
        for index in range(1, 61):
            monthly_return = drift + math.sin(index * 1.7 + phase) * 0.035
            closes.append(closes[-1] * (1 + monthly_return))
        scale = target / closes[-1]
        return [
            {"date": _month_label(2021, 8, index), "close": round(close * scale, 2)}
            for index, close in enumerate(closes)
        ]

    def daily_history(self, ticker: str) -> list[dict[str, Any]]:
        symbol = ticker.upper()
        if symbol != "SPY" and symbol not in _COMPANIES:
            raise ProviderError(f"{symbol} is not included in the demo dataset.")
        target = 642.69 if symbol == "SPY" else _COMPANIES[symbol][3]
        phase = sum(ord(character) for character in symbol) % 13
        closes = [125.0]
        for index in range(1, 320):
            # A soft early decline followed by a durable recovery creates a
            # realistic, deterministic crossover for the illustrative dataset.
            drift = -0.00035 if index < 190 else 0.00225
            daily_return = drift + math.sin(index * 0.31 + phase) * 0.0045
            closes.append(closes[-1] * (1 + daily_return))
        scale = target / closes[-1]
        trading_days = _trading_days(date.today(), len(closes))
        return [
            {"date": observed_on.isoformat(), "close": round(close * scale, 2)}
            for observed_on, close in zip(trading_days, closes)
        ]


def _month_label(year: int, month: int, offset: int) -> str:
    absolute_month = year * 12 + month - 1 + offset
    return f"{absolute_month // 12:04d}-{absolute_month % 12 + 1:02d}-01"


def _trading_days(end: date, count: int) -> list[date]:
    days = []
    current = end
    while len(days) < count:
        if current.weekday() < 5:
            days.append(current)
        current -= timedelta(days=1)
    return list(reversed(days))
