import os
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from core.providers.news_provider import GdeltNewsProvider
from core.services.provider_cache import ProviderCache


RSS = b"""<?xml version="1.0"?><rss><channel><item>
<title>Federal Reserve updates monetary policy outlook</title>
<link>https://www.federalreserve.gov/example.htm</link>
<description>Rates and the economy remain in focus.</description>
<pubDate>Thu, 13 Aug 2026 15:00:00 GMT</pubDate>
</item></channel></rss>"""


def _public_response(url, **kwargs):
    response = Mock()
    response.raise_for_status.return_value = None
    if "gdeltproject.org" in url:
        response.json.return_value = {"articles": [{
            "title": "Federal Reserve decision moves stock market",
            "url": "https://example.com/market", "domain": "example.com",
            "seendate": "20260813T150000Z",
        }]}
    else:
        response.content = RSS
    return response


def test_public_news_requires_no_key_and_caches_results(tmp_path: Path):
    cache = ProviderCache(tmp_path / "cache.db")
    with patch.dict(os.environ, {"MARKETAUX_API_TOKEN": ""}):
        provider = GdeltNewsProvider(cache)
    with patch("requests.get", side_effect=_public_response) as request:
        first = provider.market_news(25)
        second = provider.market_news(25)

    assert request.call_count == 6
    assert first["provider"].startswith("Public news feeds")
    assert second["cache_status"] == "Fresh cache"
    assert first["articles"][0]["topics"]
    gdelt_call = next(call for call in request.call_args_list
                      if "gdeltproject.org" in call.args[0])
    assert "apikey" not in gdelt_call.kwargs["params"]


def test_official_rss_feeds_continue_when_gdelt_is_rate_limited(tmp_path: Path):
    cache = ProviderCache(tmp_path / "cache.db")
    with patch.dict(os.environ, {"MARKETAUX_API_TOKEN": ""}):
        provider = GdeltNewsProvider(cache)

    def response_for(url, **kwargs):
        if "gdeltproject.org" in url:
            raise requests.HTTPError("429 Too Many Requests")
        response = Mock()
        response.raise_for_status.return_value = None
        response.content = RSS
        return response

    with patch("requests.get", side_effect=response_for):
        result = provider.market_news(25)

    assert result["articles"]
    assert result["articles"][0]["source"] == "Federal Reserve"
    assert any("GDELT news request failed" in error for error in result["source_errors"])


def test_marketaux_enriches_news_with_entities_and_sentiment(tmp_path: Path):
    cache = ProviderCache(tmp_path / "cache.db")
    with patch.dict(os.environ, {"MARKETAUX_API_TOKEN": "test-token"}):
        provider = GdeltNewsProvider(cache)

    def response_for(url, **kwargs):
        response = Mock()
        response.raise_for_status.return_value = None
        if "marketaux.com" in url:
            response.json.return_value = {"data": [{
                "title": "Nvidia leads chip stocks after upbeat outlook",
                "description": "Semiconductor shares moved higher.",
                "url": "https://example.com/nvda",
                "source": "Example Markets",
                "published_at": "2026-08-13T15:00:00+00:00",
                "entities": [{"symbol": "NVDA", "match_score": 0.95,
                              "sentiment_score": 0.42}],
            }]}
        elif "gdeltproject.org" in url:
            response.json.return_value = {"articles": []}
        else:
            response.content = RSS
        return response

    with patch("requests.get", side_effect=response_for) as request:
        result = provider.market_news(25)

    marketaux_call = next(call for call in request.call_args_list
                          if "marketaux.com" in call.args[0])
    article = next(item for item in result["articles"]
                   if item["url"] == "https://example.com/nvda")
    assert marketaux_call.kwargs["params"]["api_token"] == "test-token"
    assert article["ticker_sentiment"][0]["ticker"] == "NVDA"
    assert article["sentiment"] == 0.42
    assert result["provider"].startswith("MarketAux +")
