from __future__ import annotations

import argparse
import json
import os

from dotenv import load_dotenv

from core.providers.cached_provider import CachedEconomicDataProvider, CachedMarketDataProvider
from core.providers.calendar_provider import (
    AlphaVantageEarningsCalendarProvider,
    CombinedCatalystCalendarProvider,
    DemoCatalystCalendarProvider,
    FredReleaseCalendarProvider,
)
from core.providers.demo_provider import DemoProvider
from core.providers.economic_provider import DemoEconomicProvider, FredProvider
from core.providers.event_provider import CalendarEconomicEventProvider, DemoEconomicEventProvider
from core.providers.hybrid_provider import HybridMarketDataProvider
from core.providers.market_provider import AlphaVantageProvider
from core.providers.sec_provider import SecCompanyFactsProvider
from core.providers.tiingo_provider import TiingoProvider
from core.services.analysis_service import AnalysisService
from core.services.provider_cache import ProviderCache
from core.services.report_repository import ReportRepository
from core.services.scheduler_service import ScheduledResearchService


def build_scheduler() -> ScheduledResearchService:
    load_dotenv(override=True)
    cache = ProviderCache(os.getenv("ATLAS_CACHE_PATH", "data/provider_cache.db"))
    provider_name = os.getenv("ATLAS_DATA_PROVIDER", "hybrid").lower()
    if provider_name == "hybrid":
        base_provider = HybridMarketDataProvider(
            AlphaVantageProvider(usage_store=cache), TiingoProvider(),
            SecCompanyFactsProvider(cache),
        )
    elif provider_name == "alpha_vantage":
        base_provider = AlphaVantageProvider(usage_store=cache)
    else:
        base_provider = DemoProvider()
    provider = CachedMarketDataProvider(base_provider, cache)

    macro_name = os.getenv("ATLAS_MACRO_PROVIDER", "fred").lower()
    base_macro = FredProvider() if macro_name == "fred" else DemoEconomicProvider()
    macro_provider = CachedEconomicDataProvider(base_macro, cache)

    calendar_name = os.getenv(
        "ATLAS_CALENDAR_PROVIDER", "fred" if os.getenv("FRED_API_KEY") else "demo"
    ).lower()
    if calendar_name == "fred":
        economic_calendar = FredReleaseCalendarProvider(cache)
        calendar_provider = (
            CombinedCatalystCalendarProvider(
                economic_calendar, AlphaVantageEarningsCalendarProvider(cache)
            ) if os.getenv("ALPHA_VANTAGE_API_KEY") else economic_calendar
        )
        event_provider = CalendarEconomicEventProvider(calendar_provider)
    else:
        calendar_provider = DemoCatalystCalendarProvider()
        event_provider = DemoEconomicEventProvider()

    repository = ReportRepository(os.getenv("ATLAS_DATABASE_PATH", "data/atlas.db"))
    analysis = AnalysisService(
        provider, repository, macro_provider, event_provider, calendar_provider,
    )
    return ScheduledResearchService(
        analysis, repository, provider, macro_provider, event_provider, calendar_provider,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Run now even when not due.")
    args = parser.parse_args()
    scheduler = build_scheduler()
    status = scheduler.status()
    if not args.force and not status["due"]:
        print(json.dumps({"status": "Not due", "next_run": status["next_run"]}, indent=2))
        return 0
    result = scheduler.run("Windows task" if not args.force else "Manual background test")
    print(json.dumps(result, indent=2, default=str))
    return 1 if result.get("status") in {"Failed", "Partial"} else 0


if __name__ == "__main__":
    raise SystemExit(main())