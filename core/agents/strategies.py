from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from core.models.research import AgentAssessment, Evidence, Vote


@dataclass(frozen=True)
class StrategyAgent:
    name: str
    evaluator: Callable[[dict[str, Any], list[dict[str, Any]]], tuple[int, str, list[str]]]

    def assess(self, stock: dict[str, Any], news: list[dict[str, Any]]) -> AgentAssessment:
        score, thesis, labels = self.evaluator(stock, news)
        vote: Vote = "bullish" if score >= 65 else "bearish" if score <= 35 else "neutral"
        confidence = min(95, 50 + abs(score - 50))
        evidence = [
            Evidence(label=label, value=_display(stock.get(label)), source=stock["source"], observed_at=stock["observed_at"])
            for label in labels if stock.get(label) is not None
        ]
        return AgentAssessment(self.name, vote, confidence, thesis, evidence)


def _display(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _value(s: dict[str, Any], _: list[dict[str, Any]]) -> tuple[int, str, list[str]]:
    pe, pb = s.get("pe_ratio"), s.get("price_to_book")
    score = 50 + (15 if pe and pe < 20 else -10 if pe and pe > 40 else 0) + (10 if pb and pb < 3 else 0)
    return score, "Assesses valuation multiples and shareholder returns.", ["pe_ratio", "price_to_book", "return_on_equity"]


def _garp(s: dict[str, Any], _: list[dict[str, Any]]) -> tuple[int, str, list[str]]:
    growth, peg = s.get("revenue_growth"), s.get("peg_ratio")
    score = 50 + (20 if growth and growth > .15 else 8 if growth and growth > .05 else -12) + (12 if peg and 0 < peg < 2 else -5)
    return score, "Balances growth quality against the price paid for it.", ["revenue_growth", "earnings_growth", "peg_ratio"]


def _innovation(s: dict[str, Any], news: list[dict[str, Any]]) -> tuple[int, str, list[str]]:
    growth, margin = s.get("revenue_growth"), s.get("operating_margin")
    score = 50 + (18 if growth and growth > .20 else 6 if growth and growth > .08 else -8) + (8 if margin and margin > .20 else 0)
    return score, "Uses scalable growth and operating quality as observable innovation proxies.", ["revenue_growth", "operating_margin"]


def _macro(s: dict[str, Any], _: list[dict[str, Any]]) -> tuple[int, str, list[str]]:
    beta = s.get("beta")
    score = 50 + (10 if beta is not None and beta < 1 else -8 if beta and beta > 1.5 else 0)
    return score, "Estimates sensitivity to broad market conditions; macro-series integration is a later milestone.", ["beta", "sector"]


def _quant(s: dict[str, Any], _: list[dict[str, Any]]) -> tuple[int, str, list[str]]:
    price, high, low = s.get("price"), s.get("fifty_two_week_high"), s.get("fifty_two_week_low")
    position = (price - low) / (high - low) if all(v is not None for v in (price, high, low)) and high != low else .5
    score = int(35 + position * 30)
    return score, "Uses 52-week price position as a simple, transparent momentum factor.", ["price", "fifty_two_week_high", "fifty_two_week_low"]


def _risk(s: dict[str, Any], _: list[dict[str, Any]]) -> tuple[int, str, list[str]]:
    beta, margin = s.get("beta"), s.get("profit_margin")
    score = 55 + (12 if beta is not None and beta < 1 else -15 if beta and beta > 1.5 else 0) + (8 if margin and margin > .15 else -8)
    return score, "Votes bullish when operating resilience and volatility risk are favorable.", ["beta", "profit_margin", "debt_to_equity"]


def build_strategy_agents() -> list[StrategyAgent]:
    return [
        StrategyAgent("Value", _value), StrategyAgent("GARP", _garp),
        StrategyAgent("Innovation", _innovation), StrategyAgent("Macro", _macro),
        StrategyAgent("Quant", _quant), StrategyAgent("Risk", _risk),
    ]
