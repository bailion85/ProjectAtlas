from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from core.services.market_intelligence_service import build_market_intelligence


def build_entity_catalog(
    watchlist: list[str], discovery: dict[str, Any] | None, reports: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    discovery_tickers = {str(row.get("Ticker", "")).upper() for row in (discovery or {}).get("rows", [])}
    symbols = set(map(str.upper, watchlist)) | discovery_tickers | set(reports)
    catalog = {}
    for ticker in symbols:
        report = reports.get(ticker)
        company = str(getattr(report, "company", "") or "").strip()
        aliases = {ticker.lower()}
        if company:
            aliases.add(company.lower())
            cleaned = re.sub(r"\b(incorporated|inc|corp|corporation|plc|ltd|company|holdings)\b\.?", "", company.lower()).strip()
            if len(cleaned) >= 4:
                aliases.add(cleaned)
        catalog[ticker] = {
            "ticker": ticker, "company": company or ticker, "aliases": sorted(aliases),
            "on_watchlist": ticker in set(map(str.upper, watchlist)),
            "in_discovery": ticker in discovery_tickers,
        }
    return catalog


def match_post_entities(text: str, catalog: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    normalized = text.lower()
    cashtags = {value.upper() for value in re.findall(r"(?<![A-Za-z0-9])\$([A-Za-z]{1,6})(?![A-Za-z0-9])", text)}
    matches = []
    for ticker, item in catalog.items():
        method = None
        if ticker in cashtags:
            method = "Cashtag"
        elif re.search(rf"(?<![A-Za-z0-9]){re.escape(ticker.lower())}(?![A-Za-z0-9])", normalized):
            method = "Ticker mention"
        elif any(len(alias) >= 4 and re.search(rf"(?<![A-Za-z0-9]){re.escape(alias)}(?![A-Za-z0-9])", normalized)
                 for alias in item["aliases"] if alias != ticker.lower()):
            method = "Company name"
        if method:
            matches.append({"ticker": ticker, "method": method})
    return matches


def build_feed_analytics(
    sources: list[dict[str, Any]], raw_posts: list[dict[str, Any]], commentary: list[dict[str, Any]],
    catalog: dict[str, dict[str, Any]], reports: dict[str, Any], now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    matched_posts = [post for post in raw_posts if post.get("matches")]
    themes: dict[str, int] = {}
    for item in commentary:
        theme = str(item.get("theme", "Unclassified"))
        themes[theme] = themes.get(theme, 0) + 1
    decisions = []
    for ticker, universe in catalog.items():
        signal = build_market_intelligence(ticker, sources, commentary, now=now, max_age_days=30)
        report = reports.get(ticker)
        committee = float(getattr(report, "committee_score", 50)) if report else None
        risk = float(getattr(report, "risk", {}).get("score", 50)) if report else None
        if signal["items"] == 0:
            decision, rationale = "No feed signal", "No current matched feed evidence."
        elif signal["analysts"] < 2 or signal["items"] < 2:
            decision, rationale = "Research", "Feed signal lacks independent confirmation."
        elif signal["vote"] == "Bullish" and (committee is None or committee >= 50) and (risk is None or risk < 70):
            decision, rationale = "Positive review", "Feed sentiment is bullish without a conflicting saved-risk flag."
        elif signal["vote"] == "Bearish" or (risk is not None and risk >= 70):
            decision, rationale = "Risk review", "Bearish feed evidence or elevated saved research risk requires review."
        else:
            decision, rationale = "Watch", "Feed and saved research are mixed or neutral."
        decisions.append({
            "Universe": "Watchlist" if universe["on_watchlist"] else "Discovery",
            "Ticker": ticker, "Decision": decision, "Feed vote": signal["vote"],
            "Feed confidence": signal["confidence"], "Mentions": signal["items"],
            "Analysts": signal["analysts"], "Committee score": committee, "Risk": risk,
            "Why": rationale,
        })
    order = {"Risk review": 0, "Positive review": 1, "Research": 2, "Watch": 3, "No feed signal": 4}
    decisions.sort(key=lambda row: (order[row["Decision"]], -row["Mentions"], row["Ticker"]))
    return {
        "posts": len(raw_posts), "matched_posts": len(matched_posts),
        "unmatched_posts": len(raw_posts) - len(matched_posts),
        "coverage": round(len(matched_posts) / len(raw_posts) * 100, 1) if raw_posts else 0,
        "themes": [{"Theme": key, "Mentions": value} for key, value in sorted(themes.items(), key=lambda row: -row[1])],
        "decisions": decisions,
    }
