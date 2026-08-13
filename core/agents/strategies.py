from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from core.models.research import AgentAssessment, Evidence, Vote
from core.services.macro_service import score_macro_environment

STRATEGY_AGENTS_VERSION = 2


@dataclass(frozen=True)
class StrategyAgent:
    name: str
    evaluator: Callable[[dict[str, Any], list[dict[str, Any]]], tuple[int, str, list[str]]]

    def assess(self, stock: dict[str, Any], news: list[dict[str, Any]]) -> AgentAssessment:
        score, thesis, labels = self.evaluator(stock, news)
        vote: Vote = "bullish" if score >= 65 else "bearish" if score <= 35 else "neutral"
        confidence = min(95, 50 + abs(score - 50))
        evidence = [_evidence(stock, label) for label in labels if stock.get(label) is not None]
        return AgentAssessment(self.name, vote, confidence, thesis, evidence)


def _display(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _evidence(stock: dict[str, Any], label: str) -> Evidence:
    if label.startswith("macro_"):
        indicator = stock["macro"]["indicators"][label.removeprefix("macro_")]
        return Evidence(
            label=indicator["label"],
            value=f"{indicator['value']:.2f} {indicator['unit']}",
            source=f"{indicator['source']} · {indicator['series_id']}",
            observed_at=indicator["observed_at"],
        )
    if label == "market_environment_score":
        environment = stock["market_environment"]
        return Evidence(
            label="Market environment score",
            value=f"{environment['score']:.1f}/100 ({environment['label']})",
            source=environment["event_provider"],
            observed_at=environment["data_as_of"],
        )
    return Evidence(
        label=label,
        value=_display(stock.get(label)),
        source=stock["source"],
        observed_at=stock["observed_at"],
    )


def _value(s: dict[str, Any], _: list[dict[str, Any]]) -> tuple[int, str, list[str]]:
    if s.get("asset_type") == "ETF":
        relative, drawdown = s.get("relative_return_1y", 0), s.get("max_drawdown", -20)
        score = 50 + (12 if relative > 5 else 5 if relative > 0 else -8) + (7 if drawdown > -20 else -7)
        return score, "Evaluates ETF relative value through benchmark performance and drawdown rather than company P/E ratios.", ["relative_return_1y", "max_drawdown"]
    pe, pb = s.get("pe_ratio"), s.get("price_to_book")
    score = 50 + (15 if pe and pe < 20 else -10 if pe and pe > 40 else 0) + (10 if pb and pb < 3 else 0)
    return score, "Assesses valuation multiples and shareholder returns.", ["pe_ratio", "price_to_book", "return_on_equity"]


def _garp(s: dict[str, Any], _: list[dict[str, Any]]) -> tuple[int, str, list[str]]:
    if s.get("asset_type") == "ETF":
        annual_return, relative = s.get("return_1y", 0), s.get("relative_return_1y", 0)
        score = 50 + (14 if annual_return > 10 else 6 if annual_return > 0 else -10) + (8 if relative > 0 else -5)
        return score, "Uses ETF absolute and benchmark-relative returns as growth-at-a-reasonable-risk proxies.", ["return_1y", "relative_return_1y"]
    growth, peg = s.get("revenue_growth"), s.get("peg_ratio")
    score = 50 + (20 if growth and growth > .15 else 8 if growth and growth > .05 else -12) + (12 if peg and 0 < peg < 2 else -5)
    return score, "Balances growth quality against the price paid for it.", ["revenue_growth", "earnings_growth", "peg_ratio"]


def _innovation(s: dict[str, Any], news: list[dict[str, Any]]) -> tuple[int, str, list[str]]:
    if s.get("asset_type") == "ETF":
        relative, volatility = s.get("relative_return_1y", 0), s.get("annualized_volatility", 30)
        score = 50 + (15 if relative > 8 else 6 if relative > 0 else -8) + (6 if volatility < 30 else -5 if volatility > 45 else 0)
        return score, "Measures whether the ETF theme is delivering benchmark-relative performance without excessive volatility.", ["relative_return_1y", "annualized_volatility"]
    growth, margin = s.get("revenue_growth"), s.get("operating_margin")
    score = 50 + (18 if growth and growth > .20 else 6 if growth and growth > .08 else -8) + (8 if margin and margin > .20 else 0)
    return score, "Uses scalable growth and operating quality as observable innovation proxies.", ["revenue_growth", "operating_margin"]


def _macro(s: dict[str, Any], _: list[dict[str, Any]]) -> tuple[int, str, list[str]]:
    macro_score, thesis = score_macro_environment(s.get("sector"), s["macro"])
    environment = s.get("market_environment", {})
    score = round(macro_score * .6 + environment.get("score", macro_score) * .4)
    thesis += " " + environment.get("buying_context", "")
    return score, thesis, ["market_environment_score", "macro_inflation", "macro_policy_rate", "macro_treasury_10y", "macro_unemployment", "macro_gdp_growth", "macro_oil_wti"]


def _quant(s: dict[str, Any], _: list[dict[str, Any]]) -> tuple[int, str, list[str]]:
    relative = s.get("relative_return_1y", 0)
    drawdown = s.get("max_drawdown", -20)
    volatility = s.get("annualized_volatility", 25)
    score = 50 + (15 if relative > 10 else 7 if relative > 0 else -12)
    score += 8 if drawdown > -15 else -8 if drawdown < -30 else 0
    score += 7 if volatility < 25 else -7 if volatility > 45 else 0
    return max(0, min(100, score)), "Measures benchmark-relative momentum, volatility, and drawdown over historical prices.", ["return_1y", "relative_return_1y", "annualized_volatility", "max_drawdown"]


def _risk(s: dict[str, Any], _: list[dict[str, Any]]) -> tuple[int, str, list[str]]:
    if s.get("asset_type") == "ETF":
        volatility, drawdown = s.get("annualized_volatility", 30), s.get("max_drawdown", -20)
        score = 55 + (12 if volatility < 22 else -12 if volatility > 40 else 0) + (10 if drawdown > -15 else -10 if drawdown < -30 else 0)
        return score, "Votes on ETF volatility and drawdown resilience instead of company balance-sheet ratios.", ["annualized_volatility", "max_drawdown"]
    beta, margin = s.get("beta"), s.get("profit_margin")
    score = 55 + (12 if beta is not None and beta < 1 else -15 if beta and beta > 1.5 else 0) + (8 if margin and margin > .15 else -8)
    return score, "Votes bullish when operating resilience and volatility risk are favorable.", ["beta", "profit_margin", "debt_to_equity"]


def build_strategy_agents() -> list[StrategyAgent]:
    return [
        StrategyAgent("Value", _value), StrategyAgent("GARP", _garp),
        StrategyAgent("Innovation", _innovation), StrategyAgent("Macro", _macro),
        StrategyAgent("Quant", _quant), StrategyAgent("Risk", _risk),
    ]
