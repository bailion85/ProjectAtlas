from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

from core.providers.market_provider import ProviderError

MARKET_NEWS_SERVICE_VERSION = 1
_TOPIC_CONTEXT = {
    "Economy - Monetary": "May shift interest-rate expectations and equity valuations.",
    "Economy - Macro": "May change the market's growth and recession outlook.",
    "Financial Markets": "Directly concerns broad financial-market conditions.",
    "Energy & Transportation": "May affect oil, inflation, transport costs, and consumer margins.",
    "Finance": "May affect credit availability, banks, and market liquidity.",
    "Earnings": "May reset earnings expectations and sector leadership.",
    "Technology": "May influence growth-stock leadership and capital spending.",
    "IPO": "May indicate changes in risk appetite and capital-market activity.",
    "Mergers & Acquisitions": "May affect sector valuations and competitive positioning.",
}
_HIGH_IMPACT_TOPICS = set(_TOPIC_CONTEXT)


def build_market_news(provider, watchlist: list[str] | None = None, limit: int = 10,
                      now: datetime | None = None) -> dict[str, Any]:
    """Rank licensed provider headlines by potential market relevance."""
    now = now or datetime.now(timezone.utc)
    watchlist_set = {str(ticker).upper() for ticker in (watchlist or [])}
    try:
        snapshot = provider.market_news(max(25, limit * 3))
    except (ProviderError, RuntimeError, ValueError, AttributeError) as exc:
        return {"status": "Unavailable", "provider": getattr(provider, "name", "Unknown"),
                "articles": [], "errors": [str(exc)], "retrieved_at": now.isoformat()}

    ranked, seen = [], set()
    for article in snapshot.get("articles", []):
        title = str(article.get("title", "")).strip()
        url = str(article.get("url", "")).strip()
        identity = url.lower() or title.lower()
        if not title or identity in seen:
            continue
        seen.add(identity)
        published = _published(article.get("published_at"))
        age_hours = max(0.0, (now - published).total_seconds() / 3600) if published else 168.0
        topics = [str(item.get("topic", "")).strip() for item in article.get("topics", [])
                  if float(item.get("relevance") or 0) >= .15 and item.get("topic")]
        ticker_rows = [item for item in article.get("ticker_sentiment", [])
                       if float(item.get("relevance") or 0) >= .15]
        tickers = [str(item.get("ticker", "")).upper() for item in ticker_rows if item.get("ticker")]
        article_text = f"{title} {article.get('summary', '')}"
        for ticker in watchlist_set:
            if re.search(rf"(?<![A-Za-z0-9]){re.escape(ticker)}(?![A-Za-z0-9])", article_text, re.IGNORECASE):
                tickers.append(ticker)
        watchlist_matches = sorted(set(tickers) & watchlist_set)
        sentiment = _number(article.get("sentiment")) or 0.0
        topic_score = 20 if set(topics) & _HIGH_IMPACT_TOPICS else 8 if topics else 0
        recency_score = max(0.0, 30 - age_hours / 2)
        sentiment_score = min(20.0, abs(sentiment) * 40)
        breadth_score = min(10.0, len(set(tickers)) * 2)
        watchlist_score = 15 if watchlist_matches else 0
        importance = round(min(100.0, 25 + topic_score + recency_score + sentiment_score
                               + breadth_score + watchlist_score), 1)
        ranked.append({
            "Impact": importance, "Direction": _direction(sentiment), "Headline": title,
            "Why it matters": _why(topics, watchlist_matches, tickers),
            "Themes": ", ".join(topics[:3]) or "General market",
            "Tickers": ", ".join(tickers[:8]) or "Broad market",
            "Watchlist": ", ".join(watchlist_matches) or None,
            "Source": article.get("source") or snapshot.get("provider", "Unknown"),
            "Published": published.isoformat() if published else article.get("published_at"),
            "Summary": str(article.get("summary", "")).strip(), "Article": url,
        })
    ranked.sort(key=lambda item: (item["Impact"], str(item["Published"])), reverse=True)
    return {
        "status": "Ready" if ranked else "Unavailable",
        "provider": snapshot.get("provider", getattr(provider, "name", "Unknown")),
        "articles": ranked[:limit], "total_collected": len(seen),
        "retrieved_at": now.isoformat(), "errors": [],
        "disclosure": ("Impact is an Atlas relevance score, not a prediction of price direction. "
                       "Open the original article and confirm facts before using a headline in research."),
    }


def _published(value: Any) -> datetime | None:
    text = str(value or "").strip()
    for pattern in ("%Y%m%dT%H%M%SZ", "%Y%m%dT%H%M%S", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            parsed = datetime.strptime(text, pattern)
            return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def _direction(sentiment: float) -> str:
    return "Positive" if sentiment >= .15 else "Negative" if sentiment <= -.15 else "Mixed / neutral"


def _why(topics: list[str], watchlist: list[str], tickers: list[str]) -> str:
    context = next((_TOPIC_CONTEXT[topic] for topic in topics if topic in _TOPIC_CONTEXT),
                   "May affect broad sentiment or the companies mentioned.")
    if watchlist:
        return f"{context} Direct watchlist exposure: {', '.join(watchlist)}."
    if len(set(tickers)) >= 4:
        return f"{context} The article has broad company coverage."
    return context


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None