from __future__ import annotations

from html import escape
from io import BytesIO
from typing import Any

from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import LETTER, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


NAVY = colors.HexColor("#14213D")
BLUE = colors.HexColor("#2F6690")
GOLD = colors.HexColor("#D8A31A")
PALE_BLUE = colors.HexColor("#EAF2F8")
PALE_GOLD = colors.HexColor("#FFF6DD")
LIGHT = colors.HexColor("#F4F6F8")
MUTED = colors.HexColor("#5E6B78")
GREEN = colors.HexColor("#287A55")
RED = colors.HexColor("#A94442")


def render_report_pdf(report: Any) -> bytes:
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=LETTER,
        rightMargin=0.55 * inch,
        leftMargin=0.55 * inch,
        topMargin=0.72 * inch,
        bottomMargin=0.62 * inch,
        title=f"Atlas Research Report - {_get(report, 'ticker', '')}",
        author="Project Atlas",
    )
    styles = _styles()
    story = []
    ticker = _get(report, "ticker", "")
    company = _get(report, "company", ticker)
    story.extend([
        Paragraph("PROJECT ATLAS", styles["eyebrow"]),
        Paragraph(_text(f"{company} ({ticker})"), styles["title"]),
        Paragraph("Evidence-based investment research report", styles["subtitle"]),
        HRFlowable(width="100%", thickness=2, color=GOLD, spaceBefore=5, spaceAfter=12),
    ])
    story.append(_summary_table(report, styles, document.width))
    story.append(Spacer(1, 10))
    story.append(Paragraph(_text(_get(report, "executive_summary", "")), styles["body"]))

    readiness = _get(report, "entry_readiness", {})
    if readiness:
        story.append(_section("Entry readiness", styles))
        story.append(Paragraph(_text(readiness.get("summary", "")), styles["body"]))
        readiness_rows = [["Factor", "Score", "Weight", "Evidence"]] + [
            [item.get("factor", ""), "N/A" if item.get("score") is None else f"{item['score']:.1f}",
             f"{item.get('weight', 0):.0f}%", item.get("explanation", "")]
            for item in readiness.get("components", [])
        ]
        story.append(_styled_table(readiness_rows, [1.25 * inch, .65 * inch, .6 * inch, 4.15 * inch], header=True, font_size=6.5))
        story.append(Paragraph(_text("Research horizon: " + readiness.get("research_horizon", "")), styles["small"]))
        story.append(Paragraph(_text(readiness.get("position_sizing_caution", "")), styles["warning"]))
        story.append(Paragraph(_text(readiness.get("disclosure", "")), styles["small"]))

    contributions = _get(report, "committee_contributions", [])
    if contributions:
        story.extend([_section("Why this decision?", styles), _contribution_table(contributions, styles, document.width)])

    performance = _get(report, "performance", {})
    history = _get(report, "performance_history", [])
    if performance:
        story.extend([_section("Historical performance", styles), _performance_table(performance, ticker, styles, document.width)])
        chart = _line_chart(history, ["Company", "S&P 500"], [ticker, "S&P 500"], document.width)
        if chart:
            story.extend([Spacer(1, 6), chart])

    technical = _get(report, "technical", {})
    technical_history = _get(report, "technical_history", [])
    if technical:
        story.append(_section("Golden Cross analyzer", styles))
        if technical.get("status") == "insufficient_history":
            story.append(Paragraph(_text(technical.get("message", "Insufficient daily history.")), styles["warning"]))
        else:
            short_period = technical.get("short_window", 50)
            long_period = technical.get("long_window", 200)
            cross = technical.get("latest_cross") or {}
            rows = [
                ["Trend", f"SMA {short_period}", f"SMA {long_period}", f"{short_period}/{long_period} spread", "Latest crossover"],
                [technical.get("label", ""), f"${technical.get('short_average', technical.get('sma_50', 0)):,.2f}",
                 f"${technical.get('long_average', technical.get('sma_200', 0)):,.2f}", f"{technical.get('spread_percent', 0):+.2f}%",
                 f"{cross.get('label', 'None detected')} {cross.get('date', '')}".strip()],
            ]
            story.append(_styled_table(rows, [document.width / 5] * 5, header=True))
            chart = _line_chart(technical_history, ["Price", f"SMA {short_period}", f"SMA {long_period}"], [ticker, f"SMA {short_period}", f"SMA {long_period}"], document.width)
            if chart:
                story.extend([Spacer(1, 6), chart])
            story.append(Paragraph(
                "A Golden Cross is a technical trend signal, not a prediction or investment recommendation.",
                styles["small"],
            ))

    backtest = _get(report, "backtest", {})
    if backtest:
        story.append(_section("Golden Cross backtest", styles))
        if backtest.get("status") == "insufficient_history":
            story.append(Paragraph(_text(backtest.get("message", "Insufficient history.")), styles["warning"]))
        else:
            backtest_rows = [
                ["Strategy return", "Annualized return", "Buy and hold", "S&P 500", "Max drawdown", "Sharpe", "Trades", "Win rate"],
                [f"{backtest.get('total_return', 0):+.2f}%", f"{backtest.get('annualized_return', 0):+.2f}%",
                 f"{backtest.get('buy_hold_return', 0):+.2f}%", f"{backtest.get('benchmark_return', 0):+.2f}%",
                 f"{backtest.get('max_drawdown', 0):.2f}%", f"{backtest.get('sharpe_ratio', 0):.2f}",
                 backtest.get("completed_trades", 0), f"{backtest.get('win_rate', 0):.1f}%"],
            ]
            story.append(_styled_table(backtest_rows, [document.width / 8] * 8, header=True, font_size=6.5))
            chart = _line_chart(
                backtest.get("curve", []), ["Golden Cross strategy", "Buy and hold", "S&P 500"],
                ["Golden Cross", "Buy and hold", "S&P 500"], document.width,
            )
            if chart:
                story.extend([Spacer(1, 6), chart])
            story.append(Paragraph(_text(
                f"{backtest.get('execution', '')}. Transaction cost: {backtest.get('transaction_cost_bps', 0):.0f} bps per transaction. "
                f"{backtest.get('disclosure', '')}"
            ), styles["small"]))

    risk = _get(report, "risk", {})
    if risk:
        story.append(_section("Risk dashboard", styles))
        story.append(Paragraph(_text(risk.get("summary", "")), styles["body"]))
        risk_rows = [["Factor", "Score", "Level", "Weight", "Explanation"]] + [
            [item.get("factor", ""), "N/A" if item.get("score") is None else f"{item['score']:.1f}",
             item.get("severity", ""), f"{item.get('weight', 0):.0f}%", item.get("explanation", "")]
            for item in risk.get("components", [])
        ]
        story.append(_styled_table(risk_rows, [1.05 * inch, .55 * inch, .65 * inch, .55 * inch, 3.85 * inch], header=True, font_size=6.5))
        for flag in risk.get("flags", []):
            story.append(Paragraph(_text(f"{flag['severity']} - {flag['factor']}: {flag['message']}"), styles["warning"]))

    macro = _get(report, "macro", {})
    if macro:
        story.extend([_section("Macro environment", styles), _macro_table(macro, styles, document.width)])

    environment = _get(report, "market_environment", {})
    if environment:
        story.extend([_section("Economic events and market environment", styles)])
        story.append(Paragraph(_text(environment.get("summary", "")), styles["body"]))
        event_rows = [["Event", "Direction", "Impact", "Confidence", "Duration"]] + [
            [event.get("title", ""), event.get("expected_direction", ""), event.get("impact", ""),
             f"{event.get('confidence', 0)}%", event.get("duration", "")]
            for event in environment.get("events", [])
        ]
        story.append(_styled_table(event_rows, [2.75 * inch, 1.05 * inch, .65 * inch, .7 * inch, 1.55 * inch], header=True, font_size=6.5))
        story.append(Paragraph(_text(
            f"Event source: {environment.get('event_provider', 'Unknown')}. Macro source: {environment.get('macro_provider', 'Unknown')}."
        ), styles["small"]))

    catalyst_calendar = _get(report, "catalyst_calendar", {})
    if catalyst_calendar:
        story.extend([_section("Earnings and catalyst readiness", styles)])
        story.append(Paragraph(_text(catalyst_calendar.get("summary", "")), styles["body"]))
        catalyst_rows = [["Date", "Days", "Event", "Category", "Readiness", "Importance"]] + [
            [event.get("date", ""), event.get("days_until", ""), event.get("title", ""),
             event.get("category", ""), event.get("readiness", ""), event.get("importance", "")]
            for event in catalyst_calendar.get("events", [])
        ]
        story.append(_styled_table(catalyst_rows, [.75 * inch, .42 * inch, 2.65 * inch, .8 * inch, .9 * inch, .7 * inch], header=True, font_size=6.5))
        story.append(Paragraph(_text(f"Calendar source: {catalyst_calendar.get('provider', 'Unknown')}."), styles["small"]))

    cases = [
        [Paragraph("Bull case", styles["column_heading"]), Paragraph("Bear case", styles["column_heading"])],
        [_paragraph_list(_get(report, "bull_case", []), styles), _paragraph_list(_get(report, "bear_case", []), styles)],
    ]
    story.extend([_section("Investment case", styles), _styled_table(cases, [document.width / 2] * 2, header=True)])
    story.append(_section("Risks", styles))
    story.extend(_paragraph_list(_get(report, "risks", []), styles))
    story.append(_section("Catalysts", styles))
    story.extend(_paragraph_list(_get(report, "catalysts", []), styles))

    assessments = _get(report, "assessments", [])
    if assessments:
        story.append(_section("Strategy committee evidence", styles))
        for assessment in assessments:
            strategy_block = [Paragraph(
                _text(f"{_get(assessment, 'strategy', '')}: {_get(assessment, 'vote', '').title()} ({_get(assessment, 'confidence', 0)}% confidence)"),
                styles["strategy"],
            ), Paragraph(_text(_get(assessment, "thesis", "")), styles["body"])]
            evidence = _get(assessment, "evidence", [])
            if evidence:
                rows = [["Evidence", "Value", "Source", "Observed"]] + [
                    [
                        _p(_get(item, "label", ""), styles),
                        _p(_get(item, "value", ""), styles),
                        _p(_get(item, "source", ""), styles),
                        _p(_get(item, "observed_at", ""), styles),
                    ]
                    for item in evidence
                ]
                strategy_block.append(_styled_table(rows, [1.25 * inch, 0.9 * inch, 2.35 * inch, 1.4 * inch], header=True))
            strategy_block.append(Spacer(1, 8))
            story.append(KeepTogether(strategy_block))

    configuration = _get(report, "configuration", {})
    if configuration:
        technical_config = configuration.get("technical", {})
        story.append(_section("Configuration and methodology", styles))
        story.append(Paragraph(_text(
            f"Configuration version {configuration.get('version', 'Unknown')} | "
            f"Profile {configuration.get('profile', 'Unknown')} | "
            f"Committee preset {configuration.get('committee_preset', 'Unknown')} | "
            f"Moving averages {technical_config.get('short_window', 50)}/{technical_config.get('long_window', 200)} | "
            f"Backtest cost {configuration.get('backtest', {}).get('transaction_cost_bps', 0)} bps."
        ), styles["small"]))

    story.extend([_section("Sources and disclosures", styles)])
    story.append(Paragraph(_text(
        f"Market data provider: {_get(report, 'provider', 'Unknown')}. "
        f"Company data as of {_get(report, 'data_as_of', 'Unknown')}. "
        f"Report created {_get(report, 'created_at', 'Unknown')}."
    ), styles["small"]))
    if "FRED" in str(macro.get("provider", "")):
        story.append(Paragraph(
            "This product uses the FRED® API but is not endorsed or certified by the Federal Reserve Bank of St. Louis.",
            styles["small"],
        ))
    story.append(Paragraph(
        "Project Atlas is an analysis-only research tool. This report is not investment advice and does not constitute an offer or recommendation to buy or sell securities.",
        styles["disclaimer"],
    ))
    document.build(story, onFirstPage=_page_footer, onLaterPages=_page_footer)
    return buffer.getvalue()


