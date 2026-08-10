from pathlib import Path
from unittest.mock import patch

from core.providers.demo_provider import DemoProvider
from core.providers.market_provider import ProviderError
from core.providers.economic_provider import DemoEconomicProvider, FredProvider
from core.models.research import AgentAssessment
from core.services.analysis_service import AnalysisService
from core.services.report_repository import ReportRepository
from core.services.performance_service import analyze_performance
from core.services.macro_service import score_macro_environment
from core.services.committee_service import CommitteeService, PRESETS, normalize_weights
from core.services.comparison_service import ComparisonService


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


def test_committee_presets_normalize_to_one_hundred_percent():
    for preset in PRESETS.values():
        weights = normalize_weights(preset)
        assert sum(weights.values()) == 100
        assert set(weights) == {"Value", "GARP", "Innovation", "Macro", "Quant", "Risk"}


def test_committee_rejects_zero_weights():
    try:
        normalize_weights({strategy: 0 for strategy in PRESETS["Balanced"]})
    except ValueError as exc:
        assert "greater than zero" in str(exc)
    else:
        raise AssertionError("Expected zero strategy weights to fail")


def test_report_preserves_strategy_configuration(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    custom = {"Value": 40, "GARP": 20, "Innovation": 10, "Macro": 10, "Quant": 10, "Risk": 10}
    report = AnalysisService(DemoProvider(), repository).analyze("AAPL", custom)
    saved = repository.get(report.report_id)
    assert saved.strategy_weights == normalize_weights(custom)
    assert saved.committee_contributions == report.committee_contributions


def test_weights_can_change_committee_decision():
    assessments = [
        AgentAssessment(strategy, "bullish" if strategy == "Value" else "bearish" if strategy == "Risk" else "neutral", 90, "Test thesis")
        for strategy in PRESETS["Balanced"]
    ]
    value_only = {strategy: int(strategy == "Value") for strategy in PRESETS["Balanced"]}
    risk_only = {strategy: int(strategy == "Risk") for strategy in PRESETS["Balanced"]}
    bullish_vote, _, bullish_contributions = CommitteeService().decide(assessments, value_only)
    bearish_vote, _, bearish_contributions = CommitteeService().decide(assessments, risk_only)
    assert bullish_vote == "bullish"
    assert bearish_vote == "bearish"
    assert sum(item["weighted_signal"] for item in bullish_contributions) > 0
    assert sum(item["weighted_signal"] for item in bearish_contributions) < 0


def test_comparison_is_ranked_and_saved(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    analysis = AnalysisService(DemoProvider(), repository)
    comparison = ComparisonService(analysis, repository).compare(["AAPL", "MSFT"], PRESETS["Balanced"])
    assert comparison["comparison_id"] is not None
    assert comparison["tickers"] == ["AAPL", "MSFT"]
    assert [row["Rank"] for row in comparison["summary"]] == [1, 2]
    assert comparison["summary"][0]["Score"] >= comparison["summary"][1]["Score"]
    assert len(comparison["strategy_table"]) == 6
    assert len(comparison["performance_history"]) == 61
    saved = repository.get_comparison(comparison["comparison_id"])
    assert saved["strategy_weights"] == normalize_weights(PRESETS["Balanced"])
    assert repository.comparison_history()[0]["id"] == comparison["comparison_id"]


def test_comparison_requires_two_to_four_unique_companies(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    service = ComparisonService(AnalysisService(DemoProvider(), repository), repository)
    for tickers in (["AAPL"], ["AAPL", "AAPL"], ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN"]):
        try:
            service.compare(tickers, PRESETS["Balanced"])
        except ValueError as exc:
            assert "two and four unique" in str(exc)
        else:
            raise AssertionError(f"Expected invalid comparison selection to fail: {tickers}")
