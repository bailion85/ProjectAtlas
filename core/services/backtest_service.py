from __future__ import annotations

from datetime import date
from math import sqrt
from statistics import mean, stdev
from typing import Any


def backtest_golden_cross(
    history: list[dict[str, Any]],
    benchmark_history: list[dict[str, Any]],
    transaction_cost_bps: float = 10,
    short_window: int = 50,
    long_window: int = 200,
) -> dict[str, Any]:
    if transaction_cost_bps < 0 or transaction_cost_bps > 500:
        raise ValueError("Transaction costs must be between 0 and 500 basis points.")
    asset = _clean(history)
    benchmark = dict(_clean(benchmark_history))
    points = [(observed_on, close, benchmark[observed_on]) for observed_on, close in asset if observed_on in benchmark]
    required = long_window + 3
    if len(points) < required:
        return {
            "status": "insufficient_history", "observations": len(points), "required_observations": required,
            "message": f"At least {required} overlapping daily observations are required; {len(points)} were available.",
        }

    dates = [point[0] for point in points]
    closes = [point[1] for point in points]
    benchmark_closes = [point[2] for point in points]
    short = _rolling_average(closes, short_window)
    long = _rolling_average(closes, long_window)
    start = long_window - 1
    cost = transaction_cost_bps / 10_000
    equity = 100.0
    position = 0
    pending_position: int | None = None
    pending_signal_date: date | None = None
    strategy_returns: list[float] = []
    trades: list[dict[str, Any]] = []
    transactions = 0
    transaction_log: list[dict[str, Any]] = []
    open_trade: dict[str, Any] | None = None
    asset_base = closes[start]
    benchmark_base = benchmark_closes[start]
    curve = [{
        "date": dates[start].isoformat(), "Golden Cross strategy": 100.0,
        "Buy and hold": 100.0, "S&P 500": 100.0,
    }]

    for index in range(start + 1, len(points)):
        daily_return = closes[index] / closes[index - 1] - 1
        net_return = daily_return * position
        equity *= 1 + net_return

        if pending_position is not None and pending_position != position:
            equity *= 1 - cost
            net_return -= cost
            transactions += 1
            transaction_log.append({
                "signal": "Golden Cross" if pending_position == 1 else "Death Cross",
                "signal_date": pending_signal_date.isoformat() if pending_signal_date else "",
                "execution_date": dates[index].isoformat(),
                "price": round(closes[index], 4),
            })
            if pending_position == 1:
                open_trade = {"entry_date": dates[index].isoformat(), "entry_price": closes[index]}
            elif open_trade:
                trade_return = (closes[index] * (1 - cost)) / (open_trade["entry_price"] * (1 + cost)) - 1
                trades.append({
                    **open_trade, "exit_date": dates[index].isoformat(), "exit_price": round(closes[index], 4),
                    "return_percent": round(trade_return * 100, 2),
                })
                open_trade = None
            position = pending_position
        pending_position = None
        pending_signal_date = None
        strategy_returns.append(net_return)

        previous_difference = short[index - 1] - long[index - 1]
        current_difference = short[index] - long[index]
        if previous_difference <= 0 < current_difference:
            pending_position = 1
            pending_signal_date = dates[index]
        elif previous_difference >= 0 > current_difference:
            pending_position = 0
            pending_signal_date = dates[index]

        curve.append({
            "date": dates[index].isoformat(),
            "Golden Cross strategy": round(equity, 4),
            "Buy and hold": round(closes[index] / asset_base * 100, 4),
            "S&P 500": round(benchmark_closes[index] / benchmark_base * 100, 4),
        })

    elapsed_years = max((dates[-1] - dates[start]).days / 365.25, 1 / 365.25)
    total_return = equity - 100
    buy_hold_return = curve[-1]["Buy and hold"] - 100
    benchmark_return = curve[-1]["S&P 500"] - 100
    volatility = stdev(strategy_returns) * sqrt(252) * 100 if len(strategy_returns) > 1 else 0.0
    sharpe = mean(strategy_returns) / stdev(strategy_returns) * sqrt(252) if len(strategy_returns) > 1 and stdev(strategy_returns) else 0.0
    max_drawdown = _max_drawdown([row["Golden Cross strategy"] for row in curve])
    wins = sum(trade["return_percent"] > 0 for trade in trades)
    return {
        "status": "complete",
        "strategy": f"SMA {short_window}/{long_window} crossover",
        "execution": "Signals execute on the following trading session",
        "transaction_cost_bps": float(transaction_cost_bps),
        "observations": len(points) - start,
        "start_date": dates[start].isoformat(),
        "end_date": dates[-1].isoformat(),
        "total_return": round(total_return, 2),
        "annualized_return": round(((equity / 100) ** (1 / elapsed_years) - 1) * 100, 2),
        "buy_hold_return": round(buy_hold_return, 2),
        "benchmark_return": round(benchmark_return, 2),
        "annualized_volatility": round(volatility, 2),
        "max_drawdown": round(max_drawdown, 2),
        "sharpe_ratio": round(sharpe, 2),
        "completed_trades": len(trades),
        "transactions": transactions,
        "transaction_log": transaction_log,
        "win_rate": round(wins / len(trades) * 100, 2) if trades else 0.0,
        "open_position": bool(open_trade),
        "curve": curve,
        "trades": trades,
        "disclosure": "Illustrative historical simulation using adjusted assumptions where available; not a forecast or investment advice.",
    }


def _clean(history: list[dict[str, Any]]) -> list[tuple[date, float]]:
    values = {}
    for point in history:
        try:
            observed_on = date.fromisoformat(str(point["date"])[:10])
            close = float(point["close"])
        except (KeyError, TypeError, ValueError):
            continue
        if close > 0:
            values[observed_on] = close
    return sorted(values.items())


def _rolling_average(values: list[float], window: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    running = 0.0
    for index, value in enumerate(values):
        running += value
        if index >= window:
            running -= values[index - window]
        if index >= window - 1:
            result[index] = running / window
    return result


def _max_drawdown(values: list[float]) -> float:
    peak = values[0]
    drawdown = 0.0
    for value in values:
        peak = max(peak, value)
        drawdown = min(drawdown, value / peak - 1)
    return drawdown * 100
