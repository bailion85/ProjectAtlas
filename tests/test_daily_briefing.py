from dataclasses import replace
from datetime import datetime, timezone

from core.providers.demo_provider import DemoProvider
from core.services.analysis_service import AnalysisService
from core.services.daily_briefing_service import build_daily_briefing
from core.services.report_repository import ReportRepository


def test_daily_briefing_uses_saved_evidence_without_provider_calls(tmp_path):
    repository = ReportRepository(tmp_path / "atlas.db")
    report = AnalysisService(DemoProvider(), repository).analyze("AAPL")
    result = build_daily_briefing(
        {"AAPL": report}, [{"ticker": "AAPL", "allocation": 30}],
        [{"severity": "High", "ticker": "AAPL", "title": "Review risk", "message": "Risk changed"}],
        {"rows": [{"Rank": 1, "Ticker": "NEW", "Research label": "Worth watching",
                    "Discovery score": 67, "Data status": "Live price only",
                    "Why it surfaced": "Constructive trend", "On radar": False}]},
        {"quota_remaining": 0, "last_source": "Fresh cache"},
        now=datetime.now(timezone.utc),
    )
    assert result["posture"] == "Cautious"
    assert result["market"]["status"] == "Demo"
    assert result["data"]["status"] == "Degraded"
    assert result["portfolio"][0]["Priority"] == "Monitor"
    assert result["discovery"][0]["Ticker"] == "NEW"
    assert any(item["Where"] == "Alerts" for item in result["actions"])


def test_daily_briefing_only_includes_verified_live_catalysts(tmp_path):
    repository = ReportRepository(tmp_path / "atlas.db")
    base = AnalysisService(DemoProvider(), repository).analyze("MSFT")
    live = replace(
        base, provider="Tiingo + Alpha Vantage",
        market_environment={**base.market_environment, "event_provider": "Live news", "macro_provider": "FRED"},
        catalyst_calendar={
            "live": True, "stale": False, "provider": "Official calendar",
            "next_event": {"title": "MSFT earnings", "date": "2026-08-20", "days_until": 8,
                           "importance": 90, "source": "Live calendar", "source_live": True,
                           "source_stale": False},
        },
    )
    result = build_daily_briefing(
        {"MSFT": live}, [], [], None, {"quota_remaining": 10},
        now=datetime.now(timezone.utc),
    )
    assert result["market"]["status"] == "Live saved evidence"
    assert result["catalysts"][0]["Event"] == "MSFT earnings"
    stale = replace(live, catalyst_calendar={**live.catalyst_calendar, "stale": True})
    assert build_daily_briefing({"MSFT": stale}, [], [], None, {}, now=datetime.now(timezone.utc))["catalysts"] == []


def test_daily_briefing_handles_empty_saved_state():
    result = build_daily_briefing({}, [], [], None, {}, now=datetime(2026, 8, 12, tzinfo=timezone.utc))
    assert result["market"]["status"] == "Missing"
    assert result["posture"] == "Selective"
    assert result["actions"][0]["Action"] == "Refresh market evidence"
