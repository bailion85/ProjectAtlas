from __future__ import annotations

from typing import Any

from core.models.research import ResearchReport, utc_now
from core.services.analysis_service import AnalysisService
from core.services.report_repository import ReportRepository


COMPARISON_SERVICE_VERSION = 7


class ComparisonService:
    def __init__(self, analysis: AnalysisService, repository: ReportRepository):
        self.analysis = analysis
        self.repository = repository

    def compare(self, tickers: list[str], strategy_weights: dict[str, float]) -> dict[str, Any]:
        symbols = list(dict.fromkeys(ticker.strip().upper() for ticker in tickers if ticker.strip()))
        if not 2 <= len(symbols) <= 4:
            raise ValueError("Select between two and four unique companies.")
        macro_snapshot = self.analysis.economic_provider.snapshot()
        benchmark_history = self.analysis.provider.history("SPY")
        environment = self.analysis.event_provider.snapshot()
        from core.services.market_regime_service import analyze_market_environment
        market_environment = analyze_market_environment(environment, macro_snapshot)
        calendar_snapshot = self.analysis.calendar_provider.snapshot()
        benchmark_daily_history = self.analysis.provider.daily_history("SPY")
        reports = [
            self.analysis.analyze(
                symbol,
                strategy_weights,
                macro_snapshot=macro_snapshot,
                benchmark_history=benchmark_history,
                market_environment=market_environment,
                calendar_snapshot=calendar_snapshot,
                benchmark_daily_history=benchmark_daily_history,
            )
            for symbol in symbols
        ]
        comparison = _build_comparison(reports)
        comparison["comparison_id"] = self.repository.save_comparison(comparison)
        return comparison


def _build_comparison(reports: list[ResearchReport]) -> dict[str, Any]:
    summary = []
    for report in reports:
        periods = report.performance.get("periods", {})
        one_year = periods.get("1Y", {})
        strongest = max(report.committee_contributions, key=lambda item: item["weighted_signal"])
        weakest = min(report.committee_contributions, key=lambda item: item["weighted_signal"])
        metrics = report.company_metrics
        summary.append({
            "Rank": 0,
            "Ticker": report.ticker,
            "Company": report.company,
            "Score": report.committee_score,
            "Vote": report.committee_vote.title(),
            "Confidence": report.committee_confidence,
            "Risk score": report.risk.get("score"),
            "Risk level": report.risk.get("severity"),
            "Entry readiness": report.entry_readiness.get("score"),
            "Entry posture": report.entry_readiness.get("posture"),
            "Catalyst readiness": report.catalyst_calendar.get("readiness"),
            "Next catalyst": (report.catalyst_calendar.get("next_event") or {}).get("title"),
            "1Y return": one_year.get("company"),
            "vs S&P 500": one_year.get("relative"),
            "P/E": metrics.get("pe_ratio"),
            "Revenue growth": _percent(metrics.get("revenue_growth")),
            "Profit margin": _percent(metrics.get("profit_margin")),
            "Beta": metrics.get("beta"),
            "Strongest factor": strongest["strategy"],
            "Weakest factor": weakest["strategy"],
            "Data as of": report.data_as_of,
        })
    summary.sort(key=lambda row: row["Score"], reverse=True)
    for rank, row in enumerate(summary, start=1):
        row["Rank"] = rank

    chart_by_date: dict[str, dict[str, Any]] = {}
    for report in reports:
        for point in report.performance_history:
            chart_by_date.setdefault(point["date"], {"date": point["date"]})[report.ticker] = point["Company"]
    chart = [chart_by_date[key] for key in sorted(chart_by_date)]
    strategies = [assessment.strategy for assessment in reports[0].assessments]
    strategy_table = []
    for strategy in strategies:
        row = {"Strategy": strategy}
        for report in reports:
            assessment = next(item for item in report.assessments if item.strategy == strategy)
            row[report.ticker] = f"{assessment.vote.title()} ({assessment.confidence}%)"
        strategy_table.append(row)

    warnings = []
    dates = {report.data_as_of[:10] for report in reports}
    if len(dates) > 1:
        warnings.append("Company data have different observation dates.")
    for report in reports:
        missing = [key for key, value in report.company_metrics.items() if value is None]
        if missing:
            warnings.append(f"{report.ticker} is missing: {', '.join(missing)}.")
    return {
        "created_at": utc_now(),
        "tickers": [report.ticker for report in reports],
        "strategy_weights": reports[0].strategy_weights,
        "summary": summary,
        "strategy_table": strategy_table,
        "performance_history": chart,
        "warnings": warnings,
        "reports": [report.to_dict() for report in reports],
        "market_environment": reports[0].market_environment,
    }


def _percent(value: Any) -> float | None:
    return round(float(value) * 100, 2) if value is not None else None