def render_comparison_pdf(comparison: dict[str, Any]) -> bytes:
    buffer = BytesIO()
    page_size = landscape(LETTER)
    document = SimpleDocTemplate(
        buffer,
        pagesize=page_size,
        rightMargin=0.45 * inch,
        leftMargin=0.45 * inch,
        topMargin=0.7 * inch,
        bottomMargin=0.58 * inch,
        title="Atlas Company Comparison",
        author="Project Atlas",
    )
    styles = _styles()
    tickers = comparison.get("tickers", [])
    story = [
        Paragraph("PROJECT ATLAS", styles["eyebrow"]),
        Paragraph(_text("Company Comparison: " + " vs ".join(tickers)), styles["title"]),
        Paragraph(_text(f"Saved snapshot created {comparison.get('created_at', 'Unknown')}"), styles["subtitle"]),
        HRFlowable(width="100%", thickness=2, color=GOLD, spaceBefore=5, spaceAfter=12),
    ]
    weights = comparison.get("strategy_weights", {})
    story.append(Paragraph(
        _text("Committee weights: " + " | ".join(f"{name} {value:.1f}%" for name, value in weights.items())),
        styles["small"],
    ))
    for warning in comparison.get("warnings", []):
        story.append(Paragraph(_text("Data note: " + warning), styles["warning"]))

    environment = comparison.get("market_environment", {})
    if environment:
        story.append(Paragraph(_text(
            f"Market environment: {environment.get('label', 'Unknown')} ({environment.get('score', 0):.1f}/100). "
            f"{environment.get('buying_context', '')}"
        ), styles["body"]))

    summary = comparison.get("summary", [])
    if summary:
        columns = ["Rank", "Ticker", "Score", "Entry readiness", "Vote", "Confidence", "Risk score", "Risk level", "Catalyst readiness", "1Y return", "vs S&P 500", "P/E", "Revenue growth", "Profit margin", "Beta", "Strongest factor", "Weakest factor"]
        rows = [[_hp(column, styles) for column in columns]]
        for item in summary:
            rows.append([_p(_format_cell(column, item.get(column)), styles) for column in columns])
        widths = [0.3, 0.45, 0.45, 0.6, 0.5, 0.55, 0.55, 0.55, 0.65, 0.55, 0.6, 0.4, 0.65, 0.65, 0.35, 0.65, 0.65]
        story.extend([_section("Ranked summary", styles), _styled_table(rows, [width * inch for width in widths], header=True, font_size=6.5)])

    chart = _line_chart(comparison.get("performance_history", []), tickers, tickers, document.width, height=2.25 * inch)
    if chart:
        story.extend([_section("Normalized performance", styles), chart])

    strategy_table = comparison.get("strategy_table", [])
    if strategy_table:
        columns = ["Strategy"] + tickers
        rows = [[_hp(column, styles) for column in columns]] + [
            [_p(row.get(column, ""), styles) for column in columns] for row in strategy_table
        ]
        story.extend([_section("Strategy-by-strategy", styles), _styled_table(rows, [document.width / len(columns)] * len(columns), header=True)])

    story.append(Paragraph(
        "Project Atlas is an analysis-only research tool. This comparison is not investment advice and does not constitute an offer or recommendation to buy or sell securities.",
        styles["disclaimer"],
    ))
    if any("FRED" in str(report.get("macro", {}).get("provider", "")) for report in comparison.get("reports", [])):
        story.append(Paragraph(
            "This product uses the FRED® API but is not endorsed or certified by the Federal Reserve Bank of St. Louis.",
            styles["small"],
        ))
    document.build(story, onFirstPage=_page_footer, onLaterPages=_page_footer)
    return buffer.getvalue()


