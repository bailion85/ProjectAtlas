from dataclasses import replace
from datetime import datetime, timezone

from core.providers.demo_provider import DemoProvider
from core.services.analysis_service import AnalysisService
from core.services.holding_guidance_service import build_holding_guidance
from core.services.report_repository import ReportRepository


def _live_report(tmp_path, ticker="AAPL"):
    repository = ReportRepository(tmp_path / "reports.db")
    base = AnalysisService(DemoProvider(), repository).analyze(ticker)
    return replace(
        base,
        created_at=datetime.now(timezone.utc).isoformat(),
        provider="Tiingo + Alpha Vantage",
    )


def test_holdings_are_saved_without_allocations(tmp_path):
    repository = ReportRepository(tmp_path / "atlas.db")
    repository.save_portfolio_holdings(["msft", "AAPL", "MSFT"])
    assert repository.portfolio_holdings() == ["AAPL", "MSFT"]
    assert repository.portfolio_positions() == []


def test_guidance_can_suggest_more_without_target_weight(tmp_path):
    report = replace(
        _live_report(tmp_path),
        committee_vote="bullish",
        committee_confidence=78,
        risk={"score": 32},
        entry_readiness={"score": 74},
    )
    result = build_holding_guidance(["AAPL"], {"AAPL": report})
    row = result["rows"][0]
    assert row["Direction"] == "Consider more"
    assert "weight" not in " ".join(row).lower()
    assert result["counts"]["Consider more"] == 1


def test_guidance_flags_bearish_and_missing_research(tmp_path):
    report = replace(
        _live_report(tmp_path, "MSFT"),
        committee_vote="bearish",
        committee_confidence=72,
        risk={"score": 76},
        entry_readiness={"score": 35},
    )
    result = build_holding_guidance(["MSFT", "RKLB"], {"MSFT": report})
    rows = {row["Ticker"]: row for row in result["rows"]}
    assert rows["MSFT"]["Direction"] == "Consider less"
    assert rows["MSFT"]["Caution"] == "High"
    assert rows["RKLB"]["Direction"] == "Research needed"
