from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import time
from unittest.mock import patch

from core.providers.demo_provider import DemoProvider
from core.providers.market_provider import AlphaVantageProvider, ProviderError
from core.providers.economic_provider import DemoEconomicProvider, FredProvider
from core.providers.cached_provider import CachedMarketDataProvider
from core.providers.fallback_provider import FallbackMarketDataProvider
from core.providers.hybrid_provider import HybridMarketDataProvider
from core.providers.sec_provider import SecCompanyFactsProvider
from core.providers.market_provider import MarketDataProvider
from core.models.research import AgentAssessment
from core.services.analysis_service import AnalysisService
from core.services.report_repository import ReportRepository
from core.services.performance_service import analyze_performance
from core.services.technical_service import analyze_golden_cross
from core.services.risk_service import analyze_risk, severity
from core.services.market_regime_service import analyze_market_environment
from core.providers.event_provider import DemoEconomicEventProvider
from core.providers.calendar_provider import (
    AlphaVantageEarningsCalendarProvider, CombinedCatalystCalendarProvider,
    DemoCatalystCalendarProvider, FredReleaseCalendarProvider,
)
from core.services.catalyst_service import assess_catalysts, global_calendar
from core.services.backtest_service import backtest_golden_cross
from core.services.alert_service import AlertService
from core.services.readiness_service import analyze_entry_readiness
from core.services.settings_service import (
    DEFAULT_CONFIG, load_configuration, profile as settings_profile,
    save_configuration, validate_configuration,
)
from core.services.macro_service import score_macro_environment
from core.services.committee_service import CommitteeService, PRESETS, normalize_weights
from core.services.comparison_service import ComparisonService
from core.services.pdf_service import render_accuracy_report_pdf, render_change_pdf, render_comparison_pdf, render_decision_packet_pdf, render_discovery_pdf, render_portfolio_action_plan_pdf, render_portfolio_pdf, render_report_pdf, render_watchlist_pdf
from core.services.watchlist_service import rank_watchlist
from core.services.portfolio_exposure_service import analyze_portfolio_exposure
from core.services.change_tracking_service import compare_reports
from core.services.scheduler_service import ScheduledResearchService, validate_schedule
from core.services.live_readiness_service import (
    environment_readiness, readiness_summary, test_macro_provider as run_macro_readiness,
    test_market_provider as run_market_readiness,
)
from core.services.provider_cache import ProviderCache
from core.services.thesis_service import evaluate_thesis, validate_thesis
from core.services.stress_test_service import analyze_stress_scenario
from core.services.decision_center_service import build_beginner_guidance, build_decision_center
from core.services.valuation_service import build_valuation, suggested_assumptions
from core.services.financial_health_service import analyze_financial_health
from core.services.sec_monitor_service import SecMonitorService
from core.services.guided_workflow_service import build_company_workflow, build_setup_status
from core.services.position_sizing_service import build_position_plan
from core.services.decision_packet_service import build_decision_packet
from core.services.evidence_trust_service import assess_evidence_trust, build_trust_alert
from core.services.portfolio_action_service import build_portfolio_action_plan
from core.services.decision_accuracy_service import build_label_snapshot, evaluate_snapshot, summarize_accuracy
from core.services.opportunity_discovery_service import build_discovery_result, score_candidate, select_market_candidates
from core.services.discovery_monitor_service import compare_discovery_runs, discovery_alerts
from core.services.discovery_scheduler_service import ScheduledDiscoveryService
from core.services.provider_health_service import build_provider_health


def test_sec_company_facts_requires_compliant_user_agent(tmp_path: Path):
    provider = SecCompanyFactsProvider(ProviderCache(tmp_path / "cache.db"), user_agent="Atlas")
    try:
        provider.company_facts("AAPL")
    except ProviderError as exc:
        assert "contact email" in str(exc)
    else:
        raise AssertionError("Expected an invalid SEC user-agent to fail before a request")


def test_sec_company_facts_uses_ticker_map_and_cache(tmp_path: Path):
    provider = SecCompanyFactsProvider(
        ProviderCache(tmp_path / "cache.db"), user_agent="Project Atlas atlas@example.com"
    )
    ticker_map = {"0": {"ticker": "AAPL", "cik_str": 320193, "title": "Apple Inc."}}
    facts = {"entityName": "Apple Inc.", "facts": {"us-gaap": {}}}
    with patch.object(provider, "_get", side_effect=[ticker_map, facts]) as request:
        first = provider.company_facts("aapl")
        second = provider.company_facts("AAPL")
    assert request.call_count == 2
    assert first["cik"] == "0000320193"
    assert second["cache_status"] == "Fresh cache"


def test_financial_health_preserves_missing_values_and_scores_trends():
    def fact(values, unit="USD"):
        return {"units": {unit: [
            {"form": "10-K", "fy": year, "val": value, "filed": f"{year + 1}-02-01"}
            for year, value in values
        ]}}

    snapshot = {
        "ticker": "TEST", "company": "Test Co", "cik": "0000000001",
        "provider": "SEC EDGAR company facts", "retrieved_at": "2026-08-11T00:00:00+00:00",
        "cache_status": "Fresh live response", "facts": {"us-gaap": {
            "Revenues": fact([(2023, 100.0), (2024, 120.0)]),
            "NetIncomeLoss": fact([(2023, 10.0), (2024, 15.0)]),
            "NetCashProvidedByUsedInOperatingActivities": fact([(2023, 20.0), (2024, 30.0)]),
            "PaymentsToAcquirePropertyPlantAndEquipment": fact([(2023, 5.0), (2024, 6.0)]),
            "Liabilities": fact([(2023, 60.0), (2024, 55.0)]),
        }},
    }
    result = analyze_financial_health(snapshot)
    assert result["posture"] == "Strong"
    assert result["rows"][-1]["Revenue"] == 120.0
    assert result["rows"][-1]["Assets"] is None
    assert result["rows"][-1]["Free cash flow"] == 24.0


def test_demo_search():
    assert DemoProvider().search("Apple")[0]["symbol"] == "AAPL"


def test_demo_supports_both_alphabet_share_classes():
    provider = DemoProvider()
    assert provider.snapshot("GOOG")["symbol"] == "GOOG"
    assert provider.snapshot("GOOGL")["symbol"] == "GOOGL"
    assert len(provider.history("GOOG")) == 61
    assert len(provider.daily_history("GOOG")) == 320


def test_alpha_vantage_provider_paces_free_tier_requests():
    now = [0.0]
    waits = []

    def sleeper(delay: float):
        waits.append(delay)
        now[0] += delay

    provider = AlphaVantageProvider(
        api_key="test", min_interval_seconds=1.05, sleeper=sleeper, clock=lambda: now[0]
    )
    provider._wait_for_request_slot()
    now[0] = 0.2
    provider._wait_for_request_slot()
    assert len(waits) == 1 and abs(waits[0] - 0.85) < 1e-9
    assert abs(now[0] - 1.05) < 1e-9


def test_alpha_vantage_fundamentals_uses_one_request():
    provider = AlphaVantageProvider(api_key="test")
    calls = []

    def fake_get(**params):
        calls.append(params)
        return {"Symbol": "AAPL", "Name": "Apple", "PERatio": "25", "ProfitMargin": "0.2"}

    provider._get = fake_get
    result = provider.fundamentals("AAPL")
    assert len(calls) == 1
    assert result["price"] is None
    assert result["pe_ratio"] == 25


def test_hybrid_provider_uses_alpha_evidence_and_tiingo_prices():
    class FakeAlpha(DemoProvider):
        def fundamentals(self, ticker):
            result = super().snapshot(ticker)
            result["price"] = None
            return result

        def usage_status(self):
            return {"daily_limit": 25, "reserve": 2, "usable_limit": 23, "used": 0, "remaining": 23}

    provider = HybridMarketDataProvider(FakeAlpha(), DemoProvider())
    snapshot = provider.snapshot("AAPL")
    assert snapshot["price"] == DemoProvider().snapshot("AAPL")["price"]
    assert snapshot["pe_ratio"] is not None
    assert snapshot["source"] == "Tiingo + Alpha Vantage"
    assert len(provider.daily_history("AAPL")) >= 200