def render_watchlist_pdf(ranking: dict[str, Any]) -> bytes:
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer, pagesize=landscape(LETTER), rightMargin=.45 * inch, leftMargin=.45 * inch,
        topMargin=.7 * inch, bottomMargin=.58 * inch, title="Atlas Ranked Watchlist", author="Project Atlas",
    )
    styles = _styles()
    story = [
        Paragraph("PROJECT ATLAS", styles["eyebrow"]),
        Paragraph("Ranked Watchlist", styles["title"]),
        Paragraph(_text(f"Ranking mode: {ranking.get('mode', 'Best opportunity')} | Created {ranking.get('created_at', '')}"), styles["subtitle"]),
        HRFlowable(width="100%", thickness=2, color=GOLD, spaceBefore=5, spaceAfter=12),
    ]
    columns = ["Rank", "Ticker", "Opportunity score", "Entry readiness", "Entry posture", "Committee score", "Vote", "Risk score", "Risk level", "Momentum score", "Technical signal", "Catalyst readiness", "Days to catalyst", "1Y vs S&P 500", "Market environment", "Freshness"]
    rows = [[_hp(column, styles) for column in columns]] + [
        [_p(_format_watchlist_cell(column, row.get(column)), styles) for column in columns]
        for row in ranking.get("rows", [])
    ]
    widths = [.3, .42, .62, .62, .75, .62, .42, .5, .55, .58, .72, .68, .48, .62, .68, .48]
    story.append(_styled_table(rows, [value * inch for value in widths], header=True, font_size=6.4))
    story.append(_section("Why companies ranked this way", styles))
    for row in ranking.get("rows", []):
        story.append(Paragraph(_text(f"#{row['Rank']} {row['Ticker']}: {row['Why']}"), styles["body"]))
    if ranking.get("missing"):
        story.append(Paragraph(_text("Missing reports: " + ", ".join(ranking["missing"])), styles["warning"]))
    story.append(Paragraph(
        "Rankings combine committee, risk, momentum, and market-environment estimates. They are research aids, not investment advice.",
        styles["disclaimer"],
    ))
    document.build(story, onFirstPage=_page_footer, onLaterPages=_page_footer)
    return buffer.getvalue()


def render_portfolio_pdf(portfolio: dict[str, Any]) -> bytes:
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer, pagesize=landscape(LETTER), rightMargin=.45 * inch, leftMargin=.45 * inch,
        topMargin=.7 * inch, bottomMargin=.58 * inch, title="Atlas Portfolio Exposure", author="Project Atlas",
    )
    styles = _styles()
    story = [
        Paragraph("PROJECT ATLAS", styles["eyebrow"]),
        Paragraph("Portfolio Exposure Analysis", styles["title"]),
        Paragraph(_text(f"Created {portfolio.get('created_at', '')} | Posture: {portfolio.get('posture', 'Unavailable')}"), styles["subtitle"]),
        HRFlowable(width="100%", thickness=2, color=GOLD, spaceBefore=5, spaceAfter=12),
    ]
    metrics = [
        ["Weighted risk", "Entry readiness", "Committee score", "Weighted beta", "Covered exposure", "Effective positions"],
        [
            _portfolio_metric(portfolio.get("weighted_risk")),
            _portfolio_metric(portfolio.get("weighted_readiness")),
            _portfolio_metric(portfolio.get("weighted_committee")),
            "N/A" if portfolio.get("weighted_beta") is None else f"{portfolio['weighted_beta']:.2f}",
            f"{portfolio.get('covered_weight', 0):.1f}%",
            f"{portfolio.get('effective_positions', 0):.1f}",
        ],
    ]
    story.append(_styled_table(metrics, [document.width / 6] * 6, header=True))
    rows = [["Ticker", "Company", "Weight", "Sector", "Committee", "Vote", "Risk", "Risk level", "Readiness", "Entry posture", "Beta", "Catalyst", "Days", "Freshness"]]
    for item in portfolio.get("rows", []):
        rows.append([
            item.get("Ticker", ""), item.get("Company", ""), f"{item.get('Portfolio weight', 0):.1f}%",
            item.get("Sector", ""), f"{item.get('Committee score', 0):.1f}", item.get("Vote", ""),
            f"{item.get('Risk score', 0):.1f}", item.get("Risk level", ""), f"{item.get('Entry readiness', 0):.1f}",
            item.get("Entry posture", ""), "N/A" if item.get("Beta") is None else f"{item['Beta']:.2f}",
            item.get("Catalyst readiness", ""), item.get("Days to catalyst", ""), item.get("Freshness", ""),
        ])
    widths = [.42, 1.0, .48, .65, .55, .42, .42, .58, .58, .8, .4, .72, .35, .48]
    story.extend([_section("Holding-level exposure", styles), _styled_table(rows, [value * inch for value in widths], header=True, font_size=6.2)])
    sector_rows = [["Sector", "Portfolio allocation"]] + [
        [item["Sector"], f"{item['Allocation']:.1f}%"] for item in portfolio.get("sector_exposure", [])
    ]
    if len(sector_rows) > 1:
        story.extend([_section("Sector exposure", styles), _styled_table(sector_rows, [2.5 * inch, 1.5 * inch], header=True)])
    if portfolio.get("warnings"):
        story.append(_section("Exposure flags", styles))
        for warning in portfolio["warnings"]:
            story.append(Paragraph(_text(f"{warning['severity']} - {warning['title']}: {warning['message']}"), styles["warning"]))
    story.append(Paragraph(_text(portfolio.get("disclosure", "")), styles["disclaimer"]))
    document.build(story, onFirstPage=_page_footer, onLaterPages=_page_footer)
    return buffer.getvalue()


