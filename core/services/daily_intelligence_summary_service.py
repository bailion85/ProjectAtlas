from __future__ import annotations

from typing import Any


def build_daily_intelligence_summary(
    briefing: dict[str, Any], trending: dict[str, Any], feed: dict[str, Any],
    last_sync: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Combine saved market research and feed analytics into an auditable executive readout."""
    last_sync = last_sync or {}
    errors = [str(item.get("Error", "Unknown provider error")) for item in last_sync.get("errors", [])]
    actionable = [row for row in feed.get("decisions", []) if row.get("Decision") != "No feed signal"]
    risk_reviews = [row for row in actionable if row.get("Decision") == "Risk review"]
    positives = [row for row in actionable if row.get("Decision") == "Positive review"]
    research = [row for row in actionable if row.get("Decision") == "Research"]
    top = list(trending.get("rows", []))[:5]
    if errors and feed.get("posts", 0) == 0:
        status = "Provider blocked"
        narrative = (
            f"Atlas could not produce current Market Intelligence because the last feed refresh failed: "
            f"{'; '.join(errors)}. The broader saved-evidence posture remains {briefing['posture'].lower()}, "
            "but no social-feed conclusion should be used until posts are successfully retrieved."
        )
    elif feed.get("posts", 0) == 0:
        status = "No feed evidence"
        narrative = (
            f"Today's saved-evidence posture is {briefing['posture'].lower()}. No feed posts are saved, "
            "so Market Intelligence cannot confirm or challenge the Watchlist or Discovery ranking."
        )
    else:
        status = "Ready" if feed.get("coverage", 0) >= 40 else "Limited coverage"
        leading = ", ".join(
            f"{row['Ticker']} ({row['Sentiment'].lower()}, attention {row['Attention score']:.0f})"
            for row in top[:3]
        ) or "no company-specific trend"
        narrative = (
            f"Atlas processed {feed['posts']} saved feed post(s), matched {feed['matched_posts']} "
            f"to the Watchlist or Discovery universe ({feed['coverage']:.0f}% coverage), and identified "
            f"{trending.get('tickers', 0)} trending stock(s). Leading attention: {leading}. "
            f"The agent flagged {len(positives)} positive review(s), {len(risk_reviews)} risk review(s), "
            f"and {len(research)} signal(s) needing more independent confirmation. "
            f"This complements a {briefing['posture'].lower()} saved-evidence posture; it does not override it."
        )
    highlights = [{
        "Ticker": row.get("Ticker"), "Attention": row.get("Attention score"),
        "Sentiment": row.get("Sentiment"), "Mentions": row.get("Mentions"),
        "Analysts": row.get("Analysts"), "Themes": row.get("Themes"),
    } for row in top]
    return {
        "status": status, "executive_summary": narrative,
        "posts": feed.get("posts", 0), "coverage": feed.get("coverage", 0),
        "trending_stocks": trending.get("tickers", 0), "top_ticker": trending.get("top_ticker"),
        "positive_reviews": len(positives), "risk_reviews": len(risk_reviews),
        "needs_research": len(research), "highlights": highlights,
        "decisions": actionable[:8], "themes": list(feed.get("themes", []))[:8],
        "errors": errors,
        "disclosure": (
            "Feed analytics are a secondary research signal. Automated entity, stance, and theme classification "
            "can be wrong; review original posts and saved company evidence before drawing conclusions."
        ),
    }
