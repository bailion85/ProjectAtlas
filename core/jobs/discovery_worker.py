from __future__ import annotations

import json
import os

from dotenv import load_dotenv

from core.providers.cached_provider import CachedMarketDataProvider
from core.providers.demo_provider import DemoProvider
from core.providers.fallback_provider import FallbackMarketDataProvider
from core.providers.hybrid_provider import HybridMarketDataProvider
from core.providers.market_provider import AlphaVantageProvider
from core.providers.sec_provider import SecCompanyFactsProvider
from core.providers.tiingo_provider import TiingoProvider
from core.services.discovery_scan_service import DiscoveryScanService
from core.services.discovery_scheduler_service import ScheduledDiscoveryService
from core.services.provider_cache import ProviderCache
from core.services.report_repository import ReportRepository


def main() -> int:
    load_dotenv()
    cache = ProviderCache(os.getenv("ATLAS_CACHE_PATH", "data/provider_cache.db"))
    provider_name = os.getenv("ATLAS_DATA_PROVIDER", "demo").lower()
    if provider_name == "hybrid":
        base = HybridMarketDataProvider(
            AlphaVantageProvider(usage_store=cache), TiingoProvider(),
            SecCompanyFactsProvider(cache),
        )
    elif provider_name == "alpha_vantage":
        base = AlphaVantageProvider(usage_store=cache)
    else:
        base = DemoProvider()
    provider = CachedMarketDataProvider(base, cache)
    if (provider_name in {"alpha_vantage", "hybrid"} and
            os.getenv("ATLAS_ALLOW_DEMO_FALLBACK", "true").lower() in {"1", "true", "yes", "on"}):
        provider = FallbackMarketDataProvider(provider, DemoProvider())
    repository = ReportRepository(os.getenv("ATLAS_DATABASE_PATH", "data/atlas.db"))
    scheduler = ScheduledDiscoveryService(
        DiscoveryScanService(provider, repository, cache), repository,
    )
    result = scheduler.run("Windows task")
    print(json.dumps(result, indent=2, default=str))
    return 1 if result.get("status") in {"Failed", "Partial"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