def render_portfolio_action_plan_pdf(plan: dict[str, Any]) -> bytes:
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer, pagesize=landscape(LETTER), rightMargin=.45 * inch, leftMargin=.45 * inch,
        topMargin=.7 * inch, bottomMargin=.58 * inch, title="Atlas Portfolio Action Plan", author="Project Atlas",
    )
    styles = _styles()
    story = [
        Paragraph("PROJECT ATLAS", styles["eyebrow"]),
        Paragraph("Portfolio Action Plan", styles["title"]),
        Paragraph(_text(f"Weekly review created {plan.get('created_at', '')}"), styles["subtitle"]),
        HRFlowable(width="100%", thickness=2, color=GOLD, spaceBefore=5, spaceAfter=12),
    ]
    counts = plan.get("counts", {})
    metrics = [
        ["Portfolio posture", "Do now", "Review soon", "Monitor", "Evidence trust", "Weighted risk"],
        [plan.get("portfolio_posture", "Unavailable"), counts.get("Do now", 0), counts.get("Review soon", 0),
         counts.get("Monitor", 0), _score(plan.get("portfolio_trust")), _portfolio_metric(plan.get("weighted_risk"))],
    ]
    story.append(_styled_table(metrics, [document.width / 6] * 6, header=True))
    story.append(Paragraph(_text(plan.get("summary", "")), styles["body"]))
    columns = ["Priority", "Ticker", "Action review", "Weight", "Ceiling", "View", "Trust", "Risk", "Why", "Next step"]
    rows = [[_hp(column, styles) for column in columns]]
    for item in plan.get("rows", []):
        rows.append([_p(value, styles) for value in [
            item.get("Priority", ""), item.get("Ticker", ""), item.get("Action review", ""),
            _percent_value(item.get("Current weight")), _percent_value(item.get("Saved ceiling")),
            item.get("Beginner view", ""), item.get("Evidence trust", ""), _score(item.get("Risk score")),
            item.get("Why", ""), item.get("Next step", ""),
        ]])
    widths = [.65, .5, .95, .48, .55, .72, .52, .6, 2.1, 2.3]
    story.extend([_section("Prioritized holding review", styles), _styled_table(
        rows, [value * inch for value in widths], header=True, font_size=6.2,
    )])
    if plan.get("exposure_warnings"):
        story.append(_section("Portfolio exposure flags", styles))
        for warning in plan["exposure_warnings"]:
            story.append(Paragraph(_text(
                f"{warning.get('severity')} - {warning.get('title')}: {warning.get('message')}"
            ), styles["warning"]))
    story.append(Paragraph(_text(plan.get("disclosure", "")), styles["disclaimer"]))
    document.build(story, onFirstPage=_page_footer, onLaterPages=_page_footer)
    return buffer.getvalue()


def render_accuracy_report_pdf(summary: dict[str, Any]) -> bytes:
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer, pagesize=landscape(LETTER), rightMargin=.45 * inch, leftMargin=.45 * inch,
        topMargin=.7 * inch, bottomMargin=.58 * inch, title="Atlas Decision Accuracy Report", author="Project Atlas",
    )
    styles = _styles()
    story = [
        Paragraph("PROJECT ATLAS", styles["eyebrow"]),
        Paragraph("Decision Accuracy Report", styles["title"]),
        Paragraph(_text(f"{summary.get('horizon_days', 30)}-day outcomes | Created {summary.get('created_at', '')}"), styles["subtitle"]),
        HRFlowable(width="100%", thickness=2, color=GOLD, spaceBefore=5, spaceAfter=12),
    ]
    metrics = [
        ["Model capacity", "Snapshots", "Directional outcomes", "Win rate", "Average return", "Vs S&P 500", "Worst drawdown"],
        [summary.get("capacity", "Insufficient"), summary.get("snapshots", 0), summary.get("completed_directional", 0),
         _percent_value(summary.get("win_rate")), _signed_percent(summary.get("average_return")),
         _signed_percent(summary.get("average_relative_return")), _signed_percent(summary.get("worst_drawdown"))],
    ]
    story.append(_styled_table(metrics, [document.width / 7] * 7, header=True))
    story.append(Paragraph(_text(summary.get("summary", "")), styles["body"]))
    columns = ["Ticker", "Label", "Confidence", "Trust", "Regime", "Captured", "Company return", "S&P 500 return", "Relative return", "Drawdown", "Result"]
    rows = [[_hp(column, styles) for column in columns]]
    for item in summary.get("rows", []):
        rows.append([_p(value, styles) for value in [
            item.get("Ticker", ""), item.get("Label", ""), item.get("Confidence", ""), item.get("Trust", ""),
            item.get("Regime", ""), str(item.get("Captured", ""))[:10], _signed_percent(item.get("Company return")),
            _signed_percent(item.get("S&P 500 return")), _signed_percent(item.get("Relative return")),
            _signed_percent(item.get("Max drawdown")), item.get("Result", ""),
        ]])
    story.extend([_section("Label outcomes", styles), _styled_table(
        rows, [.65 * inch, 1.2 * inch, .75 * inch, .7 * inch, 1.0 * inch, .85 * inch,
               1.0 * inch, 1.0 * inch, 1.0 * inch, .75 * inch, .9 * inch], header=True, font_size=6.2,
    )])
    groups = summary.get("groups", [])
    if groups:
        group_rows = [["Dimension", "Group", "Completed", "Win rate", "Average relative return"]] + [
            [item.get("Dimension"), item.get("Group"), item.get("Completed"),
             _percent_value(item.get("Win rate")), _signed_percent(item.get("Average relative return"))]
            for item in groups
        ]
        story.extend([_section("Breakdown", styles), _styled_table(
            group_rows, [1.2 * inch, 2.0 * inch, .8 * inch, .8 * inch, 1.4 * inch], header=True,
        )])
    story.append(Paragraph(_text(summary.get("disclosure", "")), styles["disclaimer"])),
    document.build(story, onFirstPage=_page_footer, onLaterPages=_page_footer)
    return buffer.getvalue()


