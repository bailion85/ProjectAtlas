from core.agents.market_intelligence import MarketIntelligenceAgent
from core.providers.demo_provider import DemoProvider
from core.services.analysis_service import AnalysisService
from core.services.report_repository import ReportRepository


def test_market_intelligence_agent_abstains_without_saved_feed(tmp_path):
    assessment = MarketIntelligenceAgent(ReportRepository(tmp_path / "atlas.db")).assess("AAPL")
    assert assessment.strategy == "Market Intelligence"
    assert assessment.vote == "neutral"
    assert assessment.confidence == 15


def test_market_intelligence_agent_votes_with_independent_sources(tmp_path):
    repository = ReportRepository(tmp_path / "atlas.db")
    sources = [
        {"id": "one", "name": "One", "platform": "X", "credibility": 80, "influence": 70},
        {"id": "two", "name": "Two", "platform": "X", "credibility": 75, "influence": 60},
    ]
    posts = [{
        "source_id": source["id"], "ticker": "AAPL", "published_at": "2099-01-01T00:00:00+00:00",
        "stance": "Bullish", "conviction": 80, "argument_type": "Earnings", "theme": "Demand",
        "text": "Demand remains strong.", "url": f"https://x.com/{source['id']}/status/1",
    } for source in sources]
    repository.save_configuration("market_intelligence", {"sources": sources, "commentary": posts})
    assessment = MarketIntelligenceAgent(repository).assess("AAPL")
    assert assessment.vote == "bullish"
    assert assessment.confidence > 50
    assert len(assessment.evidence) == 2


def test_market_intelligence_agent_abstains_on_single_source(tmp_path):
    repository = ReportRepository(tmp_path / "atlas.db")
    repository.save_configuration("market_intelligence", {
        "sources": [{"id": "one", "name": "One", "platform": "X", "credibility": 90}],
        "commentary": [{"source_id": "one", "ticker": "NVDA", "published_at": "2099-01-01T00:00:00+00:00",
                        "stance": "Bullish", "conviction": 90, "text": "Strong upside."}],
    })
    assessment = MarketIntelligenceAgent(repository).assess("NVDA")
    assert assessment.vote == "neutral"
    assert assessment.confidence <= 35
def test_company_research_includes_market_intelligence_committee_vote(tmp_path):
    repository = ReportRepository(tmp_path / "atlas.db")
    sources = [
        {"id": "one", "name": "One", "platform": "X", "credibility": 85},
        {"id": "two", "name": "Two", "platform": "X", "credibility": 80},
    ]
    repository.save_configuration("market_intelligence", {
        "sources": sources,
        "commentary": [{
            "source_id": source["id"], "ticker": "AAPL", "published_at": "2099-01-01T00:00:00+00:00",
            "stance": "Bearish", "conviction": 85, "text": "Demand risk is increasing.",
        } for source in sources],
    })
    report = AnalysisService(DemoProvider(), repository).analyze("AAPL")
    assessment = next(item for item in report.assessments if item.strategy == "Market Intelligence")
    contribution = next(item for item in report.committee_contributions
                        if item["strategy"] == "Market Intelligence")
    assert assessment.vote == "bearish"
    assert contribution["weighted_signal"] < 0
    assert "seven-strategy" in report.executive_summary