def test_six_agent_report_is_saved(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    report = AnalysisService(DemoProvider(), repository).analyze("MSFT")
    assert len(report.assessments) == 6
    assert {a.strategy for a in report.assessments} == {"Value", "GARP", "Innovation", "Macro", "Quant", "Risk"}
    assert report.report_id is not None
    assert repository.get(report.report_id).ticker == "MSFT"
    assert report.performance["periods"]["1Y"]["company"] != 0
    assert len(report.performance_history) == 61
    assert report.technical["status"] == "bullish"
    assert report.technical["latest_cross"]["type"] == "golden_cross"
    assert len(report.technical_history) == 260
    assert repository.get(report.report_id).technical["sma_50"] == report.technical["sma_50"]
    assert 0 <= report.risk["score"] <= 100
    assert report.risk["coverage_percent"] == 100
    assert len(report.risk["components"]) == 9
    assert repository.get(report.report_id).risk["severity"] == report.risk["severity"]
    assert 0 <= report.market_environment["score"] <= 100
    assert report.market_environment["event_provider"].startswith("Demo")
    assert repository.get(report.report_id).market_environment["label"] == report.market_environment["label"]
    assert report.catalyst_calendar["readiness"] in {"Clear", "Watch", "Elevated", "Event imminent"}
    assert repository.get(report.report_id).catalyst_calendar["next_event"]["title"] == report.catalyst_calendar["next_event"]["title"]
    assert report.backtest["status"] == "complete"
    assert repository.get(report.report_id).backtest["strategy"] == report.backtest["strategy"]
    assert 0 <= report.entry_readiness["score"] <= 100
    assert report.entry_readiness["coverage_percent"] == 100
    assert len(report.entry_readiness["components"]) == 7
    assert repository.get(report.report_id).entry_readiness["posture"] == report.entry_readiness["posture"]
    assert report.configuration["version"] == 1
    assert report.configuration["profile"] == "Balanced"
    assert repository.get(report.report_id).configuration == report.configuration
    assert len(report.macro["indicators"]) == 5
    macro_assessment = next(item for item in report.assessments if item.strategy == "Macro")
    assert {evidence.label for evidence in macro_assessment.evidence} == {
        "Market environment score", "Inflation", "Federal funds rate", "10-year Treasury yield",
        "Unemployment rate", "Real GDP growth"
    }


def test_watchlist_round_trip(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    repository.add_ticker("aapl")
    assert repository.watchlist() == ["AAPL"]
    repository.remove_ticker("AAPL")
    assert repository.watchlist() == []


def test_watchlist_accepts_more_than_ten_tickers(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    tickers = [f"TICK{index}" for index in range(25)]
    assert repository.add_tickers(tickers) == 25
    assert len(repository.watchlist()) == 25
    assert repository.add_tickers(["tick1", "TICK1"]) == 0


def test_portfolio_positions_round_trip(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    repository.save_portfolio_positions([
        {"Ticker": "aapl", "Allocation": 60},
        {"Ticker": "msft", "Allocation": 40},
    ])
    assert repository.portfolio_positions() == [
        {"ticker": "AAPL", "allocation": 60.0},
        {"ticker": "MSFT", "allocation": 40.0},
    ]
    repository.save_portfolio_positions([{"Ticker": "GOOGL", "Allocation": 100}])
    assert repository.portfolio_positions() == [{"ticker": "GOOGL", "allocation": 100.0}]


def test_portfolio_exposure_aggregates_saved_reports(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    service = AnalysisService(DemoProvider(), repository)
    reports = {ticker: service.analyze(ticker) for ticker in ("AAPL", "MSFT")}
    portfolio = analyze_portfolio_exposure(
        [{"Ticker": "AAPL", "Allocation": 60}, {"Ticker": "MSFT", "Allocation": 40}], reports
    )
    assert portfolio["covered_weight"] == 100
    assert len(portfolio["rows"]) == 2
    assert portfolio["rows"][0]["Portfolio weight"] == 60
    assert 0 <= portfolio["weighted_risk"] <= 100
    assert 0 <= portfolio["weighted_readiness"] <= 100
    assert portfolio["effective_positions"] > 1
    assert any(warning["title"] == "AAPL concentration" for warning in portfolio["warnings"])
    assert sum(item["Allocation"] for item in portfolio["sector_exposure"]) == 100


def test_portfolio_stress_scenario_returns_weighted_ranges(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    service = AnalysisService(DemoProvider(), repository)
    reports = {ticker: service.analyze(ticker) for ticker in ("AAPL", "MSFT")}
    result = analyze_stress_scenario(
        [{"ticker": "AAPL", "allocation": 60}, {"ticker": "MSFT", "allocation": 40}],
        reports, "Recession",
    )
    assert result["estimated_impact"] < 0
    assert result["lower_range"] < result["estimated_impact"] < result["upper_range"]
    assert result["covered_weight"] == 100
    assert len(result["rows"]) == 2


def test_custom_stress_scenario_applies_sector_shock_and_flags_thesis(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    report = AnalysisService(DemoProvider(), repository).analyze("AAPL")
    result = analyze_stress_scenario(
        [{"ticker": "AAPL", "allocation": 100}], {"AAPL": report}, "Custom",
        {"market_shock": -5, "rate_change_bps": 0, "inflation_change": 0,
         "oil_change": 0, "sector_shocks": {"Technology": -20}},
        [{"ticker": "AAPL", "stance": "Hold"}],
    )
    assert result["rows"][0]["Estimated impact"] <= -20
    assert result["thesis_reviews"][0]["Ticker"] == "AAPL"


def test_stress_scenario_reports_missing_research(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    report = AnalysisService(DemoProvider(), repository).analyze("AAPL")
    result = analyze_stress_scenario(
        [{"ticker": "AAPL", "allocation": 50}, {"ticker": "JPM", "allocation": 50}],
        {"AAPL": report}, "Broad market decline",
    )
    assert result["missing"] == ["JPM"]
    assert result["covered_weight"] == 50


def test_decision_center_prioritizes_quota_and_missing_research():
    result = build_decision_center(
        ["AAPL"], {}, {"AAPL": []}, [], [], [], None,
        {"quota_remaining": 0}, freshness_days=7,
    )
    assert result["counts"]["Critical"] == 1
    assert any(item["Category"] == "Research coverage" for item in result["items"])
    assert result["items"][0]["Priority"] == "Critical"


def test_decision_center_flags_invalidated_thesis_and_stress(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    report = AnalysisService(DemoProvider(), repository).analyze("AAPL")
    thesis = validate_thesis({
        "ticker": "AAPL", "stance": "Hold", "confidence": "High", "max_risk_score": 0,
    })
    stress = analyze_stress_scenario(
        [{"ticker": "AAPL", "allocation": 100}], {"AAPL": report}, "Broad market decline",
    )
    result = build_decision_center(
        ["AAPL"], {"AAPL": report}, {"AAPL": [report]}, [thesis], [],
        [{"ticker": "AAPL", "allocation": 100}], stress, {}, freshness_days=7,
    )
    assert any(item["Category"] == "Thesis" and item["Priority"] == "Critical" for item in result["items"])
    assert any(item["Category"] == "Stress exposure" for item in result["items"])


def test_decision_center_includes_unread_alerts():
    result = build_decision_center(
        [], {}, {}, [], [{"ticker": "MSFT", "severity": "High", "title": "Risk changed", "message": "Risk increased."}],
        [], None, {}, freshness_days=7,
    )
    assert result["counts"]["High"] == 1
    assert result["items"][0]["Category"] == "Alert"


def test_portfolio_exposure_reports_missing_coverage(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    aapl = AnalysisService(DemoProvider(), repository).analyze("AAPL")
    portfolio = analyze_portfolio_exposure(
        [{"Ticker": "AAPL", "Allocation": 50}, {"Ticker": "NVDA", "Allocation": 50}], {"AAPL": aapl}
    )
    assert portfolio["missing"] == ["NVDA"]
    assert portfolio["covered_weight"] == 50
    assert portfolio["posture"] == "Insufficient coverage"


def test_change_tracker_identifies_strengthening_evidence(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    previous = AnalysisService(DemoProvider(), repository).analyze("AAPL")
    current = replace(
        previous,
        report_id=(previous.report_id or 0) + 1,
        committee_score=previous.committee_score + 12,
        risk={**previous.risk, "score": previous.risk["score"] - 8},
        entry_readiness={**previous.entry_readiness, "score": previous.entry_readiness["score"] + 10},
        catalysts=previous.catalysts + ["New product cycle improved."],
    )
    change = compare_reports(current, previous)
    assert change["thesis_status"] == "Strengthening"
    assert change["thesis_score"] >= 4
    assert change["added_catalysts"] == ["New product cycle improved."]
    assert any(item["Change"] == "Committee score" for item in change["material_changes"])


def test_change_tracker_invalidates_major_reversal(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    previous = AnalysisService(DemoProvider(), repository).analyze("MSFT")
    previous = replace(previous, committee_vote="bullish")
    current = replace(previous, committee_vote="bearish", risk={**previous.risk, "score": previous.risk["score"] + 16})
    change = compare_reports(current, previous)
    assert change["thesis_status"] == "Invalidated"
    assert change["state_changes"][0]["Factor"] == "Committee vote"
    assert "invalidation threshold" in change["reasons"][0]


def test_repository_lists_report_tickers(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    service = AnalysisService(DemoProvider(), repository)
    service.analyze("MSFT")
    service.analyze("AAPL")
    service.analyze("MSFT")
    assert repository.report_tickers() == ["AAPL", "MSFT"]


def test_thesis_versions_are_preserved_and_latest_is_returned(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    first = validate_thesis({"ticker": "aapl", "stance": "Watch", "confidence": "Medium"})
    second = validate_thesis({"ticker": "AAPL", "stance": "Buy candidate", "confidence": "High"})
    first_id = repository.save_thesis(first)
    second_id = repository.save_thesis(second)
    history = repository.thesis_history("AAPL")
    assert [item["id"] for item in history] == [second_id, first_id]
    assert repository.latest_theses()[0]["stance"] == "Buy candidate"


def test_thesis_evaluation_detects_opportunity_and_invalidation(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    report = AnalysisService(DemoProvider(), repository).analyze("AAPL")
    opportunity = validate_thesis({
        "ticker": "AAPL", "stance": "Watch", "confidence": "Medium",
        "entry_low": report.company_metrics["price"] - 1,
        "entry_high": report.company_metrics["price"] + 1,
        "max_risk_score": 100,
    })
    assert evaluate_thesis(opportunity, report)["status"] == "Opportunity"
    invalidated = validate_thesis({
        "ticker": "AAPL", "stance": "Hold", "confidence": "High",
        "max_risk_score": 0,
    })
    result = evaluate_thesis(invalidated, report)
    assert result["status"] == "Invalidated"
    assert any(flag["factor"] == "Risk threshold" for flag in result["flags"])


def test_thesis_validation_rejects_reversed_entry_range():
    try:
        validate_thesis({
            "ticker": "MSFT", "stance": "Watch", "confidence": "Low",
            "entry_low": 200, "entry_high": 100,
        })
    except ValueError as exc:
        assert "lower entry price" in str(exc)
    else:
        raise AssertionError("Expected a reversed entry range to fail")


def test_scheduled_research_runs_when_due_and_records_history(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    repository.add_ticker("AAPL")
    now = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)
    scheduler = ScheduledResearchService(
        AnalysisService(DemoProvider(), repository), repository, DemoProvider(), DemoEconomicProvider(),
        DemoEconomicEventProvider(), DemoCatalystCalendarProvider(), clock=lambda: now,
    )
    scheduler.save_configuration({
        "enabled": True, "interval_hours": 24, "scope": "Watchlist", "preset": "Balanced",
        "retry_limit": 1, "scan_alerts": True,
    })
    assert scheduler.status()["due"] is True
    result = scheduler.run("Scheduled")
    assert result["status"] == "Complete"
    assert result["requested"] == 1
    assert result["analyzed"] == 1
    assert scheduler.status()["due"] is False
    assert len(repository.recent_reports("AAPL")) == 1


def test_scheduled_research_honors_retry_limit(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    repository.add_ticker("MSFT")

    class FailingAnalysis:
        def __init__(self):
            self.calls = 0

        def analyze(self, *args, **kwargs):
            self.calls += 1
            raise ValueError("simulated analysis failure")

    failing = FailingAnalysis()
    scheduler = ScheduledResearchService(
        failing, repository, DemoProvider(), DemoEconomicProvider(), DemoEconomicEventProvider(),
        DemoCatalystCalendarProvider(),
    )
    scheduler.save_configuration({
        "enabled": False, "interval_hours": 4, "scope": "Watchlist", "preset": "Growth",
        "retry_limit": 2, "scan_alerts": False,
    })
    result = scheduler.run("Manual")
    assert result["status"] == "Failed"
    assert failing.calls == 3
    assert "MSFT" in result["errors"][0]


def test_scheduler_makes_no_requests_when_daily_budget_is_too_low(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    repository.add_ticker("AAPL")

    class BudgetedProvider(DemoProvider):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def status(self):
            return {"quota_remaining": 2}

        def estimated_requests_for_analysis(self, tickers):
            return 7

        def history(self, ticker):
            self.calls += 1
            return super().history(ticker)

    provider = BudgetedProvider()
    scheduler = ScheduledResearchService(
        AnalysisService(provider, repository), repository, provider, DemoEconomicProvider(),
        DemoEconomicEventProvider(), DemoCatalystCalendarProvider(),
    )
    scheduler.save_configuration({"scope": "Watchlist", "scan_alerts": False})
    result = scheduler.run("Scheduled")
    assert result["status"] == "Failed"
    assert provider.calls == 0
    assert "No live requests were made" in result["errors"][0]


def test_schedule_validation_rejects_invalid_limits():
    try:
        validate_schedule({"interval_hours": 0, "retry_limit": 4})
    except ValueError as exc:
        assert "interval" in str(exc).lower() or "retry" in str(exc).lower()
    else:
        raise AssertionError("Expected invalid schedule limits to fail")


def test_market_readiness_accepts_complete_history_with_news_warning():
    result = run_market_readiness(DemoProvider(), "AAPL", 200)
    assert result["status"] == "Limited"
    assert result["snapshot_coverage"] >= 80
    assert result["daily_observations"] == 320
    assert all("value" not in check for check in result["checks"])


def test_market_readiness_blocks_insufficient_daily_history():
    class CompactDemoProvider(DemoProvider):
        name = "Compact test provider"

        def daily_history(self, ticker: str):
            return super().daily_history(ticker)[-100:]

    result = run_market_readiness(CompactDemoProvider(), "MSFT", 200)
    daily = next(check for check in result["checks"] if check["check"] == "Daily technical history")
    assert result["status"] == "Blocked"
    assert daily["status"] == "Blocked"
    assert "100" in daily["details"]


def test_macro_readiness_checks_coverage_and_staleness():
    result = run_macro_readiness(DemoEconomicProvider())
    assert result["status"] == "Ready"
    assert result["indicator_coverage"] == 100
    assert result["stale_indicators"] == 0


def test_live_readiness_summary_requires_keys_and_successful_checks():
    with patch.dict("os.environ", {"ALPHA_VANTAGE_API_KEY": "test", "FRED_API_KEY": "test"}, clear=False):
        environment = environment_readiness()
    market = {"status": "Ready", "checks": []}
    macro = {"status": "Ready", "checks": []}
    assert readiness_summary(environment, market, macro)["overall"] == "Ready for live mode"
    market = {"status": "Blocked", "checks": [{"status": "Blocked", "details": "Daily history is short."}]}
    summary = readiness_summary(environment, market, macro)
    assert summary["overall"] == "Not ready for full live mode"
    assert "Daily history" in summary["blockers"][0]


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


def test_latest_reports_returns_one_report_per_ticker(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    service = AnalysisService(DemoProvider(), repository)
    service.analyze("AAPL")
    newest = service.analyze("AAPL")
    msft = service.analyze("MSFT")
    latest = repository.latest_reports(["AAPL", "MSFT", "NVDA"])
    assert latest["AAPL"].report_id == newest.report_id
    assert latest["MSFT"].report_id == msft.report_id
    assert "NVDA" not in latest


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


def test_golden_cross_detection():
    history = [{"date": f"{index:04d}", "close": 200 - index * .2} for index in range(201)]
    history.extend({"date": f"{index + 201:04d}", "close": 160 + index * 1.8} for index in range(100))
    result, chart = analyze_golden_cross(history)
    assert result["status"] == "bullish"
    assert result["latest_cross"]["type"] == "golden_cross"
    assert result["sma_50"] > result["sma_200"]
    assert chart


def test_death_cross_detection():
    history = [{"date": f"{index:04d}", "close": 100 + index * .2} for index in range(201)]
    history.extend({"date": f"{index + 201:04d}", "close": 140 - index * 1.8} for index in range(100))
    result, _ = analyze_golden_cross(history)
    assert result["status"] == "bearish"
    assert result["latest_cross"]["type"] == "death_cross"


def test_golden_cross_requires_201_daily_observations():
    result, chart = analyze_golden_cross([{"date": str(index), "close": 100} for index in range(200)])
    assert result["status"] == "insufficient_history"
    assert result["required_observations"] == 201
    assert chart == []


def test_risk_score_flags_high_risk_inputs():
    stock = {
        "pe_ratio": 70, "profit_margin": -.02, "revenue_growth": -.15, "beta": 2.1,
        "price": 55, "fifty_two_week_high": 120, "fifty_two_week_low": 50,
        "sector": "Technology",
    }
    performance = {"annualized_volatility": 58, "max_drawdown": -48}
    technical = {"status": "bearish", "spread_percent": -8, "message": "Bearish technical trend."}
    macro = DemoEconomicProvider().snapshot()
    result = analyze_risk(stock, performance, technical, macro)
    assert result["score"] > 70
    assert result["severity"] in {"High", "Critical"}
    assert len(result["flags"]) >= 5


def test_risk_severity_boundaries():
    assert [severity(value) for value in (0, 30, 31, 55, 56, 75, 76, 100)] == [
        "Low", "Low", "Moderate", "Moderate", "High", "High", "Critical", "Critical"
    ]


def test_market_environment_scores_events_and_macro():
    result = analyze_market_environment(DemoEconomicEventProvider().snapshot(), DemoEconomicProvider().snapshot())
    assert 0 <= result["score"] <= 100
    assert result["label"] in {"Favorable", "Cautiously favorable", "Neutral", "Defensive", "Highly defensive"}
    assert len(result["events"]) == 4
    assert all(event["impact"] and event["expected_direction"] for event in result["events"])


def test_severe_recent_event_creates_defensive_environment():
    snapshot = DemoEconomicEventProvider().snapshot()
    snapshot["events"] = [{
        "title": "Severe systemic shock", "category": "Financial stability", "direction": -100,
        "confidence": 100, "duration": "Unknown", "affected_sectors": ["All"],
        "supporting_evidence": "Systemic stress is present.", "counterpoint": "Policy action may help.",
        "source": "Test source", "published_at": snapshot["retrieved_at"],
    }]
    result = analyze_market_environment(snapshot, DemoEconomicProvider().snapshot())
    assert result["label"] in {"Defensive", "Highly defensive"}


def test_catalyst_calendar_prioritizes_near_term_events():
    snapshot = DemoCatalystCalendarProvider().snapshot()
    nvda = assess_catalysts("NVDA", snapshot)
    aapl = assess_catalysts("AAPL", snapshot)
    assert nvda["readiness"] == "Event imminent"
    assert aapl["readiness"] == "Elevated"
    assert nvda["risk_score"] > aapl["risk_score"]
    assert nvda["events"] == sorted(nvda["events"], key=lambda event: (event["date"], -event["importance"]))


def test_global_calendar_filters_company_events_to_watchlist():
    rows = global_calendar(DemoCatalystCalendarProvider().snapshot(), ["MSFT"])
    company_events = [event for event in rows if event["scope"] == "company"]
    assert company_events
    assert all("MSFT" in event["affected"] for event in company_events)


def test_fred_calendar_uses_official_future_release_dates(tmp_path: Path):
    class Response:
        def __init__(self, release_dates):
            self.release_dates = release_dates

        def raise_for_status(self):
            return None

        def json(self):
            return {"release_dates": self.release_dates}

    def response_for_release(_url, params, timeout):
        dates = {
            50: [{"release_id": 50, "date": "2026-08-07"}, {"release_id": 50, "date": "2026-09-04"}],
            10: [{"release_id": 10, "date": "2026-08-12"}],
        }.get(params["release_id"], [])
        return Response(dates)

    provider = FredReleaseCalendarProvider(
        ProviderCache(tmp_path / "cache.db"), api_key="test", today=lambda: date(2026, 8, 11),
    )
    with patch("requests.get", side_effect=response_for_release):
        snapshot = provider.snapshot()
    assert snapshot["live"] is True
    assert snapshot["stale"] is False
    assert [(event["title"], event["date"]) for event in snapshot["events"]] == [
        ("U.S. consumer price index", "2026-08-12"),
        ("U.S. employment report", "2026-09-04"),
    ]
    assert all(event["source_live"] is True for event in snapshot["events"])


def test_demo_calendar_cannot_create_catalyst_alert(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    report = AnalysisService(DemoProvider(), repository).analyze("NVDA")
    alerts = AlertService(repository)
    alerts.save_rule("NVDA", {"enabled": ["catalyst"], "catalyst_days": 30})
    result = alerts.scan([report.ticker])
    assert result["created"] == 0
    assert repository.alerts() == []


def test_repository_archives_demo_and_past_catalyst_alerts(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    repository.add_alert({
        "ticker": "MSFT", "alert_type": "catalyst", "severity": "High",
        "title": "Old demo event", "message": "Illustrative date", "fingerprint": "old-demo-event",
        "payload": {"date": "2026-09-04", "source_live": False},
    })
    repository.add_alert({
        "ticker": "AAPL", "alert_type": "catalyst", "severity": "High",
        "title": "Past live event", "message": "Past date", "fingerprint": "past-live-event",
        "payload": {"date": "2026-08-07", "source_live": True},
    })
    assert repository.expire_invalid_catalyst_alerts(date(2026, 8, 11)) == 2
    assert repository.alerts() == []
    assert repository.unread_alert_count() == 0


def test_alpha_vantage_earnings_calendar_is_parsed_and_cached(tmp_path: Path):
    class Response:
        text = (
            "symbol,name,reportDate,fiscalDateEnding,estimate,currency\n"
            "MSFT,Microsoft Corp,2026-09-01,2026-06-30,3.25,USD\n"
            "AAPL,Apple Inc,2026-09-03,2026-06-30,,USD\n"
        )

        def raise_for_status(self):
            return None

    cache = ProviderCache(tmp_path / "cache.db")
    provider = AlphaVantageEarningsCalendarProvider(cache, api_key="test")
    with patch("requests.get", return_value=Response()) as request:
        first = provider.snapshot()
        second = provider.snapshot()
    assert request.call_count == 1
    assert first["live"] is True and second["cache_status"] == "Fresh cache"
    assert first["events"][0]["timing_status"] == "Estimated"
    assert first["events"][0]["eps_estimate"] == 3.25
    assert all(event["source_live"] is True for event in first["events"])


def test_combined_calendar_keeps_live_sources_attributed(tmp_path: Path):
    class StaticCalendar:
        def __init__(self, name, event):
            self.name, self.event = name, event

        def snapshot(self):
            return {"provider": self.name, "retrieved_at": "2026-08-11T00:00:00+00:00",
                    "live": True, "stale": False, "events": [self.event]}

    macro = {"title": "CPI", "date": "2026-08-12", "scope": "global", "affected": [], "source_live": True}
    earnings = {"title": "MSFT quarterly earnings", "date": "2026-09-01", "scope": "company",
                "affected": ["MSFT"], "source_live": True, "timing_status": "Estimated"}
    snapshot = CombinedCatalystCalendarProvider(StaticCalendar("FRED", macro), StaticCalendar("AV", earnings)).snapshot()
    assert len(snapshot["events"]) == 2
    assert snapshot["provider"] == "Official economic and earnings calendars"
    assert snapshot["live"] is True


def test_golden_cross_backtest_uses_next_session_and_costs():
    provider = DemoProvider()
    company = provider.daily_history("AAPL")
    benchmark = provider.daily_history("SPY")
    free = backtest_golden_cross(company, benchmark, 0)
    with_costs = backtest_golden_cross(company, benchmark, 25)
    assert free["status"] == "complete"
    assert free["transaction_log"]
    assert all(item["execution_date"] > item["signal_date"] for item in free["transaction_log"])
    assert with_costs["total_return"] <= free["total_return"]
    assert len(free["curve"]) == free["observations"]


def test_golden_cross_backtest_rejects_short_or_invalid_inputs():
    history = [{"date": f"2026-01-{index + 1:02d}", "close": 100 + index} for index in range(20)]
    result = backtest_golden_cross(history, history)
    assert result["status"] == "insufficient_history"
    try:
        backtest_golden_cross(history, history, -1)
    except ValueError as exc:
        assert "between 0 and 500" in str(exc)
    else:
        raise AssertionError("Expected invalid transaction costs to fail")


def test_entry_readiness_labels_strong_and_incomplete_evidence():
    strong = analyze_entry_readiness(
        85, {"score": 20, "coverage_percent": 100}, {"score": 80, "summary": "Supportive"},
        {"status": "bullish", "spread_percent": 5, "message": "Bullish"},
        {"readiness": "Clear", "summary": "Clear"},
        {"status": "complete", "total_return": 25, "buy_hold_return": 15, "max_drawdown": -10},
        {"price": 1, "pe_ratio": 20, "profit_margin": .2, "revenue_growth": .1, "beta": 1,
         "fifty_two_week_high": 2, "fifty_two_week_low": .5},
    )
    incomplete = analyze_entry_readiness(
        50, {"score": 50, "coverage_percent": 0}, {},
        {"status": "insufficient_history"}, {}, {"status": "insufficient_history"}, {},
    )
    assert strong["posture"] == "Favorable setup"
    assert strong["coverage_percent"] == 100
    assert incomplete["posture"] == "Insufficient evidence"
    assert incomplete["coverage_percent"] < 70
    assert strong["disclosure"].startswith("This is a research posture")


def test_settings_profiles_persist_and_validate(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    assert load_configuration(repository) == DEFAULT_CONFIG
    defensive = settings_profile("Defensive")
    saved = save_configuration(repository, defensive)
    assert saved["committee_preset"] == "Defensive"
    assert sum(saved["readiness_weights"].values()) == 100
    assert load_configuration(repository) == saved
    invalid = settings_profile("Balanced")
    invalid["ranking_weights"]["committee"] = 99
    try:
        validate_configuration(invalid)
    except ValueError as exc:
        assert "must total 100%" in str(exc)
    else:
        raise AssertionError("Expected invalid calibration weights to fail")


def test_custom_settings_drive_analysis_and_alert_defaults(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    custom = settings_profile("Balanced")
    custom["profile"] = "Custom"
    custom["technical"] = {"short_window": 20, "long_window": 60}
    custom["backtest"]["transaction_cost_bps"] = 35
    custom["alert_defaults"]["risk_threshold"] = 72
    custom["freshness_days"] = 11
    save_configuration(repository, custom)
    report = AnalysisService(DemoProvider(), repository).analyze("AAPL")
    assert report.technical["short_window"] == 20
    assert report.technical["long_window"] == 60
    assert report.backtest["transaction_cost_bps"] == 35
    assert report.configuration["profile"] == "Custom"
    assert AlertService(repository).rule("AAPL")["risk_threshold"] == 72


def test_watchlist_ranking_modes_and_missing_reports(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    service = AnalysisService(DemoProvider(), repository)
    reports = {ticker: service.analyze(ticker) for ticker in ("AAPL", "MSFT")}
    for mode in ("Best opportunity", "Entry readiness", "Lowest risk", "Strongest momentum"):
        ranking = rank_watchlist(["AAPL", "MSFT", "NVDA"], reports, mode)
        assert [row["Rank"] for row in ranking["rows"]] == [1, 2]
        assert ranking["missing"] == ["NVDA"]
        assert all(0 <= row["Opportunity score"] <= 100 for row in ranking["rows"])
        assert all(row["Catalyst readiness"] != "Unavailable" for row in ranking["rows"])
        assert all(row["Entry readiness"] is not None for row in ranking["rows"])


def test_watchlist_pdf_is_generated(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    report = AnalysisService(DemoProvider(), repository).analyze("GOOGL")
    pdf = render_watchlist_pdf(rank_watchlist(["GOOGL"], {"GOOGL": report}))
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 2000


def test_alert_scan_deduplicates_unchanged_conditions(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    repository.add_ticker("AAPL")
    AnalysisService(DemoProvider(), repository).analyze("AAPL")
    alerts = AlertService(repository)
    first = alerts.scan(["AAPL"])
    second = alerts.scan(["AAPL"])
    assert first["created"] >= 1
    assert second["created"] == 0
    assert repository.unread_alert_count() == first["created"]
    repository.mark_alerts_read()
    assert repository.unread_alert_count() == 0


def test_alert_rules_persist_and_changed_report_creates_alerts(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    service = AnalysisService(DemoProvider(), repository)
    original = service.analyze("MSFT")
    alerts = AlertService(repository)
    alerts.save_rule("MSFT", {
        "enabled": ["committee", "risk", "environment", "backtest", "stale"],
        "risk_threshold": 79, "confidence_change": 5, "backtest_floor": 500,
        "stale_days": 1, "catalyst_days": 7, "rank_change": 1,
    })
    changed = replace(
        original,
        created_at=(datetime.now(timezone.utc) - timedelta(days=3)).isoformat(),
        committee_vote="bullish" if original.committee_vote != "bullish" else "bearish",
        committee_confidence=original.committee_confidence - 15 if original.committee_confidence > 85 else original.committee_confidence + 15,
        risk={**original.risk, "score": 80.0, "severity": "Critical"},
        market_environment={**original.market_environment, "label": "Highly defensive"},
        report_id=None,
    )
    repository.save(changed)
    result = alerts.scan(["MSFT"])
    types = {alert["alert_type"] for alert in repository.alerts()}
    assert result["created"] >= 5
    assert {"committee", "risk", "environment", "backtest", "stale"}.issubset(types)
    assert alerts.rule("MSFT")["risk_threshold"] == 79


def test_demo_alert_and_missing_report_scan(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    alerts = AlertService(repository)
    assert alerts.simulate_demo_alert("NVDA")
    assert alerts.scan(["NVDA"])["missing"] == ["NVDA"]
    assert repository.alerts()[0]["payload"]["demo"] is True


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


def test_report_pdf_is_generated(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    report = AnalysisService(DemoProvider(), repository).analyze("GOOGL", PRESETS["Balanced"])
    pdf = render_report_pdf(report)
    assert pdf.startswith(b"%PDF-")
    assert pdf.rstrip().endswith(b"%%EOF")
    assert len(pdf) > 5000


def test_comparison_pdf_is_generated(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    comparison = ComparisonService(AnalysisService(DemoProvider(), repository), repository).compare(
        ["AAPL", "MSFT"], PRESETS["Balanced"]
    )
    pdf = render_comparison_pdf(comparison)
    assert pdf.startswith(b"%PDF-")
    assert pdf.rstrip().endswith(b"%%EOF")
    assert len(pdf) > 4000


def test_portfolio_pdf_is_generated(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    service = AnalysisService(DemoProvider(), repository)
    reports = {ticker: service.analyze(ticker) for ticker in ("AAPL", "MSFT")}
    portfolio = analyze_portfolio_exposure(
        [{"Ticker": "AAPL", "Allocation": 55}, {"Ticker": "MSFT", "Allocation": 45}], reports
    )
    pdf = render_portfolio_pdf(portfolio)
    assert pdf.startswith(b"%PDF-")
    assert pdf.rstrip().endswith(b"%%EOF")
    assert len(pdf) > 3000


def test_change_tracking_pdf_is_generated(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    previous = AnalysisService(DemoProvider(), repository).analyze("NVDA")
    current = replace(
        previous,
        committee_score=previous.committee_score + 8,
        entry_readiness={**previous.entry_readiness, "score": previous.entry_readiness["score"] + 7},
    )
    pdf = render_change_pdf(compare_reports(current, previous))
    assert pdf.startswith(b"%PDF-")
    assert pdf.rstrip().endswith(b"%%EOF")
    assert len(pdf) > 3000


class _CountingMarketProvider(MarketDataProvider):
    name = "Counting provider"

    def __init__(self, failures: int = 0, error_message: str = "request failed: temporary connection"):
        self.calls = 0
        self.failures = failures
        self.error_message = error_message

    def search(self, query: str):
        return [{"symbol": query.upper(), "name": query}]

    def snapshot(self, ticker: str):
        self.calls += 1
        if self.calls <= self.failures:
            raise ProviderError(self.error_message)
        return {"symbol": ticker, "price": 100 + self.calls}

    def news(self, ticker: str):
        return []

    def history(self, ticker: str):
        return [{"date": "2026-01-01", "close": 100}, {"date": "2026-02-01", "close": 101}]


def test_provider_cache_reuses_and_persists_responses(tmp_path: Path):
    cache = ProviderCache(tmp_path / "cache.db")
    delegate = _CountingMarketProvider()
    provider = CachedMarketDataProvider(delegate, cache)
    first = provider.snapshot("aapl")
    second = provider.snapshot("AAPL")
    restarted_provider = CachedMarketDataProvider(_CountingMarketProvider(), ProviderCache(tmp_path / "cache.db"))
    third = restarted_provider.snapshot("AAPL")
    assert first == second == third
    assert delegate.calls == 1
    assert provider.status()["cache_hits"] == 1
    assert restarted_provider.status()["cache_hits"] == 1


def test_provider_daily_budget_persists_and_preserves_reserve(tmp_path: Path):
    cache = ProviderCache(tmp_path / "cache.db", clock=lambda: 1_786_406_400.0)
    assert [cache.claim_request("alpha_vantage", 5, 2) for _ in range(4)] == [True, True, True, False]
    restarted = ProviderCache(tmp_path / "cache.db", clock=lambda: 1_786_406_400.0)
    status = restarted.usage_status("alpha_vantage", 5, 2)
    assert status["used"] == 3
    assert status["remaining"] == 0
    assert status["reserve"] == 2


def test_live_provider_uses_clearly_labeled_demo_fallback(tmp_path: Path):
    failing = _CountingMarketProvider(failures=99, error_message="429 rate limit reached")
    primary = CachedMarketDataProvider(failing, ProviderCache(tmp_path / "cache.db"), max_attempts=1)
    provider = FallbackMarketDataProvider(primary, DemoProvider())
    snapshot = provider.snapshot("AAPL")
    assert snapshot["source"].startswith("Demo")
    assert "demo fallback enabled" in provider.name
    assert provider.status()["demo_fallbacks"] == 1


def test_analysis_request_estimate_accounts_for_cached_operations(tmp_path: Path):
    provider = CachedMarketDataProvider(DemoProvider(), ProviderCache(tmp_path / "cache.db"))
    assert provider.estimated_requests_for_analysis(["AAPL", "MSFT"]) == 12
    provider.snapshot("AAPL")
    assert provider.estimated_requests_for_analysis(["AAPL", "MSFT"]) == 10


def test_hybrid_estimate_counts_only_alpha_vantage_requests(tmp_path: Path):
    class FakeAlpha(DemoProvider):
        def fundamentals(self, ticker):
            return super().snapshot(ticker)

        def usage_status(self):
            return {"daily_limit": 25, "reserve": 2, "usable_limit": 23, "used": 0, "remaining": 23}

    hybrid = HybridMarketDataProvider(FakeAlpha(), DemoProvider())
    provider = CachedMarketDataProvider(hybrid, ProviderCache(tmp_path / "cache.db"))
    assert provider.estimated_requests_for_analysis(["AAPL", "MSFT"]) == 4


def test_expired_cache_is_used_when_provider_fails(tmp_path: Path):
    now = [100.0]
    cache = ProviderCache(tmp_path / "cache.db", clock=lambda: now[0])
    delegate = _CountingMarketProvider()
    provider = CachedMarketDataProvider(delegate, cache, ttls={"search": 1, "snapshot": 1, "news": 1, "history": 1}, max_attempts=1)
    expected = provider.snapshot("MSFT")
    now[0] += 2
    delegate.failures = 99
    assert provider.snapshot("MSFT") == expected
    assert provider.status()["stale_fallbacks"] == 1


def test_temporary_failures_use_bounded_retries(tmp_path: Path):
    waits = []
    delegate = _CountingMarketProvider(failures=2)
    provider = CachedMarketDataProvider(delegate, ProviderCache(tmp_path / "cache.db"), max_attempts=3, sleeper=waits.append)
    assert provider.snapshot("NVDA")["symbol"] == "NVDA"
    assert delegate.calls == 3
    assert waits == [0.25, 0.75]
    assert provider.status()["retries"] == 2


def test_rate_limits_do_not_retry_without_stale_data(tmp_path: Path):
    delegate = _CountingMarketProvider(failures=5, error_message="429 rate limit reached")
    provider = CachedMarketDataProvider(delegate, ProviderCache(tmp_path / "cache.db"), max_attempts=3, sleeper=lambda _: None)
    try:
        provider.snapshot("GOOGL")
    except ProviderError as exc:
        assert "rate limit" in str(exc)
    else:
        raise AssertionError("Expected a rate-limit failure")
    assert delegate.calls == 1
    assert provider.status()["retries"] == 0


def test_concurrent_duplicate_requests_are_coalesced(tmp_path: Path):
    delegate = _CountingMarketProvider()
    original_snapshot = delegate.snapshot

    def slow_snapshot(ticker: str):
        time.sleep(0.05)
        return original_snapshot(ticker)

    delegate.snapshot = slow_snapshot
    provider = CachedMarketDataProvider(delegate, ProviderCache(tmp_path / "cache.db"))
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(provider.snapshot, ["AAPL"] * 4))
    assert all(result == results[0] for result in results)
    assert delegate.calls == 1
    assert provider.status()["cache_hits"] == 3


def test_valuation_builds_ordered_scenarios_and_sensitivity(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    report = AnalysisService(DemoProvider(), repository).analyze("AAPL")
    valuation = build_valuation(report)
    assert valuation["bear_value"] < valuation["base_value"] < valuation["bull_value"]
    assert len(valuation["scenarios"]) == 3
    assert len(valuation["sensitivity"]) == 9
    assert valuation["current_price"] == report.company_metrics["price"]
    assert valuation["data_coverage"] >= 80


def test_valuation_rejects_unordered_multiples(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    report = AnalysisService(DemoProvider(), repository).analyze("MSFT")
    assumptions = suggested_assumptions(report)
    assumptions.update({"bear_multiple": 30, "base_multiple": 20, "bull_multiple": 10})
    try:
        build_valuation(report, assumptions)
    except ValueError as exc:
        assert "ordered" in str(exc)
    else:
        raise AssertionError("Expected unordered valuation multiples to fail")


def test_valuation_versions_are_persisted(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    report = AnalysisService(DemoProvider(), repository).analyze("GOOGL")
    first = build_valuation(report)
    second = build_valuation(report, {"base_multiple": 25, "bear_multiple": 18, "bull_multiple": 32})
    first_id = repository.save_valuation(first)
    second_id = repository.save_valuation(second)
    history = repository.valuation_history("googl")
    assert [item["id"] for item in history] == [second_id, first_id]
    assert repository.latest_valuations()[0]["base_value"] == second["base_value"]


def test_decision_center_flags_extended_saved_valuation():
    result = build_decision_center(
        [], {}, {}, [], [], [], None, {}, valuations=[{
            "ticker": "NVDA", "status": "Above base value", "margin_of_safety": -25,
            "entry_low": 90, "entry_high": 110,
        }],
    )
    item = next(item for item in result["items"] if item["Category"] == "Valuation")
    assert item["Priority"] == "High"
    assert item["Ticker"] == "NVDA"


def test_beginner_guide_requires_valuation_for_buy_candidate(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    report = AnalysisService(DemoProvider(), repository).analyze("AAPL")
    constructive = replace(
        report, committee_score=80, committee_vote="bullish",
        risk={**report.risk, "score": 25},
        entry_readiness={**report.entry_readiness, "score": 85},
        technical={**report.technical, "status": "bullish"},
    )
    without_valuation = build_beginner_guidance(
        ["AAPL"], {"AAPL": constructive}, [], [], [], [], freshness_days=7,
    )[0]
    with_valuation = build_beginner_guidance(
        ["AAPL"], {"AAPL": constructive}, [], [], [], [{
            "ticker": "AAPL", "status": "Within research entry range", "margin_of_safety": 20,
        }], freshness_days=7,
    )[0]
    assert without_valuation["Beginner view"] == "Watch"
    assert with_valuation["Beginner view"] == "Buy candidate"


def test_beginner_guide_marks_owned_high_risk_position_for_sell_review(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    report = AnalysisService(DemoProvider(), repository).analyze("MSFT")
    high_risk = replace(report, risk={**report.risk, "score": 82})
    guidance = build_beginner_guidance(
        ["MSFT"], {"MSFT": high_risk}, [], [], [{"ticker": "MSFT", "allocation": 10}], [],
    )[0]
    assert guidance["Beginner view"] == "Sell / reduce review"
    assert "Risk score is elevated" in guidance["What could go wrong"]


def test_beginner_guide_requests_research_when_report_is_missing():
    guidance = build_beginner_guidance(["PLTR"], {}, [], [], [], [])[0]
    assert guidance["Beginner view"] == "Research first"
    assert guidance["Confidence"] == "Low"


def test_financial_health_versions_are_persisted(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    first_id = repository.save_financial_health(
        {"ticker": "aapl", "score": 40, "posture": "Weakening", "coverage": 80}
    )
    second_id = repository.save_financial_health(
        {"ticker": "AAPL", "score": 75, "posture": "Strong", "coverage": 90}
    )
    history = repository.financial_health_history("AAPL")
    assert [item["id"] for item in history] == [second_id, first_id]
    assert repository.latest_financial_health()[0]["score"] == 75


def test_thesis_evaluation_uses_severe_sec_deterioration(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    report = AnalysisService(DemoProvider(), repository).analyze("AAPL")
    thesis = validate_thesis({
        "ticker": "AAPL", "stance": "Hold", "confidence": "High", "max_risk_score": 100,
    })
    result = evaluate_thesis(thesis, report, financial_health={"score": 30, "posture": "Weakening"})
    assert result["status"] == "Invalidated"
    assert any(flag["factor"] == "Financial health" for flag in result["flags"])


def test_financial_health_changes_suggested_valuation_multiple(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    report = AnalysisService(DemoProvider(), repository).analyze("AAPL")
    weak = suggested_assumptions(report, {"score": 20})
    strong = suggested_assumptions(report, {"score": 80})
    assert weak["base_multiple"] < strong["base_multiple"]
    valuation = build_valuation(report, financial_health={"score": 20})
    assert valuation["financial_health_adjustment"] == -3


def test_decision_center_flags_weak_sec_health_and_updates_beginner_view(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    report = AnalysisService(DemoProvider(), repository).analyze("AAPL")
    result = build_decision_center(
        ["AAPL"], {"AAPL": report}, {"AAPL": [report]}, [], [], [], None, {},
        financial_health=[{"ticker": "AAPL", "score": 30, "posture": "Weakening", "coverage": 90}],
    )
    assert any(
        item["Category"] == "Financial health" and item["Priority"] == "High"
        for item in result["items"]
    )
    assert result["beginner_guidance"][0]["Beginner view"] == "Avoid / review"


def test_comparison_surfaces_saved_sec_health(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    repository.save_financial_health(
        {"ticker": "AAPL", "score": 72, "posture": "Strong", "coverage": 90}
    )
    comparison = ComparisonService(AnalysisService(DemoProvider(), repository), repository).compare(
        ["AAPL", "MSFT"], PRESETS["Balanced"],
    )
    aapl = next(row for row in comparison["summary"] if row["Ticker"] == "AAPL")
    msft = next(row for row in comparison["summary"] if row["Ticker"] == "MSFT")
    assert aapl["SEC health score"] == 72
    assert msft["SEC health posture"] == "Not analyzed"


def _sec_snapshot(ticker: str, accession: str, current_revenue: float = 120.0) -> dict:
    def fact(values, form="10-K", frames=None):
        entries = []
        for index, (year, value) in enumerate(values):
            item = {
                "form": form, "fy": year, "fp": "FY" if form == "10-K" else f"Q{index + 1}",
                "val": value, "filed": f"{year + 1}-02-01", "accn": accession,
            }
            if frames:
                item["frame"] = frames[index]
            entries.append(item)
        return {"units": {"USD": entries}}

    return {
        "ticker": ticker, "company": f"{ticker} Company", "cik": "0000000001",
        "provider": "SEC EDGAR company facts", "retrieved_at": "2026-08-11T00:00:00+00:00",
        "cache_status": "Fresh live response", "facts": {"us-gaap": {
            "Revenues": fact([(2023, 100.0), (2024, current_revenue)]),
            "NetIncomeLoss": fact([(2023, 10.0), (2024, 15.0)]),
            "NetCashProvidedByUsedInOperatingActivities": fact([(2023, 20.0), (2024, 30.0)]),
            "PaymentsToAcquirePropertyPlantAndEquipment": fact([(2023, 5.0), (2024, 6.0)]),
            "Assets": fact([(2025, 130.0), (2025, 135.0)], "10-Q", ["CY2025Q1I", "CY2025Q2I"]),
        }},
    }


def test_financial_health_includes_quarters_and_latest_filing():
    result = analyze_financial_health(_sec_snapshot("AAPL", "0001-25-000001"))
    assert [row["Quarter"] for row in result["quarterly_rows"]] == ["CY2025Q1", "CY2025Q2"]
    assert result["latest_filing"]["accession"] == "0001-25-000001"


def test_sec_monitor_skips_same_filing_and_saves_checks(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")

    class Provider:
        def company_facts(self, ticker):
            return _sec_snapshot(ticker, "0001-25-000001")

    service = SecMonitorService(Provider(), repository)
    first = service.refresh(["AAPL"])
    second = service.refresh(["AAPL"])
    assert first["saved"] == 1
    assert second["saved"] == 0 and second["unchanged"] == 1
    assert len(repository.financial_health_history("AAPL")) == 1
    assert repository.latest_sec_monitor_checks()[0]["Status"] == "Current"


def test_sec_monitor_alerts_on_material_score_change(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    healthy = analyze_financial_health(_sec_snapshot("AAPL", "old", 120.0))
    healthy["score"] = 80
    repository.save_financial_health(healthy)

    class Provider:
        def company_facts(self, ticker):
            return _sec_snapshot(ticker, "new", 60.0)

    with patch("core.services.sec_monitor_service.analyze_financial_health") as analyzer:
        weakened = analyze_financial_health(_sec_snapshot("AAPL", "new", 60.0))
        weakened["score"] = 30
        weakened["posture"] = "Weakening"
        analyzer.return_value = weakened
        result = SecMonitorService(Provider(), repository).refresh(["AAPL"])
    assert result["alerts_created"] == 1
    alert = repository.alerts()[0]
    assert alert["alert_type"] == "financial_health"
    assert alert["severity"] == "High"


def test_guided_workflow_identifies_next_missing_evidence(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    report = AnalysisService(DemoProvider(), repository).analyze("AAPL")
    workflow = build_company_workflow(
        "AAPL", ["AAPL"], report, None, None,
        {"ticker": "AAPL", "score": 70}, [], 7,
    )
    assert workflow["ready"] == 4
    assert workflow["total"] == 6
    assert workflow["next_step"] == "Build and save a valuation scenario."
    assert next(row for row in workflow["checks"] if row["Evidence"] == "Valuation")["Status"] == "Missing"


def test_guided_workflow_surfaces_serious_alerts():
    workflow = build_company_workflow(
        "MSFT", ["MSFT"], None, None, None, None,
        [{"ticker": "MSFT", "severity": "High"}], 7,
    )
    warning = next(row for row in workflow["checks"] if row["Evidence"] == "Warnings")
    assert warning["Status"] == "Review"
    assert "Alerts" in warning["Next step"]


def test_setup_status_distinguishes_demo_and_configured_services():
    rows = build_setup_status("Demo data", "FRED", "FRED calendar", True, True)
    assert rows[0]["Status"] == "Demo / setup needed"
    assert all(row["Status"] == "Live" for row in rows[1:])


def test_position_sizing_uses_smaller_risk_and_concentration_limit():
    plan = build_position_plan(
        "AAPL", 100000, 100, 90, risk_percent=1, max_allocation=10,
    )
    assert plan["risk_limited_shares"] == 100
    assert plan["allocation_limited_shares"] == 100
    assert plan["suggested_shares"] == 100
    assert plan["loss_at_invalidation"] == 1000
    assert plan["portfolio_allocation"] == 10


def test_position_sizing_reduces_limit_for_risk_and_financial_health():
    plan = build_position_plan(
        "NVDA", 100000, 100, 80, risk_percent=5, max_allocation=20,
        risk_score=75, financial_health_score=30, readiness_score=40,
    )
    assert plan["adjusted_max_allocation"] == 3.75
    assert plan["suggested_shares"] == 37
    assert len(plan["modifiers"]) == 3
    assert plan["limiting_factor"] == "Concentration limit"


def test_position_sizing_rejects_invalidation_above_entry():
    try:
        build_position_plan("MSFT", 50000, 100, 105, 1, 10)
    except ValueError as exc:
        assert "must be below" in str(exc)
    else:
        raise AssertionError("Expected invalidation above entry to fail")


def test_position_sizing_versions_are_saved(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    first = build_position_plan("AAPL", 100000, 100, 90, 1, 10, preset="Balanced")
    second = build_position_plan("AAPL", 100000, 100, 80, 1, 10, preset="Balanced")
    first_id = repository.save_position_plan(first)
    second_id = repository.save_position_plan(second)
    history = repository.position_plan_history("AAPL")
    assert [item["id"] for item in history] == [second_id, first_id]


def test_decision_packet_combines_saved_evidence(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    report = AnalysisService(DemoProvider(), repository).analyze("AAPL")
    workflow = build_company_workflow(
        "AAPL", ["AAPL"], report, {"ticker": "AAPL", "status": "Below base value"},
        None, {"ticker": "AAPL", "score": 72, "posture": "Strong"}, [], 7,
    )
    guidance = {
        "Ticker": "AAPL", "Beginner view": "Watch", "Confidence": "Moderate", "Score": 61,
        "Plain-language summary": "AAPL evidence is mixed.", "What supports it": "Strong SEC health",
        "What could go wrong": "No thesis is saved", "Suggested next step": "Save a thesis.",
    }
    sizing = build_position_plan("AAPL", 100000, 100, 90, 1, 10, preset="Balanced")
    packet = build_decision_packet(
        "AAPL", report, guidance, workflow,
        {"ticker": "AAPL", "status": "Below base value", "margin_of_safety": 10, "base_value": 110},
        None, {"ticker": "AAPL", "score": 72, "posture": "Strong", "signals": []},
        sizing, [{"ticker": "AAPL", "severity": "High", "title": "Review", "message": "Risk changed"}],
    )
    assert packet["committee"]["vote"] == report.committee_vote.title()
    assert packet["financial_health"]["score"] == 72
    assert packet["position_plan"]["suggested_shares"] == 100
    assert packet["alerts"][0]["title"] == "Review"
    assert "Personal thesis" in packet["missing_evidence"]


def test_decision_packet_pdf_contains_major_sections(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    report = AnalysisService(DemoProvider(), repository).analyze("MSFT")
    workflow = build_company_workflow("MSFT", ["MSFT"], report, None, None, None, [], 7)
    packet = build_decision_packet("MSFT", report, None, workflow, None, None, None, None, [])
    pdf = render_decision_packet_pdf(packet)
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 5000


def test_evidence_trust_distinguishes_demo_live_and_blocked(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    report = AnalysisService(DemoProvider(), repository).analyze("AAPL")
    demo = assess_evidence_trust(report)
    assert demo["status"] == "Demo"
    assert demo["buy_allowed"] is False

    live = replace(
        report, provider="Alpha Vantage",
        macro={**report.macro, "provider": "FRED", "stale": False, "observed_at": report.created_at},
        catalyst_calendar={**report.catalyst_calendar, "provider": "Live calendar", "live": True,
                           "stale": False, "retrieved_at": report.created_at},
    )
    live_trust = assess_evidence_trust(
        live, {"provider": "SEC EDGAR", "retrieved_at": report.created_at},
    )
    assert live_trust["status"] == "Live"
    assert live_trust["score"] == 100
    assert live_trust["buy_allowed"] is True

    blocked = assess_evidence_trust(replace(live, technical={"status": "insufficient_history"}))
    assert blocked["status"] == "Blocked"


def test_evidence_trust_caps_beginner_label_and_builds_alert(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    report = AnalysisService(DemoProvider(), repository).analyze("AAPL")
    trust = assess_evidence_trust(report)
    guidance = build_beginner_guidance(
        ["AAPL"], {"AAPL": replace(
            report, committee_score=80, entry_readiness={**report.entry_readiness, "score": 80},
            risk={**report.risk, "score": 20}, technical={**report.technical, "status": "bullish"},
        )}, [], [], [], [{"ticker": "AAPL", "status": "Below base value", "margin_of_safety": 20}],
        evidence_trust={"AAPL": trust},
    )[0]
    assert guidance["Beginner view"] != "Buy candidate"
    assert guidance["Confidence"] == "Low"
    alert = build_trust_alert("AAPL", trust, report.report_id)
    assert alert["alert_type"] == "evidence_trust"
    assert alert["severity"] == "Moderate"


def test_decision_packet_includes_evidence_watermark(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    report = AnalysisService(DemoProvider(), repository).analyze("MSFT")
    workflow = build_company_workflow("MSFT", ["MSFT"], report, None, None, None, [], 7)
    trust = assess_evidence_trust(report)
    packet = build_decision_packet("MSFT", report, None, workflow, None, None, None, None, [], trust)
    assert packet["data_watermark"].startswith("DEMO EVIDENCE")
    assert render_decision_packet_pdf(packet).startswith(b"%PDF")


def test_portfolio_action_plan_prioritizes_trust_concentration_and_add_review():
    portfolio = {
        "posture": "Elevated exposure", "weighted_risk": 54, "weighted_beta": 1.1,
        "effective_positions": 2.4, "warnings": [], "sector_exposure": [],
        "rows": [
            {"Ticker": "AAPL", "Portfolio weight": 40, "Risk score": 45, "Sector": "Technology", "Freshness": "Current"},
            {"Ticker": "MSFT", "Portfolio weight": 20, "Risk score": 35, "Sector": "Technology", "Freshness": "Current"},
            {"Ticker": "PLTR", "Portfolio weight": 10, "Risk score": 55, "Sector": "Technology", "Freshness": "Current"},
        ],
    }
    guidance = [
        {"Ticker": "AAPL", "Beginner view": "Hold", "Suggested next step": "Monitor."},
        {"Ticker": "MSFT", "Beginner view": "Buy candidate", "Suggested next step": "Review size."},
        {"Ticker": "PLTR", "Beginner view": "Watch", "Suggested next step": "Wait."},
    ]
    trust = {
        "AAPL": {"status": "Live", "score": 95, "buy_allowed": True},
        "MSFT": {"status": "Live", "score": 92, "buy_allowed": True},
        "PLTR": {"status": "Stale", "score": 42, "buy_allowed": False, "summary": "Critical evidence is stale."},
    }
    plan = build_portfolio_action_plan(
        portfolio, guidance, trust,
        {"AAPL": {"portfolio_allocation": 25}, "MSFT": {"portfolio_allocation": 30}},
    )
    actions = {row["Ticker"]: row for row in plan["rows"]}
    assert actions["AAPL"]["Action review"] == "Trim-size review"
    assert actions["MSFT"]["Action review"] == "Add-size review"
    assert actions["PLTR"]["Action review"] == "Refresh evidence"
    assert plan["counts"]["Do now"] == 2


def test_portfolio_action_plan_pdf_is_generated():
    plan = build_portfolio_action_plan(
        {"posture": "Balanced watch", "weighted_risk": 45, "weighted_beta": 1.0,
         "effective_positions": 1, "warnings": [], "sector_exposure": [],
         "rows": [{"Ticker": "AAPL", "Portfolio weight": 100, "Risk score": 45,
                   "Sector": "Technology", "Freshness": "Current"}]},
        [{"Ticker": "AAPL", "Beginner view": "Hold", "Suggested next step": "Monitor."}],
        {"AAPL": {"status": "Live", "score": 95, "buy_allowed": True}},
    )
    pdf = render_portfolio_action_plan_pdf(plan)
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 3000


def test_decision_snapshot_is_immutable_per_report(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    report = AnalysisService(DemoProvider(), repository).analyze("AAPL")
    snapshot = build_label_snapshot(
        report, {"Beginner view": "Buy candidate", "Confidence": "High", "Score": 70},
        {"status": "Live", "score": 95}, 500,
    )
    first = repository.save_decision_snapshot(snapshot)
    second = repository.save_decision_snapshot({**snapshot, "label": "Avoid / review"})
    assert first is not None
    assert second is None
    assert repository.decision_snapshots()[0]["label"] == "Buy candidate"


def test_decision_accuracy_evaluates_horizons_without_lookahead():
    snapshot = {
        "ticker": "AAPL", "report_id": 1, "captured_at": "2025-01-02T12:00:00+00:00",
        "data_as_of": "2025-01-02T12:00:00+00:00", "label": "Buy candidate", "confidence": "High",
        "trust_status": "Live", "trust_score": 95, "market_regime": "Constructive",
        "start_price": 100, "benchmark_start": 100, "outcomes": {},
    }
    asset = [{"date": "2025-01-09", "close": 110}, {"date": "2025-02-03", "close": 120}]
    benchmark = [{"date": "2025-01-09", "close": 105}, {"date": "2025-02-03", "close": 110}]
    evaluated = evaluate_snapshot(snapshot, asset, benchmark, as_of=date(2025, 1, 15))
    assert evaluated["outcomes"]["7"]["result"] == "Success"
    assert evaluated["outcomes"]["7"]["max_drawdown"] == 0
    assert "30" not in evaluated["outcomes"]
    summary = summarize_accuracy([evaluated], 7)
    assert summary["win_rate"] == 100
    assert summary["capacity"] == "Insufficient"


def test_cautious_labels_and_informational_labels_do_not_distort_win_rate():
    base = {
        "ticker": "AAPL", "captured_at": "2025-01-01", "confidence": "Moderate",
        "trust_status": "Live", "market_regime": "Neutral",
    }
    snapshots = [
        {**base, "label": "Avoid / review", "outcomes": {"30": {"company_return": -5, "benchmark_return": 2, "relative_return": -7, "result": "Success"}}},
        {**base, "label": "Hold", "outcomes": {"30": {"company_return": 4, "benchmark_return": 2, "relative_return": 2, "result": "Informational"}}},
    ]
    summary = summarize_accuracy(snapshots, 30)
    assert summary["completed_directional"] == 1
    assert summary["win_rate"] == 100


def test_accuracy_report_pdf_is_generated():
    summary = summarize_accuracy([{
        "ticker": "AAPL", "captured_at": "2025-01-01", "label": "Buy candidate",
        "confidence": "High", "trust_status": "Live", "market_regime": "Constructive",
        "start_price": 100, "outcomes": {"30": {"company_return": 8, "benchmark_return": 3,
                                                   "relative_return": 5, "result": "Success"}},
    }], 30)
    pdf = render_accuracy_report_pdf(summary)
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 3000


def test_opportunity_discovery_scores_and_ranks_outside_radar():
    provider = DemoProvider()
    aapl = score_candidate(provider.snapshot("AAPL"), provider.daily_history("AAPL"), provider.name)
    msft = score_candidate(provider.snapshot("MSFT"), provider.daily_history("MSFT"), provider.name)
    result = build_discovery_result([aapl, msft], [], {"AAPL"})
    assert result["rows"][0]["Rank"] == 1
    assert result["outside_radar"] == 1
    assert next(row for row in result["rows"] if row["Ticker"] == "AAPL")["On radar"] is True
    assert all(0 <= row["Discovery score"] <= 100 for row in result["rows"])
    assert all(row["Data status"] == "Demo" for row in result["rows"])


def test_discovery_run_is_persisted(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    result = build_discovery_result([], [{"Ticker": "XYZ", "Error": "Unavailable"}], set())
    run_id = repository.save_discovery_run(result)
    saved = repository.latest_discovery_run()
    assert saved["id"] == run_id
    assert saved["failures"][0]["Ticker"] == "XYZ"


def test_discovery_rejects_short_price_history():
    try:
        score_candidate(DemoProvider().snapshot("AAPL"), [{"date": "2026-01-01", "close": 100}], "Live")
    except ValueError as exc:
        assert "50 daily" in str(exc)
    else:
        raise AssertionError("Expected short history to fail")


def test_discovery_pdf_is_generated():
    provider = DemoProvider()
    result = build_discovery_result([
        score_candidate(provider.snapshot("AAPL"), provider.daily_history("AAPL"), provider.name),
        score_candidate(provider.snapshot("MSFT"), provider.daily_history("MSFT"), provider.name),
    ], [], set())
    pdf = render_discovery_pdf(result)
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 3000


def test_market_discovery_excludes_radar_and_balances_sources():
    movers = {"rows": [
        {"ticker": "AAPL", "group": "Most active", "price": 200, "volume": 50_000_000},
        {"ticker": "NEW1", "group": "Most active", "price": 30, "volume": 20_000_000},
        {"ticker": "NEW2", "group": "Top gainer", "price": 40, "volume": 3_000_000},
        {"ticker": "NEW3", "group": "Top loser", "price": 25, "volume": 2_000_000},
        {"ticker": "PENNY", "group": "Top gainer", "price": 1, "volume": 80_000_000},
    ]}
    selected = select_market_candidates(movers, {"AAPL"}, 3)
    assert [item["ticker"] for item in selected] == ["NEW1", "NEW2", "NEW3"]


def test_demo_provider_supplies_automatic_market_candidates():
    pulse = DemoProvider().market_movers()
    assert pulse["last_updated"]
    assert len(pulse["rows"]) == 6
    assert {item["group"] for item in pulse["rows"]} == {"Top gainer", "Most active", "Top loser"}


def test_discovery_monitor_detects_changes_and_builds_alerts():
    previous = {"id": 7, "rows": [
        {"Ticker": "OLD", "Rank": 1, "Discovery score": 70, "Research label": "Worth watching"},
        {"Ticker": "MOVE", "Rank": 4, "Discovery score": 55, "Research label": "Price-only lead"},
    ]}
    current = {"rows": [
        {"Ticker": "MOVE", "Rank": 1, "Discovery score": 68, "Research label": "SEC-supported lead"},
        {"Ticker": "NEW", "Rank": 2, "Discovery score": 60, "Research label": "SEC-supported lead"},
    ]}
    monitor = compare_discovery_runs(previous, current)
    assert monitor["new_candidates"] == 1
    assert monitor["upgrades"] == 1
    assert monitor["removed"] == 1
    alerts = discovery_alerts(monitor, 8)
    assert {item["ticker"] for item in alerts} == {"MOVE", "NEW"}
    assert all(item["alert_type"] == "discovery" for item in alerts)


def test_discovery_history_is_versioned(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    repository.save_discovery_run({"rows": [{"Ticker": "FIRST"}]})
    repository.save_discovery_run({"rows": [{"Ticker": "SECOND"}]})
    history = repository.discovery_runs()
    assert [item["rows"][0]["Ticker"] for item in history] == ["SECOND", "FIRST"]


def test_daily_discovery_scheduler_runs_once_when_due(tmp_path: Path):
    class Scanner:
        def __init__(self):
            self.calls = 0

        def run(self, limit):
            self.calls += 1
            return {"rows": [{"Ticker": "NEW"}], "failures": [], "alerts_created": 2}

    repository = ReportRepository(tmp_path / "atlas.db")
    scanner = Scanner()
    now = datetime(2026, 8, 12, 23, 0, tzinfo=timezone.utc)
    scheduler = ScheduledDiscoveryService(scanner, repository, clock=lambda: now)
    scheduler.save_configuration({
        "enabled": True, "hour_et": 18, "minute_et": 15,
        "weekdays_only": True, "candidate_limit": 5,
    })
    assert scheduler.status()["due"] is True
    result = scheduler.run("Test")
    assert result["status"] == "Complete"
    assert result["candidates"] == 1
    assert result["alerts_created"] == 2
    assert scanner.calls == 1
    assert scheduler.status()["due"] is False
    assert scheduler.run("Test")["status"] == "Not due"
    assert scanner.calls == 1


def test_daily_discovery_scheduler_waits_until_configured_time(tmp_path: Path):
    repository = ReportRepository(tmp_path / "atlas.db")
    now = datetime(2026, 8, 12, 20, 0, tzinfo=timezone.utc)
    scheduler = ScheduledDiscoveryService(None, repository, clock=lambda: now)
    scheduler.save_configuration({
        "enabled": True, "hour_et": 18, "minute_et": 15,
        "weekdays_only": True, "candidate_limit": 5,
    })
    status = scheduler.status()
    assert status["due"] is False
    assert status["next_run"].startswith("2026-08-12T22:15:00")


def test_provider_health_reports_ready_without_live_calls():
    result = build_provider_health(
        {"market_mode": "hybrid", "alpha_vantage_key": True, "tiingo_key": True, "fred_key": True},
        {"last_source": "Fresh cache", "last_age_seconds": 60, "quota_remaining": 10,
         "quota_used": 5, "quota_usable_limit": 23},
        {"last_source": "Fresh cache", "last_age_seconds": 120},
        "Official economic and earnings calendars",
        {"status": "Ready", "checks": []}, {"status": "Ready", "checks": []},
        {"configuration": {"enabled": True}, "last_run": {"status": "Complete", "errors": []},
         "next_run": "2026-08-13T22:15:00+00:00"},
        True, 12, now=datetime(2026, 8, 12, tzinfo=timezone.utc),
    )
    assert result["overall"] == "Ready"
    assert result["ready"] == 5
    assert result["failures"] == []


def test_provider_health_explains_missing_configuration_and_failures():
    result = build_provider_health(
        {"market_mode": "hybrid", "alpha_vantage_key": False, "tiingo_key": True, "fred_key": False},
        {"last_source": "No requests yet", "last_age_seconds": None},
        {"last_source": "No requests yet", "last_age_seconds": None}, "Demo calendar",
        {"status": "Blocked", "tested_at": "2026-08-12T00:00:00+00:00",
         "checks": [{"check": "Quote", "status": "Blocked", "details": "Quota exhausted"}]},
        None, {"configuration": {"enabled": False}, "last_run": None, "next_run": None},
        False, 0, now=datetime(2026, 8, 12, tzinfo=timezone.utc),
    )
    assert result["overall"] == "Action required"
    assert result["action_required"] >= 2
    assert result["failures"][0]["Details"] == "Quota exhausted"
