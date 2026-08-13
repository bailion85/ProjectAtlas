from datetime import datetime, timedelta, timezone

import pytest

from core.services.market_intelligence_service import (
    build_market_intelligence, validate_commentary, validate_source,
)


def test_market_intelligence_weights_credibility_expertise_and_recency():
    now = datetime(2026, 8, 12, tzinfo=timezone.utc)
    sources = [
        {"id": "expert", "name": "Semiconductor Expert", "platform": "X", "credibility": 90,
         "influence": 60, "expertise": ["Technology"]},
        {"id": "general", "name": "General Commentator", "platform": "YouTube", "credibility": 40,
         "influence": 95, "expertise": ["Macro"]},
    ]
    posts = [
        {"source_id": "expert", "ticker": "NVDA", "published_at": now.isoformat(), "stance": "Bullish",
         "conviction": 90, "argument_type": "Earnings", "theme": "AI demand", "text": "Demand remains strong."},
        {"source_id": "general", "ticker": "NVDA", "published_at": (now - timedelta(days=20)).isoformat(),
         "stance": "Bearish", "conviction": 80, "argument_type": "Valuation", "theme": "Valuation risk",
         "text": "The multiple is extended."},
    ]
    result = build_market_intelligence("NVDA", sources, posts, sector="Technology", now=now)
    assert result["vote"] == "Bullish"
    assert result["signal_score"] > 50
    assert result["bullish"] == 1 and result["bearish"] == 1
    assert result["themes"][0]["Theme"] in {"AI demand", "Valuation risk"}


def test_market_intelligence_excludes_old_and_other_ticker_commentary():
    now = datetime(2026, 8, 12, tzinfo=timezone.utc)
    sources = [{"id": "one", "name": "One", "credibility": 80, "influence": 50}]
    posts = [
        {"source_id": "one", "ticker": "AAPL", "published_at": (now - timedelta(days=31)).isoformat(),
         "stance": "Bullish", "conviction": 80, "text": "Old."},
        {"source_id": "one", "ticker": "MSFT", "published_at": now.isoformat(),
         "stance": "Bearish", "conviction": 80, "text": "Other."},
    ]
    result = build_market_intelligence("AAPL", sources, posts, now=now)
    assert result["items"] == 0
    assert result["vote"] == "Neutral"
    assert result["confidence"] == 0


def test_market_intelligence_validates_saved_inputs():
    source = validate_source({"name": "Bald Guy Money", "platform": "X", "credibility": 91,
                              "influence": 70, "expertise": ["Macro", "Precious metals"]})
    assert source["id"] == "bald-guy-money"
    item = validate_commentary({"source_id": source["id"], "ticker": "gld", "stance": "bullish",
                                "conviction": 88, "text": "Real yields support gold."}, {source["id"]})
    assert item["ticker"] == "GLD"
    with pytest.raises(ValueError):
        validate_commentary({"source_id": "missing", "ticker": "GLD", "text": "No source"}, {source["id"]})
