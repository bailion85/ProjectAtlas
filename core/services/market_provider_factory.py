from __future__ import annotations

import os

from core.providers.cached_provider import CachedMarketDataProvider
from core.providers.fallback_provider import LiveFallbackMarketDataProvider
from core.providers.hybrid_provider import HybridMarketDataProvider
from core.providers.market_provider import AlphaVantageProvider, MarketDataProvider, ProviderError
from core.providers.sec_provider import SecCompanyFactsProvider
from core.providers.tiingo_provider import TiingoProvider
from core.providers.yahooquery_provider import YahooQueryProvider
from core.services.provider_cache import ProviderCache


def build_live_market_provider(cache: ProviderCache | None = None) -> CachedMarketDataProvider:
    """Build Atlas's production market provider with no demo-data substitution."""
    cache = cache or ProviderCache(os.getenv("ATLAS_CACHE_PATH", "data/provider_cache.db"))
    yahoo = YahooQueryProvider()
    prices: MarketDataProvider = yahoo
    if os.getenv("TIINGO_API_KEY"):
        prices = LiveFallbackMarketDataProvider(TiingoProvider(), yahoo)
    alpha_key = os.getenv("ALPHA_VANTAGE_API_KEY")
    if alpha_key:
        delegate: MarketDataProvider = HybridMarketDataProvider(
            AlphaVantageProvider(usage_store=cache), prices, SecCompanyFactsProvider(cache),
        )
    else:
        delegate = prices
    return CachedMarketDataProvider(delegate, cache)
