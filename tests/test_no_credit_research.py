from __future__ import annotations

from datetime import datetime, timezone

from core.providers.demo_provider import DemoProvider
from core.providers.economic_provider import DemoEconomicProvider
from core.providers.event_provider import DemoEconomicEventProvider
from core.providers.calendar_provider import DemoCatalystCalendarProvider
from core.providers.hybrid_provider import HybridMarketDataProvider
from core.providers.market_provider import ProviderError
from core.providers.sec_provider import SecCompanyFactsProvider
from core.services.analysis_service import AnalysisService
from core.services.provider_cache import ProviderCache
from core.services.report_repository import ReportRepository
from core.services.scheduler_service import ScheduledResearchService


def _facts_snapshot() -> dict:
    def fact(values):
        return {"units": {"USD": [
            {"form": "10-K", "fy": 2024, "filed": "2025-01-01", "val": values[0]},
            {"form": "10-K", "fy": 2025, "filed": "2026-01-01", "val": values[1]},
        ]}}
    shares = {"units": {"shares": [
        {"form": "10-K", "fy": 2024, "filed": "2025-01-01", "val": 10},
        {"form": "10-K", "fy": 2025, "filed": "2026-01-01", "val": 10},
    ]}}
    return {
        "ticker": "TEST", "company": "Test Company", "cik": "0000000001",
        "provider": "SEC EDGAR company facts", "retrieved_at": "2026-01-02T00:00:00+00:00",
        "facts": {"us-gaap": {
            "Revenues": fact((100, 120)), "NetIncomeLoss": fact((10, 18)),
            "OperatingIncomeLoss": fact((15, 24)),
            "NetCashProvidedByUsedInOperatingActivities": fact((20, 30)),
            "PaymentsToAcquirePropertyPlantAndEquipment": fact((5, 6)),
            "Assets": fact((200, 240)), "Liabilities": fact((80, 90)),
            "StockholdersEquity": fact((120, 150)), "CommonStockSharesOutstanding": shares,
        }},
    }


def test_sec_company_facts_convert_to_research_fundamentals(tmp_path):
    provider = SecCompanyFactsProvider(ProviderCache(tmp_path / "cache.db"), "Atlas test@example.com")
    provider.company_facts = lambda ticker: _facts_snapshot()
    result = provider.fundamentals("TEST", price=30)
    assert result["source"] == "SEC EDGAR company facts"
    assert result["revenue_growth"] == 0.2
    assert result["profit_margin"] == 0.15
    assert result["pe_ratio"] == 30 / 1.8
    assert result["market_cap"] == 300


def test_hybrid_falls_back_to_sec_and_empty_news_when_alpha_is_exhausted():
    class ExhaustedAlpha:
        def fundamentals(self, ticker):
            raise ProviderError("Atlas daily Alpha Vantage request budget is exhausted")
        def news(self, ticker):
            raise ProviderError("Atlas daily Alpha Vantage request budget is exhausted")
        def usage_status(self):
            return {"remaining": 0}

    class Prices(DemoProvider):
        def price_snapshot(self, ticker):
            return {"price": 30, "change_percent": 1.5, "observed_at": "2026-01-02"}

    class Sec:
        def fundamentals(self, ticker, price):
            return {"symbol": ticker, "name": "Test", "observed_at": "2026-01-01", "pe_ratio": 20}

    provider = HybridMarketDataProvider(ExhaustedAlpha(), Prices(), Sec())
    snapshot = provider.snapshot("TEST")
    assert snapshot["source"] == "Tiingo + SEC EDGAR"
    assert snapshot["fundamentals_status"] == "SEC EDGAR fallback"
    assert provider.news("TEST") == []


def test_no_credit_scheduler_refreshes_saved_holdings(tmp_path):
    repository = ReportRepository(tmp_path / "atlas.db")
    repository.save_portfolio_holdings(["AAPL"])

    class NoCreditProvider(DemoProvider):
        supports_no_credit_research = True
        def status(self):
            return {"quota_remaining": 0}
        def estimated_requests_for_analysis(self, tickers):
            return 10

    provider = NoCreditProvider()
    scheduler = ScheduledResearchService(
        AnalysisService(provider, repository), repository, provider, DemoEconomicProvider(),
        DemoEconomicEventProvider(), DemoCatalystCalendarProvider(),
        clock=lambda: datetime(2026, 8, 13, tzinfo=timezone.utc),
    )
    scheduler.save_configuration({
        "enabled": True, "interval_hours": 4, "scope": "Holdings", "preset": "Balanced",
        "retry_limit": 0, "scan_alerts": False,
    })
    result = scheduler.run("Test")
    assert result["status"] == "Complete"
    assert result["analyzed"] == 1
    assert repository.latest_reports(["AAPL"])["AAPL"].ticker == "AAPL"


def test_old_portfolio_scope_migrates_to_holdings(tmp_path):
    repository = ReportRepository(tmp_path / "atlas.db")
    repository.save_configuration("scheduler", {"scope": "Portfolio"})
    scheduler = ScheduledResearchService(
        None, repository, DemoProvider(), DemoEconomicProvider(),
        DemoEconomicEventProvider(), DemoCatalystCalendarProvider(),
    )
    assert scheduler.configuration()["scope"] == "Holdings"