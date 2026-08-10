from pathlib import Path
from unittest.mock import patch

from core.providers.demo_provider import DemoProvider
from core.providers.market_provider import ProviderError
from core.providers.economic_provider import DemoEconomicProvider, FredProvider
from core.services.analysis_service import AnalysisService
from core.services.report_repository import ReportRepository
from core.services.performance_service import analyze_performance
from core.services.macro_service import score_macro_environment


def test_demo_search():
    assert DemoProvider().search("Apple")[0]["symbol"] == "AAPL"


def test_six_agent_report_is_saved(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    report = AnalysisService(DemoProvider(), repository).analyze("MSFT")
    assert len(report.assessments) == 6
    assert {a.strategy for a in report.assessments} == {"Value", "GARP", "Innovation", "Macro", "Quant", "Risk"}
    assert report.report_id is not None
    assert repository.get(report.report_id).ticker == "MSFT"
    assert report.performance["periods"]["1Y"]["company"] != 0
    assert len(report.performance_history) == 61
    assert len(report.macro["indicators"]) == 5
    macro_assessment = next(item for item in report.assessments if item.strategy == "Macro")
    assert {evidence.label for evidence in macro_assessment.evidence} == {
        "Inflation", "Federal funds rate", "10-year Treasury yield", "Unemployment rate", "Real GDP growth"
    }


def test_watchlist_round_trip(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    repository.add_ticker("aapl")
    assert repository.watchlist() == ["AAPL"]
    repository.remove_ticker("AAPL")
    assert repository.watchlist() == []


def test_watchlist_normalizes_tickers(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    repository.add_ticker("  msft  ")
    assert repository.watchlist() == ["MSFT"]


def test_watchlist_rejects_invalid_tickers(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    for ticker in ("", "AAPL; DROP TABLE reports"):
        try:
            repository.add_ticker(ticker)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Expected {ticker!r} to be rejected")


def test_demo_unknown_ticker_is_clear():
    try:
        DemoProvider().snapshot("UNKNOWN")
    except ProviderError as exc:
        assert "not included in the demo dataset" in str(exc)
    else:
        raise AssertionError("Expected an unknown demo ticker to fail")


def test_report_history_is_newest_first(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    service = AnalysisService(DemoProvider(), repository)
    service.analyze("AAPL")
    service.analyze("MSFT")
    assert [row["ticker"] for row in repository.history()] == ["MSFT", "AAPL"]


def test_performance_metrics_and_benchmark_comparison():
    company = [
        {"date": "2025-01-01", "close": 100},
        {"date": "2025-07-01", "close": 90},
        {"date": "2026-01-01", "close": 120},
    ]
    benchmark = [
        {"date": "2025-01-01", "close": 100},
        {"date": "2025-07-01", "close": 105},
        {"date": "2026-01-01", "close": 110},
    ]
    metrics, chart = analyze_performance(company, benchmark)
    assert metrics["periods"]["1Y"] == {"company": 20.0, "benchmark": 10.0, "relative": 10.0}
    assert metrics["max_drawdown"] == -10.0
    assert chart[-1] == {"date": "2026-01-01", "Company": 120.0, "S&P 500": 110.0}


def test_performance_requires_history():
    try:
        analyze_performance([{"date": "2026-01-01", "close": 100}], [])
    except ValueError as exc:
        assert "two historical observations" in str(exc)
    else:
        raise AssertionError("Expected incomplete history to fail")


def test_demo_macro_snapshot_is_attributed_and_current():
    macro = DemoEconomicProvider().snapshot()
    assert macro["provider"] == "Demo macro data (not live)"
    assert all(indicator["source"] == macro["provider"] for indicator in macro["indicators"].values())
    assert not any(indicator["stale"] for indicator in macro["indicators"].values())


def test_fred_requires_api_key():
    with patch.dict("os.environ", {}, clear=True):
        try:
            FredProvider()
        except ProviderError as exc:
            assert "FRED_API_KEY" in str(exc)
        else:
            raise AssertionError("Expected a missing FRED API key to fail")


def test_macro_score_reflects_sector_rate_sensitivity():
    macro = DemoEconomicProvider().snapshot()
    low_rate_score, _ = score_macro_environment("Technology", macro)
    macro["indicators"]["policy_rate"]["value"] = 6.0
    high_rate_score, _ = score_macro_environment("Technology", macro)
    assert low_rate_score > high_rate_score
