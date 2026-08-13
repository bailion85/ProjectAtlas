from dataclasses import replace
from datetime import datetime, timezone

from core.providers.demo_provider import DemoProvider
from core.services.analysis_service import AnalysisService
from core.services.feed_intelligence_service import build_entity_catalog, build_feed_analytics, match_post_entities
from core.services.report_repository import ReportRepository


def test_entity_matching_supports_cashtags_tickers_and_company_names(tmp_path):
    report = AnalysisService(DemoProvider(), ReportRepository(tmp_path / "atlas.db")).analyze("AAPL")
    catalog = build_entity_catalog(["AAPL"], {"rows": [{"Ticker": "NVDA"}]}, {"AAPL": report})
    assert match_post_entities("Watching $AAPL after earnings", catalog)[0]["method"] == "Cashtag"
    assert match_post_entities("AAPL may break support", catalog)[0]["method"] == "Ticker mention"
    assert match_post_entities(f"{report.company} demand looks strong", catalog)[0]["ticker"] == "AAPL"


def test_feed_agent_separates_watchlist_and_discovery_decisions(tmp_path):
    now = datetime(2026, 8, 12, tzinfo=timezone.utc)
    report = AnalysisService(DemoProvider(), ReportRepository(tmp_path / "atlas.db")).analyze("AAPL")
    report = replace(report, committee_score=70, risk={**report.risk, "score": 40})
    sources = [{"id": "one", "name": "One", "credibility": 80, "influence": 70},
               {"id": "two", "name": "Two", "credibility": 80, "influence": 70}]
    commentary = [{"source_id": source, "ticker": "AAPL", "published_at": now.isoformat(),
                   "stance": "Bullish", "conviction": 80, "theme": "Demand", "text": "Strong demand"}
                  for source in ("one", "two")]
    catalog = build_entity_catalog(["AAPL"], {"rows": [{"Ticker": "NVDA"}]}, {"AAPL": report})
    result = build_feed_analytics(sources, [{"matches": [{"ticker": "AAPL"}]}], commentary, catalog, {"AAPL": report}, now)
    aapl = next(row for row in result["decisions"] if row["Ticker"] == "AAPL")
    nvda = next(row for row in result["decisions"] if row["Ticker"] == "NVDA")
    assert aapl["Universe"] == "Watchlist" and aapl["Decision"] == "Positive review"
    assert nvda["Universe"] == "Discovery" and nvda["Decision"] == "No feed signal"
