from __future__ import annotations

from typing import Any


DISCOVERY_MONITOR_SERVICE_VERSION = 1
LABEL_ORDER = {"Pass for now": 0, "Price-only lead": 1, "Worth watching": 2,
               "SEC-supported lead": 3, "Strong research candidate": 4}


def compare_discovery_runs(
    previous: dict[str, Any] | None, current: dict[str, Any],
    rank_threshold: int = 2, score_threshold: float = 5,
) -> dict[str, Any]:
    previous_rows = {row["Ticker"]: row for row in (previous or {}).get("rows", [])}
    current_rows = {row["Ticker"]: row for row in current.get("rows", [])}
    events = []
    for ticker, row in current_rows.items():
        old = previous_rows.get(ticker)
        if old is None:
            events.append(_event(ticker, "New candidate", "Moderate", None, row.get("Rank"), None,
                                 row.get("Discovery score"), f"Entered at #{row.get('Rank')} as {row.get('Research label')}."))
            continue
        old_rank, new_rank = _integer(old.get("Rank")), _integer(row.get("Rank"))
        old_score, new_score = _number(old.get("Discovery score")), _number(row.get("Discovery score"))
        rank_change = old_rank - new_rank if old_rank is not None and new_rank is not None else None
        score_change = new_score - old_score if old_score is not None and new_score is not None else None
        old_label, new_label = str(old.get("Research label", "")), str(row.get("Research label", ""))
        if LABEL_ORDER.get(new_label, 0) != LABEL_ORDER.get(old_label, 0):
            upgraded = LABEL_ORDER.get(new_label, 0) > LABEL_ORDER.get(old_label, 0)
            events.append(_event(ticker, "Evidence upgrade" if upgraded else "Evidence downgrade",
                                 "High" if upgraded else "Moderate", old_rank, new_rank, old_score, new_score,
                                 f"Label changed from {old_label or 'Unknown'} to {new_label or 'Unknown'}."))
        elif rank_change is not None and abs(rank_change) >= rank_threshold:
            direction = "rose" if rank_change > 0 else "fell"
            events.append(_event(ticker, "Rank change", "Moderate", old_rank, new_rank, old_score, new_score,
                                 f"Rank {direction} from #{old_rank} to #{new_rank}."))
        elif score_change is not None and abs(score_change) >= score_threshold:
            events.append(_event(ticker, "Score change", "Moderate", old_rank, new_rank, old_score, new_score,
                                 f"Discovery score changed {score_change:+.1f} points."))
    for ticker, row in previous_rows.items():
        if ticker not in current_rows:
            events.append(_event(ticker, "Left screen", "Low", row.get("Rank"), None,
                                 row.get("Discovery score"), None, "No longer appears in the current candidate set."))
    order = {"High": 0, "Moderate": 1, "Low": 2}
    events.sort(key=lambda item: (order.get(item["Severity"], 9), item["Ticker"], item["Change"]))
    return {
        "has_baseline": previous is not None,
        "previous_run_id": (previous or {}).get("id"),
        "events": events,
        "new_candidates": sum(item["Change"] == "New candidate" for item in events),
        "upgrades": sum(item["Change"] == "Evidence upgrade" for item in events),
        "downgrades": sum(item["Change"] == "Evidence downgrade" for item in events),
        "removed": sum(item["Change"] == "Left screen" for item in events),
        "summary": "Baseline created; future scans will show changes." if previous is None else
                   f"Detected {len(events)} meaningful change(s) versus discovery run #{previous.get('id', 'previous')}.",
    }


def discovery_alerts(monitor: dict[str, Any], run_id: int | None = None) -> list[dict[str, Any]]:
    alerts = []
    for item in monitor.get("events", []):
        if item["Change"] not in {"New candidate", "Evidence upgrade", "Evidence downgrade"}:
            continue
        ticker = item["Ticker"]
        alerts.append({
            "ticker": ticker, "alert_type": "discovery", "severity": item["Severity"],
            "title": f"{ticker}: {item['Change'].lower()}", "message": item["Details"],
            "fingerprint": f"discovery:{run_id or 'pending'}:{ticker}:{item['Change']}",
            "payload": {**item, "discovery_run_id": run_id},
        })
    return alerts


def _event(ticker: str, change: str, severity: str, old_rank: Any, new_rank: Any,
           old_score: Any, new_score: Any, details: str) -> dict[str, Any]:
    return {"Ticker": ticker, "Change": change, "Severity": severity,
            "Previous rank": old_rank, "Current rank": new_rank,
            "Previous score": old_score, "Current score": new_score, "Details": details}


def _number(value: Any) -> float | None:
    try: return float(value) if value is not None else None
    except (TypeError, ValueError): return None


def _integer(value: Any) -> int | None:
    try: return int(value) if value is not None else None
    except (TypeError, ValueError): return None
