from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from core.models.research import ResearchReport


DECISION_ACCURACY_SERVICE_VERSION = 1
HORIZONS = (7, 30, 90, 365)


def build_label_snapshot(
    report: ResearchReport, guidance: dict[str, Any], trust: dict[str, Any],
    benchmark_price: float, captured_at: str | None = None,
) -> dict[str, Any]:
    return {
        "ticker": report.ticker, "report_id": report.report_id,
        "captured_at": captured_at or datetime.now(timezone.utc).isoformat(),
        "data_as_of": report.data_as_of, "label": guidance.get("Beginner view", "Research first"),
        "confidence": guidance.get("Confidence", "Low"), "evidence_score": guidance.get("Score"),
        "trust_status": trust.get("status", "Not assessed"), "trust_score": trust.get("score"),
        "market_regime": report.market_environment.get("label", "Unavailable"),
        "committee_vote": report.committee_vote.title(), "committee_score": report.committee_score,
        "start_price": float(report.company_metrics.get("price", 0)),
        "benchmark_start": float(benchmark_price), "outcomes": {},
    }


def evaluate_snapshot(
    snapshot: dict[str, Any], asset_history: list[dict[str, Any]],
    benchmark_history: list[dict[str, Any]], as_of: date | None = None,
) -> dict[str, Any]:
    as_of = as_of or date.today()
    start = _date(snapshot.get("data_as_of") or snapshot.get("captured_at"))
    asset = _series(asset_history)
    benchmark = _series(benchmark_history)
    outcomes = dict(snapshot.get("outcomes") or {})
    for horizon in HORIZONS:
        target = start + timedelta(days=horizon)
        if target > as_of:
            continue
        asset_point = _on_or_after(asset, target, as_of)
        benchmark_point = _on_or_after(benchmark, target, as_of)
        if not asset_point or not benchmark_point:
            continue
        company_return = (asset_point[1] / float(snapshot["start_price"]) - 1) * 100
        benchmark_return = (benchmark_point[1] / float(snapshot["benchmark_start"]) - 1) * 100
        relative = company_return - benchmark_return
        outcome = _label_outcome(str(snapshot.get("label")), company_return, relative)
        outcomes[str(horizon)] = {
            "horizon_days": horizon, "target_date": target.isoformat(),
            "observed_date": max(asset_point[0], benchmark_point[0]).isoformat(),
            "company_return": round(company_return, 2), "benchmark_return": round(benchmark_return, 2),
            "relative_return": round(relative, 2), "result": outcome,
            "max_drawdown": _max_drawdown(float(snapshot["start_price"]), asset, asset_point[0]),
        }
    return {**snapshot, "outcomes": outcomes, "evaluated_at": datetime.now(timezone.utc).isoformat()}


def summarize_accuracy(snapshots: list[dict[str, Any]], horizon_days: int = 30) -> dict[str, Any]:
    key = str(horizon_days)
    rows = []
    for item in snapshots:
        outcome = (item.get("outcomes") or {}).get(key)
        rows.append({
            "Ticker": item.get("ticker"), "Label": item.get("label"), "Confidence": item.get("confidence"),
            "Trust": item.get("trust_status"), "Regime": item.get("market_regime"),
            "Vote": item.get("committee_vote", "Unavailable"),
            "Captured": item.get("captured_at"), "Start price": item.get("start_price"),
            "Company return": outcome.get("company_return") if outcome else None,
            "S&P 500 return": outcome.get("benchmark_return") if outcome else None,
            "Relative return": outcome.get("relative_return") if outcome else None,
            "Max drawdown": outcome.get("max_drawdown") if outcome else None,
            "Result": outcome.get("result") if outcome else "Pending",
        })
    completed = [row for row in rows if row["Result"] not in {"Pending", "Informational"}]
    wins = sum(row["Result"] == "Success" for row in completed)
    average_return = _average(row["Company return"] for row in rows if row["Company return"] is not None)
    average_relative = _average(row["Relative return"] for row in rows if row["Relative return"] is not None)
    drawdowns = [float(row["Max drawdown"]) for row in rows if row["Max drawdown"] is not None]
    capacity = "Adequate" if len(completed) >= 30 else "Growing" if len(completed) >= 10 else "Insufficient"
    groups = []
    for field in ("Label", "Confidence", "Trust", "Regime", "Vote"):
        values = sorted({str(row[field]) for row in rows})
        for value in values:
            group = [row for row in rows if str(row[field]) == value and row["Result"] not in {"Pending", "Informational"}]
            if group:
                groups.append({
                    "Dimension": field, "Group": value, "Completed": len(group),
                    "Win rate": round(sum(row["Result"] == "Success" for row in group) / len(group) * 100, 1),
                    "Average relative return": _average(row["Relative return"] for row in group),
                })
    return {
        "created_at": datetime.now(timezone.utc).isoformat(), "horizon_days": horizon_days,
        "snapshots": len(rows), "completed_directional": len(completed), "wins": wins,
        "win_rate": round(wins / len(completed) * 100, 1) if completed else None,
        "average_return": average_return, "average_relative_return": average_relative,
        "worst_drawdown": min(drawdowns) if drawdowns else None,
        "capacity": capacity, "rows": rows, "groups": groups,
        "summary": (
            f"{len(completed)} completed directional outcome(s) at {horizon_days} days. "
            + (f"Observed win rate is {wins / len(completed) * 100:.1f}%." if completed else "More elapsed observations are required.")
        ),
        "disclosure": (
            "Historical label outcomes are descriptive, not proof of future performance. Small samples, overlapping "
            "periods, survivorship bias, and demo data can make results misleading."
        ),
    }


def _label_outcome(label: str, company_return: float, relative: float) -> str:
    if label == "Buy candidate":
        return "Success" if company_return > 0 and relative > 0 else "Miss"
    if label in {"Avoid / review", "Sell / reduce review"}:
        return "Success" if company_return < 0 or relative < 0 else "Miss"
    return "Informational"


def _date(value: Any) -> date:
    return date.fromisoformat(str(value)[:10])


def _series(history: list[dict[str, Any]]) -> list[tuple[date, float]]:
    return sorted({(_date(row["date"]), float(row["close"])) for row in history if float(row["close"]) > 0})


def _on_or_after(series: list[tuple[date, float]], target: date, as_of: date) -> tuple[date, float] | None:
    return next((point for point in series if target <= point[0] <= as_of), None)


def _max_drawdown(start_price: float, series: list[tuple[date, float]], end: date) -> float:
    peak = start_price
    drawdown = 0.0
    for observed_on, close in series:
        if observed_on > end:
            break
        peak = max(peak, close)
        drawdown = min(drawdown, close / peak - 1)
    return round(drawdown * 100, 2)


def _average(values: Any) -> float | None:
    numbers = [float(value) for value in values]
    return round(sum(numbers) / len(numbers), 2) if numbers else None
