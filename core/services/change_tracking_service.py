from __future__ import annotations

from typing import Any

from core.models.research import ResearchReport


CHANGE_TRACKING_SERVICE_VERSION = 1


def compare_reports(current: ResearchReport, previous: ResearchReport) -> dict[str, Any]:
    if current.ticker != previous.ticker:
        raise ValueError("Change tracking requires two reports for the same ticker.")
    metrics = [
        _metric("Committee score", previous.committee_score, current.committee_score, "points", True),
        _metric("Committee confidence", previous.committee_confidence, current.committee_confidence, "points", True),
        _metric("Risk score", _path(previous.risk, "score", 50), _path(current.risk, "score", 50), "points", False),
        _metric("Entry readiness", _path(previous.entry_readiness, "score", 50), _path(current.entry_readiness, "score", 50), "points", True),
        _metric("Market environment", _path(previous.market_environment, "score", 50), _path(current.market_environment, "score", 50), "points", True),
        _metric("1Y vs S&P 500", _relative(previous), _relative(current), "pp", True),
        _metric("Moving-average spread", _path(previous.technical, "spread_percent", 0), _path(current.technical, "spread_percent", 0), "%", True),
    ]
    state_changes = []
    _state(state_changes, "Committee vote", previous.committee_vote.title(), current.committee_vote.title())
    _state(state_changes, "Risk level", previous.risk.get("severity", "Unavailable"), current.risk.get("severity", "Unavailable"))
    _state(state_changes, "Entry posture", previous.entry_readiness.get("posture", "Unavailable"), current.entry_readiness.get("posture", "Unavailable"))
    _state(state_changes, "Market posture", previous.market_environment.get("label", "Unavailable"), current.market_environment.get("label", "Unavailable"))
    _state(state_changes, "Technical trend", previous.technical.get("label", "Unavailable"), current.technical.get("label", "Unavailable"))
    _state(state_changes, "Next catalyst", _next_catalyst(previous), _next_catalyst(current))

    added_risks, removed_risks = _list_changes(previous.risks, current.risks)
    added_catalysts, removed_catalysts = _list_changes(previous.catalysts, current.catalysts)
    thesis_status, thesis_score, reasons = _thesis_status(current, previous, metrics, state_changes)
    material = _material_changes(metrics, state_changes, added_risks, removed_risks, added_catalysts, removed_catalysts)
    summary = _summary(current.ticker, thesis_status, material)
    return {
        "ticker": current.ticker,
        "company": current.company,
        "current_report_id": current.report_id,
        "previous_report_id": previous.report_id,
        "current_created_at": current.created_at,
        "previous_created_at": previous.created_at,
        "thesis_status": thesis_status,
        "thesis_score": thesis_score,
        "summary": summary,
        "reasons": reasons,
        "metrics": metrics,
        "state_changes": state_changes,
        "added_risks": added_risks,
        "removed_risks": removed_risks,
        "added_catalysts": added_catalysts,
        "removed_catalysts": removed_catalysts,
        "material_changes": material,
        "disclosure": "Change tracking compares saved Atlas research snapshots. It is not investment advice or a recommendation to trade.",
    }


def _metric(label: str, previous: Any, current: Any, unit: str, higher_is_better: bool) -> dict[str, Any]:
    before = float(previous)
    after = float(current)
    delta = round(after - before, 2)
    impact = "Neutral"
    threshold = 1 if unit == "points" else .5
    if abs(delta) >= threshold:
        favorable = delta > 0 if higher_is_better else delta < 0
        impact = "Favorable" if favorable else "Unfavorable"
    return {
        "Metric": label, "Previous": round(before, 2), "Current": round(after, 2),
        "Change": delta, "Unit": unit, "Impact": impact,
    }


def _state(rows: list[dict[str, str]], factor: str, previous: str, current: str) -> None:
    if previous != current:
        rows.append({"Factor": factor, "Previous": previous, "Current": current})


