from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def build_trending_intelligence(
    sources: list[dict[str, Any]], commentary: list[dict[str, Any]],
    now: datetime | None = None, max_age_days: int = 7,
) -> dict[str, Any]:
    """Rank tickers by recent curated-feed attention, independent of direction."""
    now = now or datetime.now(timezone.utc)
    source_map = {str(item.get("id")): item for item in sources if item.get("id")}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in commentary:
        ticker = str(item.get("ticker", "")).strip().upper()
        source = source_map.get(str(item.get("source_id")))
        if not ticker or not source:
            continue
        age = max(0.0, (now - _datetime(item.get("published_at"))).total_seconds() / 86400)
        if age <= max_age_days:
            grouped.setdefault(ticker, []).append({**item, "source": source, "age": age})
    if not grouped:
        return {"rows": [], "tickers": 0, "mentions": 0, "analysts": 0, "top_ticker": None}
    max_mentions = max(len(items) for items in grouped.values())
    rows = []
    for ticker, items in grouped.items():
        analysts = {str(item["source"].get("id")) for item in items}
        recency = sum(max(0.0, 1 - item["age"] / max_age_days) for item in items) / len(items)
        influence = sum(_score(item["source"].get("influence", 50)) for item in items) / len(items)
        attention = (
            len(items) / max_mentions * 55 + min(len(analysts), 3) / 3 * 20
            + recency * 15 + influence / 100 * 10
        )
        weighted = []
        for item in items:
            direction = {"Bullish": 1, "Neutral": 0, "Bearish": -1}.get(
                str(item.get("stance", "Neutral")).title(), 0,
            )
            weight = (_score(item.get("conviction", 50)) / 100
                      * _score(item["source"].get("credibility", 50)) / 100
                      * max(0.1, 1 - item["age"] / max_age_days))
            weighted.append((direction * weight, weight))
        denominator = sum(weight for _, weight in weighted)
        signal = sum(value for value, _ in weighted) / denominator if denominator else 0
        sentiment = "Bullish" if signal >= .2 else "Bearish" if signal <= -.2 else "Mixed / neutral"
        themes = sorted({str(item.get("theme", "Unclassified")) for item in items})
        rows.append({
            "Ticker": ticker, "Attention score": round(min(100, attention), 1),
            "Mentions": len(items), "Analysts": len(analysts), "Sentiment": sentiment,
            "Sentiment score": round((signal + 1) * 50, 1), "Average influence": round(influence, 1),
            "Latest mention (days)": min(round(item["age"], 1) for item in items),
            "Themes": ", ".join(themes[:3]),
        })
    rows.sort(key=lambda row: (-row["Attention score"], -row["Mentions"], row["Ticker"]))
    return {
        "rows": rows, "tickers": len(rows), "mentions": sum(len(items) for items in grouped.values()),
        "analysts": len({str(item["source"].get("id")) for items in grouped.values() for item in items}),
        "top_ticker": rows[0]["Ticker"],
    }


def _score(value: Any) -> int:
    try:
        return max(0, min(100, round(float(value))))
    except (TypeError, ValueError):
        return 50


def _datetime(value: Any) -> datetime:
    observed = datetime.fromisoformat(str(value).replace("Z", "+00:00")) if value else datetime.now(timezone.utc)
    return observed.replace(tzinfo=timezone.utc) if observed.tzinfo is None else observed.astimezone(timezone.utc)
