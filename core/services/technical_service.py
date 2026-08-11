from __future__ import annotations

from typing import Any


def analyze_golden_cross(
    history: list[dict[str, Any]], short_window: int = 50, long_window: int = 200
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Calculate moving averages and identify the latest 50/200-day crossover."""
    cleaned = sorted(
        (
            {"date": str(point["date"]), "close": float(point["close"])}
            for point in history
            if point.get("date") and point.get("close") is not None
        ),
        key=lambda point: point["date"],
    )
    required = long_window + 1
    if len(cleaned) < required:
        return ({
            "status": "insufficient_history",
            "label": "Insufficient history",
            "observations": len(cleaned),
            "required_observations": required,
            "short_window": short_window,
            "long_window": long_window,
            "message": f"At least {required} daily closes are required; {len(cleaned)} were available.",
        }, [])

    closes = [point["close"] for point in cleaned]
    short = _rolling_average(closes, short_window)
    long = _rolling_average(closes, long_window)
    chart = []
    latest_cross = None
    previous_difference = None
    for index, point in enumerate(cleaned):
        row = {"date": point["date"], "Price": round(point["close"], 4)}
        if short[index] is not None:
            row[f"SMA {short_window}"] = round(short[index], 4)
        if long[index] is not None:
            row[f"SMA {long_window}"] = round(long[index], 4)
        if short[index] is not None and long[index] is not None:
            difference = short[index] - long[index]
            if previous_difference is not None:
                if previous_difference <= 0 < difference:
                    latest_cross = {"type": "golden_cross", "label": "Golden Cross", "date": point["date"]}
                elif previous_difference >= 0 > difference:
                    latest_cross = {"type": "death_cross", "label": "Death Cross", "date": point["date"]}
            previous_difference = difference
        chart.append(row)

    latest_short = short[-1]
    latest_long = long[-1]
    spread = ((latest_short / latest_long) - 1) * 100
    state = "bullish" if latest_short > latest_long else "bearish" if latest_short < latest_long else "neutral"
    result = {
        "status": state,
        "label": f"{state.title()} trend",
        "observations": len(cleaned),
        "required_observations": required,
        "short_window": short_window,
        "long_window": long_window,
        "sma_50": round(latest_short, 4),
        "sma_200": round(latest_long, 4),
        "short_average": round(latest_short, 4),
        "long_average": round(latest_long, 4),
        "spread_percent": round(spread, 3),
        "price": round(closes[-1], 4),
        "price_vs_sma_50_percent": round(((closes[-1] / latest_short) - 1) * 100, 3),
        "latest_cross": latest_cross,
        "message": (
            f"The 50-day average is {abs(spread):.2f}% "
            f"{'above' if spread >= 0 else 'below'} the 200-day average."
        ),
    }
    return result, chart[-260:]


def _rolling_average(values: list[float], window: int) -> list[float | None]:
    averages: list[float | None] = [None] * len(values)
    running = 0.0
    for index, value in enumerate(values):
        running += value
        if index >= window:
            running -= values[index - window]
        if index >= window - 1:
            averages[index] = running / window
    return averages
