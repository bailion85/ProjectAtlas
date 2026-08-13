from datetime import datetime, timezone

from core.services.market_news_service import build_market_news


class NewsStub:
    name = "Live news"

    def market_news(self, limit=50):
        return {"provider": "Alpha Vantage News & Sentiment", "articles": [
            {"title": "Fed signals a policy shift", "summary": "Rates may change.",
             "url": "https://example.com/fed", "source": "Example Wire",
             "published_at": "20260813T140000", "sentiment": -0.25,
             "topics": [{"topic": "Economy - Monetary", "relevance": 0.9}],
             "ticker_sentiment": [{"ticker": "AAPL", "relevance": 0.7, "sentiment": -0.2}]},
            {"title": "Small company launches a product", "summary": "Product update.",
             "url": "https://example.com/product", "source": "Example Wire",
             "published_at": "20260812T140000", "sentiment": 0.05,
             "topics": [{"topic": "Technology", "relevance": 0.2}],
             "ticker_sentiment": [{"ticker": "SMALL", "relevance": 0.2, "sentiment": 0.1}]},
        ]}


def test_market_news_prioritizes_macro_and_watchlist_impact():
    result = build_market_news(
        NewsStub(), ["AAPL"], now=datetime(2026, 8, 13, 15, tzinfo=timezone.utc)
    )

    assert result["status"] == "Ready"
    assert result["articles"][0]["Headline"] == "Fed signals a policy shift"
    assert result["articles"][0]["Direction"] == "Negative"
    assert result["articles"][0]["Watchlist"] == "AAPL"
    assert "interest-rate expectations" in result["articles"][0]["Why it matters"]
    assert result["articles"][0]["Impact"] > result["articles"][1]["Impact"]