def render_discovery_pdf(result: dict[str, Any]) -> bytes:
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer, pagesize=landscape(LETTER), rightMargin=.45 * inch, leftMargin=.45 * inch,
        topMargin=.7 * inch, bottomMargin=.58 * inch, title="Atlas Opportunity Discovery", author="Project Atlas",
    )
    styles = _styles()
    story = [
        Paragraph("PROJECT ATLAS", styles["eyebrow"]), Paragraph("Opportunity Discovery", styles["title"]),
        Paragraph(_text(f"Preliminary market screen created {result.get('created_at', '')}"), styles["subtitle"]),
        HRFlowable(width="100%", thickness=2, color=GOLD, spaceBefore=5, spaceAfter=12),
        Paragraph(_text(result.get("summary", "")), styles["body"]),
    ]
    columns = ["Rank", "Ticker", "Company", "Sector", "Score", "Label", "Price", "Forward P/E", "PEG", "Valuation", "Quality", "Growth", "Trend", "Risk fit", "Data", "On radar"]
    rows = [[_hp(column, styles) for column in columns]]
    for item in result.get("rows", []):
        rows.append([_p(value, styles) for value in [
            item.get("Rank"), item.get("Ticker"), item.get("Company"), item.get("Sector"),
            _score(item.get("Discovery score")), item.get("Research label"), _currency(item.get("Price")),
            _decimal(item.get("Forward P/E")), _decimal(item.get("PEG")), _score(item.get("Valuation")),
            _score(item.get("Quality")), _score(item.get("Growth")), _score(item.get("Trend")),
            _score(item.get("Risk fit")), item.get("Data status"), "Yes" if item.get("On radar") else "No",
        ]])
    widths = [.4, .5, .95, .7, .52, 1.05, .55, .55, .42, .55, .55, .55, .55, .55, .45, .48]
    story.append(_styled_table(rows, [value * inch for value in widths], header=True, font_size=6.0))
    story.append(_section("Why candidates surfaced", styles))
    for item in result.get("rows", [])[:10]:
        story.append(Paragraph(_text(
            f"#{item.get('Rank')} {item.get('Ticker')}: {item.get('Why it surfaced')}. Caution: {item.get('What could go wrong')}."
        ), styles["body"]))
    monitor = result.get("monitor") or {}
    if monitor:
        story.append(_section("Changes since prior scan", styles))
        story.append(Paragraph(_text(monitor.get("summary", "")), styles["body"]))
        for item in monitor.get("events", [])[:12]:
            story.append(Paragraph(_text(
                f"{item.get('Ticker')} — {item.get('Change')}: {item.get('Details')}"
            ), styles["body"]))
    if result.get("failures"):
        story.append(Paragraph(_text("Unavailable: " + "; ".join(
            f"{item.get('Ticker')} - {item.get('Error')}" for item in result["failures"]
        )), styles["warning"]))
    story.append(Paragraph(_text(result.get("disclosure", "")), styles["disclaimer"]))
    document.build(story, onFirstPage=_page_footer, onLaterPages=_page_footer)
    return buffer.getvalue()


def render_change_pdf(change: dict[str, Any]) -> bytes:
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer, pagesize=LETTER, rightMargin=.55 * inch, leftMargin=.55 * inch,
        topMargin=.72 * inch, bottomMargin=.62 * inch, title="Atlas Research Change Report", author="Project Atlas",
    )
    styles = _styles()
    story = [
        Paragraph("PROJECT ATLAS", styles["eyebrow"]),
        Paragraph(_text(f"{change.get('company', change.get('ticker', ''))} ({change.get('ticker', '')})"), styles["title"]),
        Paragraph(_text(f"Research Change Report | Thesis {change.get('thesis_status', 'Unavailable')}"), styles["subtitle"]),
        HRFlowable(width="100%", thickness=2, color=GOLD, spaceBefore=5, spaceAfter=12),
        Paragraph(_text(change.get("summary", "")), styles["body"]),
    ]
    story.append(_styled_table([
        ["Previous report", "Current report", "Thesis status", "Thesis change score"],
        [
            str(change.get("previous_created_at", ""))[:19].replace("T", " ") + " UTC",
            str(change.get("current_created_at", ""))[:19].replace("T", " ") + " UTC",
            change.get("thesis_status", ""), f"{change.get('thesis_score', 0):+.1f}",
        ],
    ], [document.width / 4] * 4, header=True))
    metric_rows = [["Metric", "Previous", "Current", "Change", "Impact"]] + [
        [
            item["Metric"], f"{item['Previous']:.1f}", f"{item['Current']:.1f}",
            f"{item['Change']:+.1f} {item['Unit']}", item["Impact"],
        ] for item in change.get("metrics", [])
    ]
    story.extend([_section("Measured changes", styles), _styled_table(metric_rows, [1.55 * inch, 1.0 * inch, 1.0 * inch, 1.15 * inch, 1.2 * inch], header=True)])
    if change.get("material_changes"):
        material_rows = [["Category", "Change", "Impact", "Details"]] + [
            [item["Category"], item["Change"], item["Impact"], item["Details"]]
            for item in change["material_changes"]
        ]
        story.extend([_section("What changed?", styles), _styled_table(material_rows, [1.0 * inch, 1.45 * inch, 1.0 * inch, 3.4 * inch], header=True, font_size=6.8)])
    story.append(_section("Why Atlas assigned this thesis status", styles))
    story.extend(_paragraph_list(change.get("reasons", []), styles))
    story.append(Paragraph(_text(change.get("disclosure", "")), styles["disclaimer"]))
    document.build(story, onFirstPage=_page_footer, onLaterPages=_page_footer)
    return buffer.getvalue()