def _thesis_status(
    current: ResearchReport, previous: ResearchReport, metrics: list[dict[str, Any]], states: list[dict[str, str]],
) -> tuple[str, float, list[str]]:
    values = {item["Metric"]: item["Change"] for item in metrics}
    score = round(
        values["Committee score"] * .30 + values["Entry readiness"] * .25
        - values["Risk score"] * .25 + values["Market environment"] * .15
        + values["Moving-average spread"] * .05,
        1,
    )
    reasons = []
    if values["Committee score"]:
        reasons.append(f"Committee score moved {values['Committee score']:+.1f} points.")
    if values["Risk score"]:
        reasons.append(f"Risk moved {values['Risk score']:+.1f} points.")
    if values["Entry readiness"]:
        reasons.append(f"Entry readiness moved {values['Entry readiness']:+.1f} points.")
    invalidated = (
        (previous.committee_vote == "bullish" and current.committee_vote == "bearish")
        or values["Risk score"] >= 15 or values["Entry readiness"] <= -15
        or (previous.technical.get("label") == "Bullish" and current.technical.get("label") == "Bearish")
    )
    if invalidated:
        reasons.insert(0, "A major invalidation threshold was crossed.")
        return "Invalidated", score, reasons
    if score >= 4:
        return "Strengthening", score, reasons or ["The weighted evidence improved."]
    if score <= -4:
        return "Weakening", score, reasons or ["The weighted evidence weakened."]
    if states:
        reasons.append("State labels changed, but the weighted evidence remained within the unchanged range.")
    return "Unchanged", score, reasons or ["No material evidence movement was detected."]


def _material_changes(
    metrics: list[dict[str, Any]], states: list[dict[str, str]], added_risks: list[str], removed_risks: list[str],
    added_catalysts: list[str], removed_catalysts: list[str],
) -> list[dict[str, str]]:
    rows = []
    for item in metrics:
        threshold = 5 if item["Metric"] != "Moving-average spread" else 2
        if abs(item["Change"]) >= threshold:
            rows.append({
                "Category": "Metric", "Change": item["Metric"], "Impact": item["Impact"],
                "Details": f"{item['Previous']:.1f} to {item['Current']:.1f} ({item['Change']:+.1f} {item['Unit']}).",
            })
    for item in states:
        rows.append({"Category": "State", "Change": item["Factor"], "Impact": "Changed", "Details": f"{item['Previous']} to {item['Current']}."})
    for label, values, impact in (
        ("Risk added", added_risks, "Unfavorable"), ("Risk removed", removed_risks, "Favorable"),
        ("Catalyst added", added_catalysts, "Favorable"), ("Catalyst removed", removed_catalysts, "Unfavorable"),
    ):
        rows.extend({"Category": "Evidence", "Change": label, "Impact": impact, "Details": value} for value in values)
    return rows


def _summary(ticker: str, status: str, changes: list[dict[str, str]]) -> str:
    if not changes:
        return f"{ticker}'s thesis is unchanged; no material report-to-report movement was detected."
    leading = "; ".join(f"{item['Change']}: {item['Details']}" for item in changes[:3])
    return f"{ticker}'s thesis is {status.lower()}. Key changes: {leading}"


def _list_changes(previous: list[str], current: list[str]) -> tuple[list[str], list[str]]:
    previous_map = {item.strip().lower(): item for item in previous}
    current_map = {item.strip().lower(): item for item in current}
    added = [current_map[key] for key in current_map.keys() - previous_map.keys()]
    removed = [previous_map[key] for key in previous_map.keys() - current_map.keys()]
    return sorted(added), sorted(removed)


def _relative(report: ResearchReport) -> float:
    return float(report.performance.get("periods", {}).get("1Y", {}).get("relative", 0))


def _next_catalyst(report: ResearchReport) -> str:
    return str((report.catalyst_calendar.get("next_event") or {}).get("title") or "Unavailable")


def _path(data: dict[str, Any], key: str, default: float) -> float:
    try:
        return float(data.get(key, default))
    except (TypeError, ValueError):
        return default
