from core.services.provider_cache import ProviderCache
from core.services.x_feed_service import classify_argument, classify_stance, sync_x_sources


class FakeXProvider:
    def recent_posts(self, handle):
        return {"handle": handle.lstrip("@"), "posts": [
            {"id": "123", "created_at": "2026-08-12T12:00:00Z",
             "text": "$NVDA earnings and strong demand support more upside."},
            {"id": "124", "created_at": "2026-08-12T13:00:00Z", "text": "Macro thoughts without a cashtag."},
        ]}

    def usage_status(self):
        return {"used": 2, "remaining": 18}


def test_x_sync_adds_cashtagged_posts_and_deduplicates():
    sources = [{"id": "analyst", "name": "Analyst", "platform": "X", "handle": "@analyst"}]
    first = sync_x_sources(FakeXProvider(), sources, [])
    assert first["items_added"] == 1
    assert first["commentary"][0]["ticker"] == "NVDA"
    assert first["commentary"][0]["origin"] == "X API"
    second = sync_x_sources(FakeXProvider(), sources, first["commentary"])
    assert second["items_added"] == 0


def test_x_post_classification_is_conservative():
    assert classify_stance("Strong demand and upside") == ("Bullish", 71)
    assert classify_stance("A general update") == ("Neutral", 45)
    assert classify_argument("EPS guidance increased")[0] == "Earnings"


def test_x_provider_cache_usage_store(tmp_path):
    cache = ProviderCache(tmp_path / "cache.db")
    assert cache.usage_status("x_api", 20)["remaining"] == 20
