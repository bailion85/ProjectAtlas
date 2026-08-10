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

    macro = _get(report, "macro", {})
    if macro:
        story.extend([_section("Macro environment", styles), _macro_table(macro, styles, document.width)])

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

    summary = comparison.get("summary", [])
    if summary:
        columns = ["Rank", "Ticker", "Score", "Vote", "Confidence", "1Y return", "vs S&P 500", "P/E", "Revenue growth", "Profit margin", "Beta", "Strongest factor", "Weakest factor"]
        rows = [[_hp(column, styles) for column in columns]]
        for item in summary:
            rows.append([_p(_format_cell(column, item.get(column)), styles) for column in columns])
        widths = [0.4, 0.6, 0.6, 0.7, 0.8, 0.75, 0.85, 0.6, 0.95, 0.9, 0.55, 0.95, 0.95]
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
