from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import time
from unittest.mock import patch

from core.providers.demo_provider import DemoProvider
from core.providers.market_provider import AlphaVantageProvider, ProviderError
from core.providers.economic_provider import DemoEconomicProvider, FredProvider
from core.providers.cached_provider import CachedMarketDataProvider
from core.providers.market_provider import MarketDataProvider
from core.models.research import AgentAssessment
from core.services.analysis_service import AnalysisService
from core.services.report_repository import ReportRepository
from core.services.performance_service import analyze_performance
from core.services.technical_service import analyze_golden_cross
from core.services.risk_service import analyze_risk, severity
from core.services.market_regime_service import analyze_market_environment
from core.providers.event_provider import DemoEconomicEventProvider
from core.providers.calendar_provider import DemoCatalystCalendarProvider
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
from core.services.pdf_service import render_change_pdf, render_comparison_pdf, render_portfolio_pdf, render_report_pdf, render_watchlist_pdf
from core.services.watchlist_service import rank_watchlist
from core.services.portfolio_exposure_service import analyze_portfolio_exposure
from core.services.change_tracking_service import compare_reports
from core.services.scheduler_service import ScheduledResearchService, validate_schedule
from core.services.live_readiness_service import (
    environment_readiness, readiness_summary, test_macro_provider as run_macro_readiness,
    test_market_provider as run_market_readiness,
)
from core.services.provider_cache import ProviderCache


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
