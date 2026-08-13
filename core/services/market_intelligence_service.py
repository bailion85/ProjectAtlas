from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


MARKET_INTELLIGENCE_SERVICE_VERSION = 1
STANCES = ("Bullish", "Neutral", "Bearish")
ARGUMENT_TYPES = ("Macro", "Technical", "Valuation", "Earnings", "Catalyst", "Risk", "Other")


def build_market_intelligence(
    ticker: str,
    sources: list[dict[str, Any]],
    commentary: list[dict[str, Any]],
    sector: str | None = None,
    now: datetime | None = None,
    max_age_days: int = 30,
) -> dict[str, Any]:
    """Create an advisory analyst-consensus vote from curated saved commentary."""
    symbol = ticker.strip().upper()
    if not symbol:
        raise ValueError("Ticker is required.")
    now = now or datetime.now(timezone.utc)
    source_map = {str(item.get("id")): item for item in sources if item.get("id")}
    rows = []
    for item in commentary:
        if str(item.get("ticker", "")).strip().upper() != symbol:
            continue
        source = source_map.get(str(item.get("source_id")))
        if not source:
            continue
        observed = _datetime(item.get("published_at"))
        age = max(0.0, (now - observed).total_seconds() / 86400)
        if age > max_age_days:
            continue
        stance = str(item.get("stance", "Neutral")).title()
        if stance not in STANCES:
            continue
        credibility = _score(source.get("credibility", 50))
        influence = _score(source.get("influence", 50))
        conviction = _score(item.get("conviction", 50))
        expertise = _expertise(source, sector)
        recency = max(0.1, 1 - age / max_age_days)
        base_weight = credibility / 100 * expertise / 100 * conviction / 100 * recency
        direction = {"Bullish": 1, "Neutral": 0, "Bearish": -1}[stance]
        rows.append({
            "Analyst": source.get("name", "Unknown"), "Platform": source.get("platform", "Other"),
            "Stance": stance, "Conviction": conviction, "Credibility": credibility,
            "Influence": influence, "Expertise fit": expertise, "Age (days)": round(age, 1),
            "Argument": item.get("argument_type", "Other"), "Theme": item.get("theme", "Unclassified"),
            "Commentary": item.get("text", ""), "Source URL": item.get("url", ""),
            "weight": base_weight, "predictive_signal": direction * base_weight,
            "influence_signal": direction * base_weight * influence / 100,
        })
    total_weight = sum(row["weight"] for row in rows)
    predictive = sum(row["predictive_signal"] for row in rows) / total_weight if total_weight else 0.0
    influence_weight = sum(row["weight"] * row["Influence"] / 100 for row in rows)
    influence = sum(row["influence_signal"] for row in rows) / influence_weight if influence_weight else 0.0
    vote = "Bullish" if predictive >= .2 else "Bearish" if predictive <= -.2 else "Neutral"
    confidence = round(min(95, 40 + abs(predictive) * 40 + min(len(rows), 5) * 3)) if rows else 0
    counts = {stance: sum(row["Stance"] == stance for row in rows) for stance in STANCES}
    themes = _themes(rows)
    display_rows = [{key: value for key, value in row.items() if key not in {
        "weight", "predictive_signal", "influence_signal"
    }} for row in sorted(rows, key=lambda row: (-row["weight"], row["Age (days)"]))]
    warnings = []
    if len(rows) < 3:
        warnings.append("Fewer than three current commentary items are available; treat the vote as preliminary.")
    if len({row["Analyst"] for row in rows}) < 2:
        warnings.append("The signal lacks independent-source confirmation.")
    return {
        "ticker": symbol, "vote": vote, "confidence": confidence,
        "signal_score": round((predictive + 1) * 50, 1),
        "influence_score": round((influence + 1) * 50, 1),
        "bullish": counts["Bullish"], "neutral": counts["Neutral"], "bearish": counts["Bearish"],
        "analysts": len({row["Analyst"] for row in rows}), "items": len(rows),
        "themes": themes, "rows": display_rows, "warnings": warnings,
        "summary": (
            f"Curated analyst commentary is {vote.lower()} for {symbol} with {confidence}% confidence. "
            f"Consensus is {counts['Bullish']} bullish / {counts['Neutral']} neutral / {counts['Bearish']} bearish."
        ),
        "disclosure": (
            "Market Intelligence is an advisory social/analyst signal, not a trading instruction. "
            "Credibility and influence are user-maintained estimates and are not verified performance statistics."
        ),
    }


def validate_source(source: dict[str, Any]) -> dict[str, Any]:
    name = str(source.get("name", "")).strip()
    if not name:
        raise ValueError("Analyst name is required.")
    return {
        "id": str(source.get("id") or _slug(name)), "name": name,
        "platform": str(source.get("platform", "Other")).strip() or "Other",
        "handle": str(source.get("handle", "")).strip(),
        "credibility": _score(source.get("credibility", 50)),
        "influence": _score(source.get("influence", 50)),
        "expertise": [str(value).strip() for value in source.get("expertise", []) if str(value).strip()],
    }


def validate_commentary(item: dict[str, Any], source_ids: set[str]) -> dict[str, Any]:
    source_id = str(item.get("source_id", ""))
    if source_id not in source_ids:
        raise ValueError("Choose a saved analyst source.")
    ticker = str(item.get("ticker", "")).strip().upper()
    text = str(item.get("text", "")).strip()
    if not ticker or not text:
        raise ValueError("Ticker and commentary are required.")
    stance = str(item.get("stance", "Neutral")).title()
    if stance not in STANCES:
        raise ValueError("Choose a valid stance.")
    return {
        "id": str(item.get("id") or f"{source_id}-{ticker}-{datetime.now(timezone.utc).timestamp():.0f}"),
        "source_id": source_id, "ticker": ticker, "published_at": _datetime(item.get("published_at")).isoformat(),
        "stance": stance, "conviction": _score(item.get("conviction", 50)),
        "argument_type": str(item.get("argument_type", "Other")),
        "theme": str(item.get("theme", "Unclassified")).strip() or "Unclassified",
        "text": text, "url": str(item.get("url", "")).strip(),
    }


def _score(value: Any) -> int:
    try:
        return max(0, min(100, round(float(value))))
    except (TypeError, ValueError) as exc:
        raise ValueError("Scores must be numeric values from 0 to 100.") from exc


def _datetime(value: Any) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    observed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return observed.replace(tzinfo=timezone.utc) if observed.tzinfo is None else observed.astimezone(timezone.utc)


def _expertise(source: dict[str, Any], sector: str | None) -> int:
    expertise = {str(value).strip().lower() for value in source.get("expertise", [])}
    if not expertise or not sector:
        return 70
    return 100 if sector.strip().lower() in expertise else 55


def _themes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    themes: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        themes.setdefault(str(row["Theme"]), []).append(row)
    return [{
        "Theme": theme, "Mentions": len(items),
        "Net stance": round(sum(item["predictive_signal"] for item in items) / sum(item["weight"] for item in items), 2),
    } for theme, items in sorted(themes.items(), key=lambda pair: (-len(pair[1]), pair[0]))]


def _slug(value: str) -> str:
    return "-".join("".join(character.lower() if character.isalnum() else " " for character in value).split())
