from __future__ import annotations

from dataclasses import replace

from core.agents import build_strategy_agents
from core.models.research import ResearchReport, utc_now
from core.providers.market_provider import MarketDataProvider
from core.providers.economic_provider import DemoEconomicProvider, EconomicDataProvider
from core.services.committee_service import CommitteeService, normalize_weights, score_contributions
from core.services.report_repository import ReportRepository
from core.services.performance_service import analyze_performance


class AnalysisService:
    def __init__(self, provider: MarketDataProvider, repository: ReportRepository, economic_provider: EconomicDataProvider | None = None):
        self.provider = provider
        self.repository = repository
        self.economic_provider = economic_provider or DemoEconomicProvider()

    def analyze(
        self,
        ticker: str,
        strategy_weights: dict[str, float] | None = None,
        macro_snapshot: dict | None = None,
        benchmark_history: list[dict] | None = None,
    ) -> ResearchReport:
        stock = self.provider.snapshot(ticker)
        news = self.provider.news(ticker)
        macro = macro_snapshot or self.economic_provider.snapshot()
        performance, performance_history = analyze_performance(
            self.provider.history(stock["symbol"]), benchmark_history or self.provider.history("SPY")
        )
        one_year = performance["periods"]["1Y"]
        stock.update({
            "return_1y": one_year["company"],
            "relative_return_1y": one_year["relative"],
            "annualized_volatility": performance["annualized_volatility"],
            "max_drawdown": performance["max_drawdown"],
            "macro": macro,
        })
        for key, indicator in macro["indicators"].items():
            stock[f"macro_{key}"] = indicator["value"]
        assessments = [agent.assess(stock, news) for agent in build_strategy_agents()]
        normalized_weights = normalize_weights(strategy_weights)
        vote, confidence, contributions = CommitteeService().decide(assessments, normalized_weights)
        bullish = [a for a in assessments if a.vote == "bullish"]
        bearish = [a for a in assessments if a.vote == "bearish"]
        report = ResearchReport(
            ticker=stock["symbol"], company=stock["name"], created_at=utc_now(),
            data_as_of=stock["observed_at"],
            executive_summary=f"The six-strategy committee is {vote} with {confidence}% confidence. This is research, not investment advice.",
            bull_case=[a.thesis for a in bullish] or ["No strategy produced a bullish vote."],
            bear_case=[a.thesis for a in bearish] or ["No strategy produced a bearish vote."],
            risks=_risks(stock), catalysts=_catalysts(stock, news), assessments=assessments,
            committee_vote=vote, committee_confidence=confidence, provider=self.provider.name,
            performance=performance, performance_history=performance_history,
            macro=macro,
            strategy_weights=normalized_weights,
            committee_contributions=contributions,
            committee_score=score_contributions(contributions),
            company_metrics={key: stock.get(key) for key in (
                "price", "pe_ratio", "forward_pe", "peg_ratio", "profit_margin",
                "operating_margin", "return_on_equity", "revenue_growth",
                "earnings_growth", "beta", "sector", "industry",
            )},
        )
        report_id = self.repository.save(report)
        return replace(report, report_id=report_id)


def _risks(stock: dict) -> list[str]:
    risks = []
    if stock.get("pe_ratio") and stock["pe_ratio"] > 40:
        risks.append("Elevated valuation may amplify downside if expectations reset.")
    if stock.get("beta") and stock["beta"] > 1.5:
        risks.append("High historical beta indicates above-market price volatility.")
    if stock.get("profit_margin") is not None and stock["profit_margin"] < .05:
        risks.append("Thin profit margins reduce operating resilience.")
    return risks or ["Provider data is incomplete; qualitative, balance-sheet, and event risks require further review."]


def _catalysts(stock: dict, news: list[dict]) -> list[str]:
    catalysts = []
    if stock.get("revenue_growth") and stock["revenue_growth"] > .15:
        catalysts.append("Sustained double-digit revenue growth could support upward revisions.")
    catalysts.extend(item["title"] for item in news[:3] if item.get("title"))
    return catalysts or ["No verified catalyst was available from the configured data provider."]
