from core.services.daily_intelligence_summary_service import build_daily_intelligence_summary


def test_daily_intelligence_summary_reports_cross_source_decisions():
    result = build_daily_intelligence_summary(
        {"posture": "Selective"},
        {"tickers": 2, "top_ticker": "NVDA", "rows": [
            {"Ticker": "NVDA", "Attention score": 88, "Sentiment": "Bullish",
             "Mentions": 4, "Analysts": 2, "Themes": "AI demand"},
        ]},
        {"posts": 6, "matched_posts": 4, "coverage": 66.7, "themes": [{"Theme": "AI", "Mentions": 4}],
         "decisions": [
             {"Ticker": "NVDA", "Decision": "Positive review"},
             {"Ticker": "TSLA", "Decision": "Risk review"},
         ]},
    )
    assert result["status"] == "Ready"
    assert result["positive_reviews"] == 1
    assert result["risk_reviews"] == 1
    assert "processed 6" in result["executive_summary"]


def test_daily_intelligence_summary_surfaces_provider_blocker():
    result = build_daily_intelligence_summary(
        {"posture": "Cautious"}, {"rows": []},
        {"posts": 0, "matched_posts": 0, "coverage": 0, "decisions": []},
        {"errors": [{"Error": "X API: credits depleted"}]},
    )
    assert result["status"] == "Provider blocked"
    assert "credits depleted" in result["executive_summary"]