def render_decision_packet_pdf(packet: dict[str, Any]) -> bytes:
    buffer = BytesIO()
    ticker = packet.get("ticker", "")
    company = packet.get("company", ticker)
    document = SimpleDocTemplate(
        buffer, pagesize=LETTER, rightMargin=.55 * inch, leftMargin=.55 * inch,
        topMargin=.72 * inch, bottomMargin=.62 * inch,
        title=f"Atlas Decision Packet - {ticker}", author="Project Atlas",
    )
    styles = _styles()
    story = [
        Paragraph("PROJECT ATLAS", styles["eyebrow"]),
        Paragraph(_text(f"{company} ({ticker}) Decision Packet"), styles["title"]),
        Paragraph(_text(f"Saved evidence snapshot created {packet.get('created_at', '')}"), styles["subtitle"]),
        HRFlowable(width="100%", thickness=2, color=GOLD, spaceBefore=5, spaceAfter=12),
        Paragraph(_text(packet.get("data_watermark", "EVIDENCE TRUST NOT ASSESSED")), styles["trust_band"]),
    ]
    committee = packet.get("committee") or {}
    summary_rows = [
        ["Beginner view", "Evidence confidence", "Evidence score", "Committee vote", "Committee score"],
        [packet.get("beginner_view", "Research first"), packet.get("evidence_confidence", "Low"),
         _score(packet.get("evidence_score")), committee.get("vote", "Unavailable"),
         _score(committee.get("score"))],
    ]
    story.append(_styled_table(summary_rows, [document.width / 5] * 5, header=True))
    story.append(Spacer(1, 8))
    story.append(Paragraph(_text(packet.get("plain_language_summary", "")), styles["body"]))
    story.append(Paragraph(_text("Next step: " + str(packet.get("next_step") or "Complete missing research.")), styles["warning"]))

    trust = packet.get("evidence_trust") or {}
    if trust:
        trust_rows = [["Evidence", "Status", "Trust score", "Details"]] + [
            [row.get("Evidence", ""), row.get("Status", ""), _score(row.get("Score")), row.get("Details", "")]
            for row in trust.get("components", [])
        ]
        story.extend([_section("Evidence trust and freshness", styles), _styled_table(
            trust_rows, [1.35 * inch, .7 * inch, .8 * inch, 3.9 * inch], header=True, font_size=6.8,
        )])
        for warning in trust.get("warnings", []):
            story.append(Paragraph(_text(warning), styles["warning"]))

    story.append(_section("Decision explanation", styles))
    decision_rows = [
        [Paragraph("What supports this view", styles["column_heading"]), Paragraph("What could change it", styles["column_heading"])],
        [_p(packet.get("supports", ""), styles), _p(packet.get("cautions", ""), styles)],
    ]
    story.append(_styled_table(decision_rows, [document.width / 2] * 2, header=True))
    workflow = packet.get("workflow", {})
    workflow_rows = [["Evidence", "Status", "Details", "Next step"]] + [
        [row.get("Evidence", ""), row.get("Status", ""), row.get("Details", ""), row.get("Next step", "")]
        for row in workflow.get("checks", [])
    ]
    story.extend([_section("Evidence completeness", styles), _styled_table(
        workflow_rows, [1.2 * inch, .65 * inch, 2.25 * inch, 2.55 * inch], header=True, font_size=6.8,
    )])

    report = packet.get("report") or {}
    if report:
        story.append(_section("Research case", styles))
        story.append(Paragraph(_text(report.get("executive_summary", "")), styles["body"]))
        cases = [
            [Paragraph("Bull case", styles["column_heading"]), Paragraph("Bear case", styles["column_heading"])],
            [_paragraph_list(report.get("bull_case", []), styles), _paragraph_list(report.get("bear_case", []), styles)],
        ]
        story.append(_styled_table(cases, [document.width / 2] * 2, header=True))
        story.append(_section("Risks and catalysts", styles))
        risk_catalyst = [
            [Paragraph("Risks", styles["column_heading"]), Paragraph("Catalysts", styles["column_heading"])],
            [_paragraph_list(report.get("risks", []), styles), _paragraph_list(report.get("catalysts", []), styles)],
        ]
        story.append(_styled_table(risk_catalyst, [document.width / 2] * 2, header=True))

    technical = packet.get("technical") or {}
    environment = packet.get("environment") or {}
    catalyst = packet.get("next_catalyst") or {}
    story.append(_section("Market, trend, and catalyst context", styles))
    context_rows = [
        ["Technical trend", "Market posture", "Environment score", "Next catalyst", "Event date"],
        [technical.get("label", technical.get("status", "Unavailable")), environment.get("label", "Unavailable"),
         _score(environment.get("score")), catalyst.get("title", "Unavailable"), catalyst.get("date", "Unavailable")],
    ]
    story.append(_styled_table(context_rows, [document.width / 5] * 5, header=True))
    if environment.get("buying_context"):
        story.append(Paragraph(_text(environment["buying_context"]), styles["body"]))

    health = packet.get("financial_health") or {}
    valuation = packet.get("valuation") or {}
    story.append(_section("Financial health and valuation", styles))
    health_rows = [
        ["SEC posture", "SEC score", "Metric coverage", "Valuation status", "Margin of safety", "Base value"],
        [_p(health.get("posture", "Not analyzed"), styles), _p(_score(health.get("score")), styles),
         _p(_percent_value(health.get("coverage")), styles), _p(valuation.get("status", "Not modeled"), styles),
         _p(_signed_percent(valuation.get("margin_of_safety")), styles),
         _p(_currency(valuation.get("base_value")), styles)],
    ]
    story.append(_styled_table(health_rows, [document.width / 6] * 6, header=True))
    signals = health.get("signals", [])
    if signals:
        signal_rows = [["SEC factor", "Direction", "Change"]] + [
            [item.get("Factor", ""), item.get("Direction", ""), _signed_percent(item.get("Change"))]
            for item in signals
        ]
        story.append(Spacer(1, 6))
        story.append(_styled_table(signal_rows, [document.width / 3] * 3, header=True))

    thesis = packet.get("thesis") or {}
    evaluation = packet.get("thesis_evaluation") or {}
    story.append(_section("Thesis and invalidation", styles))
    if thesis:
        thesis_rows = [
            ["Saved stance", "Confidence", "Evaluation", "Review date", "Risk limit", "Minimum readiness"],
            [thesis.get("stance", ""), thesis.get("confidence", ""), evaluation.get("status", ""),
             thesis.get("review_date", ""), _score(thesis.get("max_risk_score")),
             _score(thesis.get("min_readiness_score"))],
        ]
        story.append(_styled_table(thesis_rows, [document.width / 6] * 6, header=True))
        conditions = thesis.get("invalidation_conditions", [])
        if conditions:
            story.append(Paragraph(_text("Saved invalidation conditions: " + "; ".join(conditions)), styles["warning"]))
        for flag in evaluation.get("flags", []):
            story.append(Paragraph(_text(f"{flag.get('factor')}: {flag.get('message')}"), styles["small"]))
    else:
        story.append(Paragraph("No personal thesis has been saved.", styles["warning"]))

    sizing = packet.get("position_plan") or {}
    story.append(_section("Position-sizing plan", styles))
    if sizing:
        sizing_rows = [
            ["Preset", "Entry", "Invalidation", "Share ceiling", "Position value", "Allocation", "Modeled loss"],
            [sizing.get("preset", ""), _currency(sizing.get("entry_price")), _currency(sizing.get("invalidation_price")),
             f"{sizing.get('suggested_shares', 0):,}", _currency(sizing.get("position_value")),
             _percent_value(sizing.get("portfolio_allocation")), _currency(sizing.get("loss_at_invalidation"))],
        ]
        story.append(_styled_table(sizing_rows, [document.width / 7] * 7, header=True, font_size=6.8))
        story.append(Paragraph(_text(sizing.get("summary", "")), styles["body"]))
        for note in sizing.get("modifiers", []) + sizing.get("warnings", []):
            story.append(Paragraph(_text(note), styles["warning"]))
    else:
        story.append(Paragraph("No saved position-sizing plan is available.", styles["warning"]))

    alerts = packet.get("alerts", [])
    story.append(_section("Active alerts", styles))
    if alerts:
        alert_rows = [["Severity", "Category", "Title", "Message", "Created"]] + [
            [item.get("severity", ""), item.get("alert_type", ""), item.get("title", ""),
             item.get("message", ""), item.get("created_at", "")]
            for item in alerts
        ]
        story.append(_styled_table(alert_rows, [.65 * inch, .9 * inch, 1.5 * inch, 2.75 * inch, .9 * inch], header=True, font_size=6.5))
    else:
        story.append(Paragraph("No active saved alerts for this company.", styles["body"]))

    sources = packet.get("sources", [])
    story.append(_section("Sources and freshness", styles))
    if sources:
        source_rows = [["Evidence", "Provider", "Observed", "Saved"]] + [
            [item.get("Evidence", ""), item.get("Provider", ""), item.get("Observed", ""), item.get("Saved", "")]
            for item in sources
        ]
        story.append(_styled_table(source_rows, [1.25 * inch, 2.4 * inch, 1.55 * inch, 1.55 * inch], header=True, font_size=6.5))
    story.append(Paragraph(_text(packet.get("disclosure", "")), styles["disclaimer"]))
    document.build(story, onFirstPage=_page_footer, onLaterPages=_page_footer)
    return buffer.getvalue()


