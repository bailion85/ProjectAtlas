from __future__ import annotations

import re
from typing import Any

from core.services.market_intelligence_service import validate_commentary
from core.services.feed_intelligence_service import match_post_entities


X_FEED_SERVICE_VERSION = 2
_CASHTAG = re.compile(r"(?<![A-Za-z0-9])\$([A-Za-z]{1,6})(?![A-Za-z0-9])")
_BULLISH = ("bullish", "buy", "upside", "breakout", "undervalued", "strong demand", "beat", "growth")
_BEARISH = ("bearish", "sell", "downside", "overvalued", "weak demand", "miss", "risk", "decline")


def sync_x_sources(
    provider, sources: list[dict[str, Any]], commentary: list[dict[str, Any]],
    catalog: dict[str, dict[str, Any]] | None = None,
    raw_posts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    existing_ids = {str(item.get("id")) for item in commentary}
    raw_posts = list(raw_posts or [])
    raw_ids = {str(item.get("id")) for item in raw_posts}
    additions, raw_additions, errors, fetched = [], [], [], 0
    x_sources = [item for item in sources if str(item.get("platform", "")).lower() == "x" and item.get("handle")]
    source_ids = {str(item.get("id")) for item in sources}
    for source in x_sources:
        try:
            feed = provider.recent_posts(str(source["handle"]))
            fetched += len(feed["posts"])
            for post in feed["posts"]:
                post_id = str(post.get("id", ""))
                item_id = f"x-{post_id}"
                if not post_id:
                    continue
                text = str(post.get("text", "")).strip()
                matches = (
                    match_post_entities(text, catalog) if catalog is not None else
                    [{"ticker": value.upper(), "method": "Cashtag"} for value in _CASHTAG.findall(text)]
                )
                raw_id = f"x-{post_id}"
                if raw_id not in raw_ids:
                    raw_additions.append({
                        "id": raw_id, "source_id": source["id"], "source": source.get("name"),
                        "handle": feed["handle"], "published_at": post.get("created_at"), "text": text,
                        "url": f"https://x.com/{feed['handle']}/status/{post_id}", "matches": matches,
                    })
                    raw_ids.add(raw_id)
                stance, conviction = classify_stance(text)
                argument, theme = classify_argument(text)
                for match in matches[:5]:
                    ticker = match["ticker"]
                    candidate_id = f"{item_id}-{ticker}"
                    if candidate_id in existing_ids:
                        continue
                    candidate = validate_commentary({
                        "id": candidate_id, "source_id": source["id"], "ticker": ticker,
                        "published_at": post.get("created_at"), "stance": stance,
                        "conviction": conviction, "argument_type": argument, "theme": theme,
                        "text": text, "url": f"https://x.com/{feed['handle']}/status/{post_id}",
                    }, source_ids)
                    candidate["origin"] = "X API"
                    candidate["match_method"] = match["method"]
                    additions.append(candidate)
                    existing_ids.add(candidate["id"])
        except Exception as exc:
            errors.append({"Source": source.get("name"), "Handle": source.get("handle"), "Error": str(exc)})
    merged = [*additions, *commentary][:500]
    merged_raw = [*raw_additions, *raw_posts][:500]
    return {
        "sources_checked": len(x_sources), "posts_fetched": fetched, "items_added": len(additions),
        "commentary": merged, "raw_posts": merged_raw, "raw_posts_added": len(raw_additions),
        "matched_posts": sum(bool(item.get("matches")) for item in raw_additions), "errors": errors, "usage": provider.usage_status(),
    }


def classify_stance(text: str) -> tuple[str, int]:
    normalized = text.lower()
    positive = sum(term in normalized for term in _BULLISH)
    negative = sum(term in normalized for term in _BEARISH)
    if positive > negative:
        return "Bullish", min(80, 55 + (positive - negative) * 8)
    if negative > positive:
        return "Bearish", min(80, 55 + (negative - positive) * 8)
    return "Neutral", 45


def classify_argument(text: str) -> tuple[str, str]:
    normalized = text.lower()
    mappings = (
        ("Earnings", ("earnings", "revenue", "eps", "guidance")),
        ("Valuation", ("valuation", "multiple", "p/e", "undervalued", "overvalued")),
        ("Technical", ("chart", "breakout", "support", "resistance", "moving average")),
        ("Macro", ("inflation", "rates", "fed", "yield", "dollar", "gdp")),
        ("Catalyst", ("launch", "approval", "contract", "event", "catalyst")),
        ("Risk", ("risk", "debt", "lawsuit", "regulation", "warning")),
    )
    for label, terms in mappings:
        matched = next((term for term in terms if term in normalized), None)
        if matched:
            return label, matched.title()
    return "Other", "Social commentary"
