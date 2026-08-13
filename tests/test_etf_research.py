from __future__ import annotations

from core.providers.demo_provider import DemoProvider
from core.providers.hybrid_provider import HybridMarketDataProvider
from core.providers.tiingo_provider import TiingoProvider
from core.services.analysis_service import AnalysisService
from core.services.report_repository import ReportRepository
from core.services.watchlist_service import rank_watchlist
from core.services.holding_guidance_service import build_holding_guidance


def test_tiingo_metadata_classifies_etf_from_description():
    provider = object.__new__(TiingoProvider)
    provider._get = lambda ticker, endpoint="": {
        "ticker": ticker, "name": "Example Index Fund ETF Shares",
        "description": "The Fund is an exchange-traded fund that tracks an index.",
        "exchangeCode": "NYSE",
    }
    result = provider.security_metadata("TEST")
    assert result["asset_type"] == "ETF"


def test_hybrid_etf_path_skips_company_fundamentals():
    class Alpha:
        def fundamentals(self, ticker):
            raise AssertionError("ETF research must not request company fundamentals")
        def news(self, ticker):
            return []
        def usage_status(self):
            return {"remaining": 0}

    class Prices(DemoProvider):
        def price_snapshot(self, ticker):
            return {"price": 500, "change_percent": 0.5, "observed_at": "2026-08-13"}
        def security_metadata(self, ticker):
            return {"name": "Example ETF", "description": "Tracks an index", "asset_type": "ETF"}

    snapshot = HybridMarketDataProvider(Alpha(), Prices()).snapshot("ETF")
    assert snapshot["asset_type"] == "ETF"
    assert snapshot["source"] == "Tiingo ETF market data"
    assert snapshot["fundamentals_status"] == "ETF market-data analysis"


def test_etf_analysis_uses_market_evidence_and_labels_guidance(tmp_path):
    class EtfProvider(DemoProvider):
        name = "ETF test provider"
        def snapshot(self, ticker):
            result = super().snapshot("AAPL")
            result.update({
                "symbol": ticker, "name": "Example ETF", "asset_type": "ETF",
                "source": "ETF test provider", "sector": "Diversified fund", "industry": "ETF",
                "pe_ratio": None, "price_to_book": None, "profit_margin": None,
                "operating_margin": None, "return_on_equity": None,
                "revenue_growth": None, "earnings_growth": None, "debt_to_equity": None,
            })
            return result
        def news(self, ticker):
            return []

    repository = ReportRepository(tmp_path / "atlas.db")
    report = AnalysisService(EtfProvider(), repository).analyze("SPY")
    assert report.company_metrics["asset_type"] == "ETF"
    assert "ETF committee" in report.executive_summary
    assert all("ETF" in item.thesis or item.strategy in {"Macro", "Quant", "Market Intelligence"} for item in report.assessments)
    ranked = rank_watchlist(["SPY"], {"SPY": report})
    assert ranked["rows"][0]["Asset type"] == "ETF"
    guidance = build_holding_guidance(["SPY"], {"SPY": report})
    assert guidance["rows"][0]["Asset type"] == "ETF"