def _score(value: Any) -> str:
    return "Unavailable" if value is None else f"{float(value):.1f}/100"


def _decimal(value: Any) -> str:
    return "Unavailable" if value is None else f"{float(value):.2f}"


def _currency(value: Any) -> str:
    return "Unavailable" if value is None else f"${float(value):,.2f}"


def _percent_value(value: Any) -> str:
    return "Unavailable" if value is None else f"{float(value):.1f}%"


def _signed_percent(value: Any) -> str:
    return "Unavailable" if value is None else f"{float(value):+.1f}%"


def _portfolio_metric(value: Any) -> str:
    return "N/A" if value is None else f"{float(value):.1f}/100"


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("AtlasTitle", parent=base["Title"], fontName="Helvetica-Bold", fontSize=21, leading=24, textColor=NAVY, alignment=TA_LEFT, spaceAfter=2),
        "subtitle": ParagraphStyle("AtlasSubtitle", parent=base["Normal"], fontSize=9, leading=12, textColor=MUTED),
        "eyebrow": ParagraphStyle("AtlasEyebrow", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=BLUE, tracking=1.2),
        "heading": ParagraphStyle("AtlasHeading", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=12, leading=15, textColor=NAVY, spaceBefore=12, spaceAfter=6, keepWithNext=True),
        "strategy": ParagraphStyle("AtlasStrategy", parent=base["Heading3"], fontName="Helvetica-Bold", fontSize=10, leading=13, textColor=BLUE, spaceBefore=5, spaceAfter=3, keepWithNext=True),
        "column_heading": ParagraphStyle("AtlasColumnHeading", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=9, textColor=colors.white, alignment=TA_CENTER),
        "body": ParagraphStyle("AtlasBody", parent=base["BodyText"], fontSize=8.5, leading=12, textColor=NAVY, spaceAfter=5),
        "small": ParagraphStyle("AtlasSmall", parent=base["BodyText"], fontSize=7, leading=9.5, textColor=MUTED, spaceAfter=4),
        "cell": ParagraphStyle("AtlasCell", parent=base["BodyText"], fontSize=7, leading=9, textColor=NAVY),
        "header_cell": ParagraphStyle("AtlasHeaderCell", parent=base["BodyText"], fontName="Helvetica-Bold", fontSize=7, leading=9, textColor=colors.white),
        "warning": ParagraphStyle("AtlasWarning", parent=base["BodyText"], fontSize=7.5, leading=10, textColor=RED, backColor=colors.HexColor("#FCE8E6"), borderPadding=4, spaceAfter=4),
        "trust_band": ParagraphStyle("AtlasTrustBand", parent=base["BodyText"], fontName="Helvetica-Bold", fontSize=9, leading=12, textColor=NAVY, backColor=PALE_GOLD, borderPadding=6, alignment=TA_CENTER, spaceAfter=8),
        "disclaimer": ParagraphStyle("AtlasDisclaimer", parent=base["BodyText"], fontSize=7, leading=9.5, textColor=NAVY, backColor=PALE_GOLD, borderPadding=6, spaceBefore=8),
    }


def _summary_table(report: Any, styles: dict[str, ParagraphStyle], width: float) -> Table:
    score = _get(report, "committee_score", 50.0)
    weights = _get(report, "strategy_weights", {})
    rows = [
        ["Committee vote", "Confidence", "Committee score", "Data as of"],
        [
            _get(report, "committee_vote", "neutral").title(),
            f"{_get(report, 'committee_confidence', 0)}%",
            f"{score:.1f}/100",
            str(_get(report, "data_as_of", "Unknown"))[:19].replace("T", " ") + " UTC",
        ],
    ]
    table = _styled_table(rows, [width * 0.2, width * 0.18, width * 0.2, width * 0.42], header=True)
    if weights:
        return Table([[table], [Paragraph(_text("Weights: " + " | ".join(f"{key} {value:.1f}%" for key, value in weights.items())), styles["small"])]], colWidths=[width])
    return table


