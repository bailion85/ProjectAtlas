from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import html
import os
import re
from typing import Any
from xml.etree import ElementTree

from core.providers.market_provider import ProviderError


NEWS_PROVIDER_VERSION = 3
_QUERY = ('("stock market" OR stocks OR "Federal Reserve" OR inflation OR recession OR earnings '
          'OR "crude oil" OR tariffs OR treasury) sourcelang:english')


class GdeltNewsProvider:
    """No-key market news from GDELT and official public RSS feeds."""

    name = "Public news feeds (GDELT + Federal Reserve + SEC + EIA)"
    marketaux_url = "https://api.marketaux.com/v1/news/all"
    base_url = "https://api.gdeltproject.org/api/v2/doc/doc"
    cache_namespace = "news:public-market-feeds"

    def __init__(self, cache, timeout: int = 30):
        self.cache = cache
        self.timeout = timeout
        self.marketaux_token = os.getenv("MARKETAUX_API_TOKEN", "").strip()
        if self.marketaux_token:
            self.name = "MarketAux + public feeds (GDELT + Federal Reserve + SEC + EIA)"

    def market_news(self, limit: int = 50) -> dict[str, Any]:
        parameters = {"schema": 3, "query": _QUERY, "limit": max(25, min(250, int(limit))),
                      "marketaux": bool(self.marketaux_token)}
        cached = self.cache.get(self.cache_namespace, "market_news", parameters)
        if cached:
            return {**cached.value, "cache_status": "Fresh cache", "cache_age_seconds": round(cached.age_seconds)}
        try:
            result = self._combined_request(parameters["limit"])
            self.cache.put(self.cache_namespace, "market_news", parameters, result, 15 * 60)
            return {**result, "cache_status": "Fresh public response", "cache_age_seconds": 0}
        except ProviderError as exc:
            stale = self.cache.get(self.cache_namespace, "market_news", parameters, allow_expired=True)
            if stale and stale.age_seconds <= 24 * 60 * 60:
                return {**stale.value, "cache_status": "Stale cached fallback",
                        "cache_age_seconds": round(stale.age_seconds), "stale": True, "error": str(exc)}
            raise

    def _combined_request(self, limit: int) -> dict[str, Any]:
        articles: list[dict[str, Any]] = []
        errors: list[str] = []
        if self.marketaux_token:
            try:
                articles.extend(self._marketaux_articles(limit))
            except ProviderError as exc:
                errors.append(str(exc))
        try:
            articles.extend(self._request(limit).get("articles", []))
        except ProviderError as exc:
            errors.append(str(exc))

        feeds = (
            ("Federal Reserve", "https://www.federalreserve.gov/feeds/press_all.xml"),
            ("Federal Reserve monetary policy", "https://www.federalreserve.gov/feeds/press_monetary.xml"),
            ("SEC", "https://www.sec.gov/news/pressreleases.rss"),
            ("EIA Today in Energy", "https://www.eia.gov/rss/todayinenergy.xml"),
            ("EIA press releases", "https://www.eia.gov/rss/press_rss.xml"),
        )
        for source, url in feeds:
            try:
                articles.extend(self._rss_articles(source, url))
            except ProviderError as exc:
                errors.append(str(exc))

        unique: list[dict[str, Any]] = []
        seen: set[str] = set()
        for article in articles:
            key = str(article.get("url") or article.get("title", "")).strip().lower()
            if key and key not in seen:
                seen.add(key)
                unique.append(article)
        if not unique:
            detail = "; ".join(errors[:3]) or "No current articles were returned."
            raise ProviderError(f"Public news feeds are unavailable: {detail}")
        return {
            "provider": self.name,
            "articles": unique[:max(limit, 25)],
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "stale": False,
            "source_errors": errors,
        }

    def _marketaux_articles(self, limit: int) -> list[dict[str, Any]]:
        try:
            import requests
        except ImportError as exc:
            raise ProviderError("Install requests to use MarketAux.") from exc
        try:
            response = requests.get(
                self.marketaux_url,
                params={
                    "api_token": self.marketaux_token,
                    "language": "en",
                    "countries": "us",
                    "filter_entities": "true",
                    "limit": min(50, max(3, int(limit))),
                },
                headers={"User-Agent": "Project Atlas market research dashboard"},
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise ProviderError(f"MarketAux news request failed: {exc}") from exc
        except ValueError as exc:
            raise ProviderError("MarketAux returned an invalid news response.") from exc

        articles = []
        for item in payload.get("data", []):
            title = str(item.get("title", "")).strip()
            url = str(item.get("url", "")).strip()
            if not title or not url:
                continue
            entities = []
            sentiment_values = []
            for entity in item.get("entities") or []:
                symbol = str(entity.get("symbol", "")).strip().upper()
                relevance = _number(entity.get("match_score"))
                sentiment = _number(entity.get("sentiment_score"))
                if symbol:
                    entities.append({
                        "ticker": symbol,
                        "relevance": relevance if relevance is not None else .5,
                        "sentiment": sentiment,
                    })
                if sentiment is not None:
                    sentiment_values.append(sentiment)
            article_sentiment = _number(item.get("sentiment_score"))
            if article_sentiment is None and sentiment_values:
                article_sentiment = sum(sentiment_values) / len(sentiment_values)
            summary = str(item.get("description") or item.get("snippet") or "").strip()
            articles.append({
                "title": title,
                "summary": summary,
                "url": url,
                "source": item.get("source") or "MarketAux",
                "published_at": item.get("published_at", ""),
                "sentiment": article_sentiment,
                "sentiment_label": _sentiment_label(article_sentiment),
                "ticker_sentiment": entities,
                "topics": [{"topic": topic, "relevance": .9}
                           for topic in _topics(f"{title} {summary}")],
            })
        return articles
    def _rss_articles(self, source: str, url: str) -> list[dict[str, Any]]:
        try:
            import requests
        except ImportError as exc:
            raise ProviderError("Install requests to use public news feeds.") from exc
        user_agent = os.getenv("SEC_USER_AGENT", "Project Atlas market research contact@example.com")
        try:
            response = requests.get(url, headers={"User-Agent": user_agent}, timeout=self.timeout)
            response.raise_for_status()
            root = ElementTree.fromstring(response.content)
        except (requests.RequestException, ElementTree.ParseError) as exc:
            raise ProviderError(f"{source} feed failed: {exc}") from exc
        articles = []
        for item in root.findall(".//item"):
            title = _xml_text(item, "title")
            link = _xml_text(item, "link")
            if not title or not link:
                continue
            summary = re.sub(r"<[^>]+>", " ", html.unescape(_xml_text(item, "description")))
            summary = " ".join(summary.split())
            articles.append({
                "title": title, "summary": summary, "url": link, "source": source,
                "published_at": _rss_date(_xml_text(item, "pubDate")), "sentiment": None,
                "sentiment_label": "Not scored", "ticker_sentiment": [],
                "topics": [{"topic": topic, "relevance": .9}
                           for topic in _topics(f"{title} {summary}")],
            })
        return articles

    def _request(self, limit: int) -> dict[str, Any]:
        try:
            import requests
        except ImportError as exc:
            raise ProviderError("Install requests to use the public GDELT news feed.") from exc
        try:
            response = requests.get(self.base_url, params={
                "query": _QUERY, "mode": "artlist", "format": "json",
                "maxrecords": str(limit), "timespan": "24h", "sort": "datedesc",
            }, headers={"User-Agent": "Project Atlas market research dashboard"}, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise ProviderError(f"GDELT news request failed: {exc}") from exc
        except ValueError as exc:
            raise ProviderError("GDELT returned an invalid news response.") from exc
        articles = []
        for item in payload.get("articles", []):
            title = str(item.get("title", "")).strip()
            url = str(item.get("url", "")).strip()
            if not title or not url:
                continue
            articles.append({
                "title": title, "summary": "", "url": url,
                "source": item.get("domain") or "GDELT indexed source",
                "published_at": item.get("seendate", ""), "sentiment": None,
                "sentiment_label": "Not scored", "ticker_sentiment": [],
                "topics": [{"topic": topic, "relevance": .8} for topic in _topics(title)],
            })
        if not articles:
            raise ProviderError("GDELT returned no current market-news articles.")
        return {"provider": "GDELT DOC 2.0 public news index", "articles": articles,
                "retrieved_at": datetime.now(timezone.utc).isoformat(), "stale": False}


def _topics(title: str) -> list[str]:
    text = title.lower()
    rules = (
        ("Economy - Monetary", ("fed", "federal reserve", "interest rate", "treasury", "yield")),
        ("Economy - Macro", ("inflation", "recession", "economy", "gdp", "jobs", "unemployment")),
        ("Financial Markets", ("stock", "market", "dow", "nasdaq", "s&p", "wall street")),
        ("Energy & Transportation", ("oil", "crude", "opec", "gasoline", "energy")),
        ("Earnings", ("earnings", "revenue", "profit", "guidance")),
        ("Finance", ("bank", "credit", "bond", "liquidity")),
        ("Technology", ("technology", "semiconductor", "chip", "artificial intelligence", " ai ")),
    )
    return [topic for topic, terms in rules if any(term in f" {text} " for term in terms)]


def _xml_text(item: ElementTree.Element, tag: str) -> str:
    node = item.find(tag)
    return "" if node is None or node.text is None else node.text.strip()


def _rss_date(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    except (TypeError, ValueError, OverflowError):
        return value


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _sentiment_label(value: float | None) -> str:
    if value is None:
        return "Not scored"
    if value >= .15:
        return "Positive"
    if value <= -.15:
        return "Negative"
    return "Neutral"
