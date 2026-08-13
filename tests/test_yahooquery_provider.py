from __future__ import annotations

import pandas as pd

from core.providers.fallback_provider import LiveFallbackMarketDataProvider
from core.providers.market_provider import ProviderError
from core.providers.yahooquery_provider import YahooQueryProvider


class FakeTicker:
    price = {"AAPL": {
        "regularMarketPrice": 201.0, "regularMarketPreviousClose": 200.0,
        "regularMarketChangePercent": .005, "regularMarketVolume": 1_500_000,
        "regularMarketTime": 1_786_000_000,
    }}
    quote_type = {"AAPL": {"longName": "Apple", "quoteType": "EQUITY", "exchange": "NMS"}}
    asset_profile = {"AAPL": {"sector": "Technology", "industry": "Consumer Electronics"}}
    summary_detail = {"AAPL": {"marketCap": 3_000_000, "trailingPE": 25, "forwardPE": 22,
                                "beta": 1.1, "fiftyTwoWeekHigh": 210, "fiftyTwoWeekLow": 140}}
    key_stats = {"AAPL": {"pegRatio": 1.8, "priceToBook": 8}}
    financial_data = {"AAPL": {"profitMargins": .24, "revenueGrowth": .08,
                                 "earningsGrowth": .1, "targetMeanPrice": 220}}

    def history(self, **kwargs):
        index = pd.MultiIndex.from_tuples([
            ("AAPL", pd.Timestamp("2026-08-11")), ("AAPL", pd.Timestamp("2026-08-12")),
        ])
        return pd.DataFrame({"adjclose": [199.0, 201.0]}, index=index)

    def news(self, **kwargs):
        return []


def test_yahooquery_normalizes_quote_history_and_company_data():
    provider = YahooQueryProvider()
    provider._ticker = lambda symbols: FakeTicker()
    quote = provider.price_snapshot("AAPL")
    assert quote["price"] == 201
    assert quote["change_percent"] == .5
    assert len(provider.daily_history("AAPL")) == 2
    snapshot = provider.snapshot("AAPL")
    assert snapshot["asset_type"] == "Stock"
    assert snapshot["forward_pe"] == 22
    assert snapshot["source"] == "YahooQuery"


def test_live_fallback_uses_yahoo_when_primary_is_rate_limited():
    class Limited:
        name = "Tiingo"
        def daily_history(self, ticker):
            raise ProviderError("429 Too Many Requests")

    class Yahoo:
        name = "YahooQuery"
        def daily_history(self, ticker):
            return [{"date": "2026-08-12", "close": 201}]

    provider = LiveFallbackMarketDataProvider(Limited(), Yahoo())
    assert provider.daily_history("AAPL")[0]["close"] == 201
    assert provider.status()["live_fallbacks"] == 1

def test_live_fallback_completes_symbols_omitted_by_primary_batch():
    class Primary:
        name = "Tiingo"
        def market_dashboard(self, tickers):
            return {"provider": self.name, "quotes": [{"ticker": "SPY", "price": 600}]}

    class Yahoo:
        name = "YahooQuery"
        def market_dashboard(self, tickers):
            return {"provider": self.name, "quotes": [
                {"ticker": ticker, "price": 100} for ticker in tickers
            ]}

    provider = LiveFallbackMarketDataProvider(Primary(), Yahoo())
    result = provider.market_dashboard(("SPY", "GC=F", "SI=F"))
    assert {row["ticker"] for row in result["quotes"]} == {"SPY", "GC=F", "SI=F"}
    assert result["provider"] == "Tiingo + YahooQuery"