def _contribution_table(contributions: list[dict[str, Any]], styles: dict[str, ParagraphStyle], width: float) -> Table:
    rows = [["Strategy", "Weight", "Vote", "Confidence", "Weighted signal"]] + [
        [item["strategy"], f"{item['weight']:.1f}%", item["vote"].title(), f"{item['confidence']}%", f"{item['weighted_signal']:+.2f}"]
        for item in contributions
    ]
    return _styled_table(rows, [width * value for value in (0.24, 0.16, 0.2, 0.2, 0.2)], header=True)


def _performance_table(performance: dict[str, Any], ticker: str, styles: dict[str, ParagraphStyle], width: float) -> Table:
    rows = [["Period", ticker, "S&P 500", "Relative"]]
    for period, values in performance.get("periods", {}).items():
        rows.append([period, f"{values['company']:.2f}%", f"{values['benchmark']:.2f}%", f"{values['relative']:+.2f} pp"])
    rows.append(["Risk", f"Volatility {performance.get('annualized_volatility', 0):.2f}%", f"Max drawdown {performance.get('max_drawdown', 0):.2f}%", f"{performance.get('observations', 0)} observations"])
    return _styled_table(rows, [width / 4] * 4, header=True)


def _macro_table(macro: dict[str, Any], styles: dict[str, ParagraphStyle], width: float) -> Table:
    indicators = list(macro.get("indicators", {}).values())
    rows = [[_hp(item.get("label", ""), styles) for item in indicators], [
        _p(f"{item.get('value', 0):.2f} {item.get('unit', '')}", styles) for item in indicators
    ], [_p(f"{item.get('observed_at', '')} | {item.get('series_id', '')}", styles) for item in indicators]]
    return _styled_table(rows, [width / max(len(indicators), 1)] * len(indicators), header=True)


def _line_chart(history: list[dict[str, Any]], keys: list[str], labels: list[str], width: float, height: float = 2.05 * inch) -> Drawing | None:
    if len(history) < 2 or not keys:
        return None
    drawing = Drawing(width, height)
    chart = LinePlot()
    chart.x = 38
    chart.y = 24
    chart.width = width - 55
    chart.height = height - 48
    data = []
    active_labels = []
    for key, label in zip(keys, labels):
        points = [(index, row.get(key)) for index, row in enumerate(history) if row.get(key) is not None]
        if points:
            data.append(points)
            active_labels.append(label)
    if not data:
        return None
    chart.data = data
    palette = [BLUE, GOLD, GREEN, RED]
    for index in range(len(data)):
        chart.lines[index].strokeColor = palette[index % len(palette)]
        chart.lines[index].strokeWidth = 1.8
    all_values = [value for series in data for _, value in series]
    chart.yValueAxis.valueMin = min(all_values) * 0.96
    chart.yValueAxis.valueMax = max(all_values) * 1.04
    chart.yValueAxis.labelTextFormat = "%0.0f"
    chart.xValueAxis.valueMin = 0
    chart.xValueAxis.valueMax = len(history) - 1
    chart.xValueAxis.labelTextFormat = ""
    chart.strokeColor = colors.HexColor("#CBD3DA")
    drawing.add(chart)
    drawing.add(String(38, 6, _plain_text(history[0].get("date", "")), fontName="Helvetica", fontSize=6, fillColor=MUTED))
    drawing.add(String(width - 90, 6, _plain_text(history[-1].get("date", "")), fontName="Helvetica", fontSize=6, fillColor=MUTED))
    legend_x = 42
    for index, label in enumerate(active_labels):
        drawing.add(String(legend_x, height - 13, _plain_text(f"- {label}"), fontName="Helvetica-Bold", fontSize=7, fillColor=palette[index % len(palette)]))
        legend_x += 92
    return drawing


def _styled_table(rows: list[list[Any]], widths: list[float], header: bool = False, font_size: float = 7.5) -> Table:
    table = Table(rows, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
    commands = [
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), font_size),
        ("TEXTCOLOR", (0, 0), (-1, -1), NAVY),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CCD4DC")),
        ("ROWBACKGROUNDS", (0, 1 if header else 0), (-1, -1), [colors.white, LIGHT]),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    if header:
        commands.extend([
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ])
    table.setStyle(TableStyle(commands))
    return table


def _section(title: str, styles: dict[str, ParagraphStyle]) -> Paragraph:
    return Paragraph(_text(title), styles["heading"])


def _paragraph_list(items: list[str], styles: dict[str, ParagraphStyle]) -> list[Paragraph]:
    return [Paragraph(_text(f"- {item}"), styles["body"]) for item in items]


def _p(value: Any, styles: dict[str, ParagraphStyle]) -> Paragraph:
    return Paragraph(_text(value), styles["cell"])


def _hp(value: Any, styles: dict[str, ParagraphStyle]) -> Paragraph:
    return Paragraph(_text(value), styles["header_cell"])


def _format_cell(column: str, value: Any) -> str:
    if value is None:
        return "N/A"
    if column in {"1Y return", "vs S&P 500", "Revenue growth", "Profit margin"}:
        suffix = " pp" if column == "vs S&P 500" else "%"
        return f"{float(value):.2f}{suffix}"
    if column == "Confidence":
        return f"{value}%"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _format_watchlist_cell(column: str, value: Any) -> str:
    if value is None:
        return "N/A"
    if column in {"Opportunity score", "Entry readiness", "Committee score", "Risk score", "Momentum score", "Market environment"}:
        return f"{float(value):.1f}"
    if column == "1Y vs S&P 500":
        return f"{float(value):+.2f} pp"
    return str(value)


def _get(value: Any, key: str, default: Any = None) -> Any:
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


def _text(value: Any) -> str:
    return escape(_plain_text(value))


def _plain_text(value: Any) -> str:
    return str(value).replace("—", "-").replace("–", "-").replace("…", "...").replace("·", "|")


def _page_footer(canvas, document) -> None:
    canvas.saveState()
    width, _ = document.pagesize
    canvas.setStrokeColor(GOLD)
    canvas.setLineWidth(1)
    canvas.line(document.leftMargin, 0.45 * inch, width - document.rightMargin, 0.45 * inch)
    canvas.setFont("Helvetica", 6.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(document.leftMargin, 0.27 * inch, "PROJECT ATLAS | ANALYSIS-ONLY INVESTMENT RESEARCH")
    canvas.drawRightString(width - document.rightMargin, 0.27 * inch, f"Page {document.page}")
    canvas.restoreState()
