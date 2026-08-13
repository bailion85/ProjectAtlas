from datetime import datetime, timezone

from core.services.trending_intelligence_service import build_trending_intelligence


def test_trending_ranks_attention_separately_from_sentiment():
    now = datetime(2026, 8, 12, tzinfo=timezone.utc)
    sources = [
        {"id": "one", "name": "One", "credibility": 80, "influence": 90},
        {"id": "two", "name": "Two", "credibility": 70, "influence": 60},
    ]
    posts = [
        {"source_id": "one", "ticker": "TSLA", "published_at": now.isoformat(),
         "stance": "Bearish", "conviction": 85, "theme": "Valuation"},
        {"source_id": "two", "ticker": "TSLA", "published_at": now.isoformat(),
         "stance": "Bearish", "conviction": 70, "theme": "Demand"},
        {"source_id": "one", "ticker": "NVDA", "published_at": now.isoformat(),
         "stance": "Bullish", "conviction": 90, "theme": "AI demand"},
    ]
    result = build_trending_intelligence(sources, posts, now=now)
    assert result["top_ticker"] == "TSLA"
    assert result["rows"][0]["Sentiment"] == "Bearish"
    assert result["rows"][1]["Sentiment"] == "Bullish"


def test_trending_ignores_old_items():
    result = build_trending_intelligence(
        [{"id": "one"}],
        [{"source_id": "one", "ticker": "AAPL", "published_at": "2026-07-01T00:00:00Z"}],
        now=datetime(2026, 8, 12, tzinfo=timezone.utc),
    )
    assert result["rows"] == []
