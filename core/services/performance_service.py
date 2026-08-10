from __future__ import annotations

from datetime import date, timedelta
from math import sqrt
from statistics import stdev
from typing import Any


WINDOWS = {"1M": 30, "6M": 182, "1Y": 365, "5Y": 1826}


def analyze_performance(
    history: list[dict[str, Any]],
    benchmark_history: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    asset = _clean(history)
    benchmark = _clean(benchmark_history)
    if len(asset) < 2 or len(benchmark) < 2:
        raise ValueError("At least two historical observations are required.")

    periods = {}
    for label, days in WINDOWS.items():
        asset_return = _window_return(asset, days)
        benchmark_return = _window_return(benchmark, days)
        periods[label] = {
            "company": asset_return,
            "benchmark": benchmark_return,
            "relative": round(asset_return - benchmark_return, 2),
        }

    monthly_returns = [asset[index][1] / asset[index - 1][1] - 1 for index in range(1, len(asset))]
    volatility = stdev(monthly_returns) * sqrt(12) * 100 if len(monthly_returns) > 1 else 0.0
    peak = asset[0][1]
    max_drawdown = 0.0
    for _, close in asset:
        peak = max(peak, close)
        max_drawdown = min(max_drawdown, close / peak - 1)

    benchmark_by_date = dict(benchmark)
    common_dates = [observed_on for observed_on, _ in asset if observed_on in benchmark_by_date]
    if len(common_dates) < 2:
        raise ValueError("Company and benchmark histories do not overlap.")
    asset_by_date = dict(asset)
    asset_base = asset_by_date[common_dates[0]]
    benchmark_base = benchmark_by_date[common_dates[0]]
    chart = [
        {
            "date": observed_on.isoformat(),
            "Company": round(asset_by_date[observed_on] / asset_base * 100, 2),
            "S&P 500": round(benchmark_by_date[observed_on] / benchmark_base * 100, 2),
        }
        for observed_on in common_dates
    ]
    metrics = {
        "periods": periods,
        "annualized_volatility": round(volatility, 2),
        "max_drawdown": round(max_drawdown * 100, 2),
        "observations": len(asset),
    }
    return metrics, chart


def _clean(history: list[dict[str, Any]]) -> list[tuple[date, float]]:
    points = {(date.fromisoformat(str(point["date"])[:10]), float(point["close"])) for point in history}
    return sorted((observed_on, close) for observed_on, close in points if close > 0)


def _window_return(points: list[tuple[date, float]], days: int) -> float:
    end_date, end_close = points[-1]
    target = end_date - timedelta(days=days)
    candidates = [point for point in points if point[0] <= target]
    start_close = (candidates[-1] if candidates else points[0])[1]
    return round((end_close / start_close - 1) * 100, 2)
