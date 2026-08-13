from __future__ import annotations

import argparse
import html
import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from core.providers.cached_provider import CachedEconomicDataProvider
from core.providers.economic_provider import FredProvider
from core.providers.news_provider import GdeltNewsProvider
from core.services.daily_briefing_service import build_daily_briefing
from core.services.daily_intelligence_summary_service import build_daily_intelligence_summary
from core.services.feed_intelligence_service import build_entity_catalog, build_feed_analytics
from core.services.holding_guidance_service import build_holding_guidance
from core.services.market_news_service import build_market_news
from core.services.market_provider_factory import build_live_market_provider
from core.services.market_pulse_service import build_market_pulse
from core.services.provider_cache import ProviderCache
from core.services.report_repository import ReportRepository
from core.services.trending_intelligence_service import build_trending_intelligence


CENTRAL = ZoneInfo("America/Chicago")


def compile_report(edition: str = "morning", output_dir: str | Path = "output/pdf") -> dict:
    load_dotenv(override=True)
    now = datetime.now(CENTRAL)
    cache = ProviderCache(os.getenv("ATLAS_CACHE_PATH", "data/provider_cache.db"))
    provider = build_live_market_provider(cache)
    macro = CachedEconomicDataProvider(FredProvider(), cache)
    repository = ReportRepository(os.getenv("ATLAS_DATABASE_PATH", "data/atlas.db"))

    watchlist = repository.watchlist()
    holdings = repository.portfolio_holdings()
    universe = sorted(set(watchlist + holdings + repository.report_tickers()))
    reports = repository.latest_reports(universe)
    discovery = repository.latest_discovery_run()
    positions = [{"ticker": ticker, "allocation": None} for ticker in holdings]
    briefing = build_daily_briefing(
        reports, positions, repository.alerts(100, unread_only=True), discovery,
        provider.status(), now=now,
    )
    pulse = build_market_pulse(provider, macro)
    news = build_market_news(GdeltNewsProvider(cache), universe, limit=12, now=now)
    intelligence_state = repository.configuration("market_intelligence") or {}
    sources = intelligence_state.get("sources", [])
    commentary = intelligence_state.get("commentary", [])
    posts = intelligence_state.get("raw_posts", [])
    catalog = build_entity_catalog(watchlist, discovery, reports)
    feed = build_feed_analytics(sources, posts, commentary, catalog, reports)
    trending = build_trending_intelligence(sources, commentary)
    intelligence = build_daily_intelligence_summary(
        briefing, trending, feed, intelligence_state.get("last_x_sync"),
    )
    holding_guidance = build_holding_guidance(holdings, reports)
    discovery_rows = list((discovery or {}).get("rows", []))[:8]
    report = {
        "edition": edition.lower(), "generated_at": now.isoformat(),
        "title": f"Atlas {edition.title()} Executive Market Report",
        "subject": f"Atlas {edition.title()} Report - {now:%B %d, %Y}",
        "executive_summary": _executive_summary(briefing, pulse, intelligence, news, holding_guidance, discovery_rows),
        "market_pulse": pulse, "briefing": briefing, "holding_guidance": holding_guidance,
        "market_intelligence": intelligence, "news": news,
        "discovery": discovery_rows,
        "sources": sorted(set(
            [pulse.get("market_source"), pulse.get("macro_source"), news.get("provider")]
            + [str(row.get("Provider")) for row in (discovery or {}).get("rows", [])]
        ) - {None, "None", ""}),
    }
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    pdf_path = output / f"atlas-{edition.lower()}-executive-report.pdf"
    render_pdf(report, pdf_path)
    report["pdf_path"] = str(pdf_path.resolve())
    report["email_html"] = render_email_html(report)
    manifest = output / f"atlas-{edition.lower()}-executive-report.json"
    manifest.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    report["manifest_path"] = str(manifest.resolve())
    return report


def _executive_summary(briefing, pulse, intelligence, news, guidance, discovery) -> str:
    oil = pulse.get("oil") or {}
    oil_text = "The official WTI benchmark is unavailable."
    if oil.get("value") is not None:
        oil_text = f"Official WTI is ${oil['value']:.2f} per barrel and trending {str(oil.get('trend') or 'unknown').lower()}."
    bonds = ", ".join(
        f"{row['ticker']} {row.get('change_percent') or 0:+.2f}%" for row in pulse.get("bonds", [])
    ) or "unavailable"
    metals = ", ".join(
        f"{row['label'].replace(' futures', '')} ${row['price']:.2f} ({row.get('change_percent') or 0:+.2f}%)"
        for row in pulse.get("commodities", []) if row.get("ticker") in {"GC=F", "SI=F", "HG=F"} and row.get("price") is not None
    ) or "unavailable"
    opportunities = [row for row in discovery
                     if row.get("Research label") != "Pass for now" and row.get("On radar") is not True][:3]
    opportunity_text = "; ".join(
        f"{row.get('Ticker')} ({row.get('Research label')}, score {float(row.get('Discovery score') or 0):.1f}, {row.get('Data status')})"
        for row in opportunities
    ) or "no current candidate cleared the preliminary research filter"
    high_caution = guidance.get("counts", {}).get("Consider less", 0) + guidance.get("counts", {}).get("Caution", 0)
    analyst_context = " ".join(row.get("Note", "") for row in pulse.get("analyst_notes", [])[:3])
    tone = str(pulse.get("tone") or "Mixed")
    simple_market = {
        "Risk-on": "Most major parts of the market are moving higher, which means investors are generally feeling optimistic today",
        "Risk-off": "Most major parts of the market are moving lower, which means investors are being more cautious today",
        "Mixed": "The market is sending mixed signals today, so there is no clear broad direction",
    }.get(tone, "The market does not have a clear broad direction today")
    posture = str(briefing.get("posture") or "unavailable").lower()
    opportunity_count = len(opportunities)
    opportunity_intro = (
        f"Atlas found {opportunity_count} possible new idea{'s' if opportunity_count != 1 else ''} worth researching"
        if opportunity_count else "Atlas did not find a new idea strong enough for priority research"
    )
    oil_advice = "Oil data is unavailable, so Atlas cannot judge its effect on inflation and company costs."
    if oil.get("value") is not None:
        oil_direction = str(oil.get("trend") or "unknown").lower()
        oil_advice = (
            f"Oil is about ${oil['value']:.2f} per barrel and is {oil_direction}; higher oil can help energy companies, "
            "but it can also raise fuel, shipping, and everyday business costs."
        )
    advisor_opening = (
        f"Here is the simple takeaway: {simple_market}. That is helpful, but it does not mean every stock is safe to buy. "
        f"Atlas's overall research stance is {posture}, so treat today's strength as a reason to review opportunities carefully, "
        f"not as a reason to make broad changes all at once. {oil_advice} {opportunity_intro}, and {high_caution} of your current "
        f"holding{'s' if high_caution != 1 else ''} need{'s' if high_caution == 1 else ''} extra attention."
    )
    return (
        f"{advisor_opening} {pulse.get('market_summary', 'Cross-asset direction is unavailable')} The saved research posture is "
        f"{briefing.get('posture', 'unavailable').lower()}. Bonds and credit: {bonds}. {oil_text} "
        f"Precious and industrial metals: {metals}. Discovery opportunities for deeper review: {opportunity_text}. "
        f"Atlas ranked {len(news.get('articles', []))} market-moving stories, found "
        f"{intelligence.get('trending_stocks', 0)} feed-trending stocks, and flagged {high_caution} holding caution "
        f"or consider-less item(s). Analyst context: {analyst_context}"
    )

def render_email_html(report: dict) -> str:
    pulse = report["market_pulse"]
    precious_metals = [
        row for row in pulse.get("commodities", []) if row.get("ticker") in {"GC=F", "SI=F"}
    ]
    metals_html = "".join(
        f"<tr><td>{html.escape(row['label'].replace(' futures', ''))}</td><td>${row['price']:,.2f}</td>"
        f"<td style='color:{'#16803c' if (row.get('change_percent') or 0) >= 0 else '#b42318'}'>"
        f"{row.get('change_percent') or 0:+.2f}%</td><td>{html.escape(str(row.get('direction') or 'Unavailable'))}</td></tr>"
        for row in precious_metals if row.get("price") is not None
    ) or "<tr><td colspan='4'>Live Gold and Silver quotes are currently unavailable.</td></tr>"
    quote_rows = "".join(
        f"<tr><td>{html.escape(row['label'])}</td><td>${row['price']:.2f}</td>"
        f"<td style='color:{'#16803c' if (row.get('change_percent') or 0) >= 0 else '#b42318'}'>"
        f"{row.get('change_percent') or 0:+.2f}%</td></tr>" for row in pulse.get("quotes", [])
        if row.get("price") is not None
    )
    news_rows = "".join(
        f"<li><a href='{html.escape(str(row.get('Article') or ''))}'>{html.escape(str(row.get('Headline') or ''))}</a> "
        f"<b>({row.get('Impact', 0):.0f}/100 impact)</b><br>{html.escape(str(row.get('Why it matters') or ''))}</li>"
        for row in report["news"].get("articles", [])[:8]
    )
    actions = "".join(
        f"<li><b>{html.escape(str(row.get('Priority')))}</b> - {html.escape(str(row.get('Action')))}: "
        f"{html.escape(str(row.get('Why')))}</li>" for row in report["briefing"].get("actions", [])
    ) or "<li>No urgent saved-evidence action.</li>"
    notes_html = "".join(
        f"<li><b>{html.escape(str(row.get('Theme')))}</b>: {html.escape(str(row.get('Note')))}</li>"
        for row in pulse.get("analyst_notes", [])
    ) or "<li>No cross-asset analyst note is available.</li>"
    discovery_html = "".join(
        f"<li><b>{html.escape(str(row.get('Ticker')))}</b> - {html.escape(str(row.get('Research label')))} "
        f"(score {float(row.get('Discovery score') or 0):.1f}, {html.escape(str(row.get('Data status')))})<br>"
        f"{html.escape(str(row.get('Why it surfaced') or 'Review the saved evidence.'))}</li>"
        for row in report.get("discovery", [])
        if row.get("Research label") != "Pass for now" and row.get("On radar") is not True
    ) or "<li>No current Discovery opportunity cleared the preliminary filter.</li>"
    return f"""<html><body style='font-family:Arial,sans-serif;color:#172033;max-width:820px;margin:auto'>
    <div style='background:#15233c;color:white;padding:24px;border-radius:10px 10px 0 0'>
      <div style='font-size:13px;letter-spacing:1px'>PROJECT ATLAS</div><h1 style='margin:8px 0'>{html.escape(report['title'])}</h1>
      <div>{html.escape(report['generated_at'])}</div></div>
    <div style='padding:24px;border:1px solid #d9e0ea'><h2>Executive summary</h2><p>{html.escape(report['executive_summary'])}</p>
    <h2>Market at a glance</h2><table cellpadding='8' cellspacing='0' style='border-collapse:collapse;width:100%'>{quote_rows}</table>
    <h2>Precious metals</h2><p>Gold can reflect defensive demand and inflation concerns; silver also carries an industrial-demand signal.</p>
    <table cellpadding='8' cellspacing='0' style='border-collapse:collapse;width:100%'><tr><th align='left'>Metal</th><th align='left'>Price</th><th align='left'>Day move</th><th align='left'>Direction</th></tr>{metals_html}</table>
    <h2>Atlas analyst notes</h2><ul>{notes_html}</ul><h2>Discovery opportunities</h2><ul>{discovery_html}</ul>
    <h2>What needs attention</h2><ol>{actions}</ol><h2>Most important market news</h2><ol>{news_rows}</ol>
    <p><b>Market Intelligence:</b> {html.escape(report['market_intelligence'].get('executive_summary',''))}</p>
    <p style='font-size:12px;color:#667085'>The attached PDF contains holdings guidance, Discovery candidates, news evidence, timestamps, and provider attribution. Analysis only - not investment advice.</p></div></body></html>"""


def render_pdf(report: dict, path: Path) -> None:
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="AtlasTitle", parent=styles["Title"], textColor=colors.HexColor("#15233c"),
                              fontSize=22, leading=27, alignment=TA_CENTER, spaceAfter=14))
    styles.add(ParagraphStyle(name="Section", parent=styles["Heading2"], textColor=colors.HexColor("#c23b38"),
                              fontSize=14, leading=18, spaceBefore=12, spaceAfter=7))
    styles.add(ParagraphStyle(name="Small", parent=styles["BodyText"], fontSize=8, leading=11, textColor=colors.HexColor("#596579")))
    doc = SimpleDocTemplate(str(path), pagesize=letter, rightMargin=.55*inch, leftMargin=.55*inch,
                            topMargin=.55*inch, bottomMargin=.55*inch,
                            title=report["title"], author="Project Atlas")
    story = [Paragraph("PROJECT ATLAS", styles["Small"]), Paragraph(report["title"], styles["AtlasTitle"]),
             Paragraph(html.escape(report["generated_at"]), styles["Small"]), Spacer(1, 10),
             Paragraph("Executive summary", styles["Section"]), Paragraph(html.escape(report["executive_summary"]), styles["BodyText"])]
    pulse = report["market_pulse"]
    story += [Paragraph("Market at a glance", styles["Section"])]
    market_data = [["Market", "Price", "Day", "Direction"]] + [[
        row.get("label"), f"${row['price']:.2f}" if row.get("price") is not None else "N/A",
        f"{row.get('change_percent'):+.2f}%" if row.get("change_percent") is not None else "N/A", row.get("direction"),
    ] for row in pulse.get("quotes", [])]
    story.append(_table(market_data, [3.25*inch, 1.0*inch, .85*inch, .85*inch]))
    oil = pulse.get("oil") or {}
    story.append(Paragraph(
        f"WTI oil: {oil.get('value', 'Unavailable')} {html.escape(str(oil.get('unit') or ''))} | "
        f"Trend: {html.escape(str(oil.get('trend') or 'Unavailable'))} | As of: {html.escape(str(oil.get('observed_at') or 'Unavailable'))}",
        styles["Small"],
    ))
    precious_metals = [row for row in pulse.get("commodities", []) if row.get("ticker") in {"GC=F", "SI=F"}]
    metals_data = [["Metal", "Price", "Day move", "Direction"]] + [[
        row.get("label", "").replace(" futures", ""),
        f"${row['price']:,.2f}" if row.get("price") is not None else "Unavailable",
        f"{row['change_percent']:+.2f}%" if row.get("change_percent") is not None else "Unavailable",
        row.get("direction") or "Unavailable",
    ] for row in precious_metals]
    if len(metals_data) == 1:
        metals_data.append(["Gold and Silver", "Unavailable", "Unavailable", "Live quotes not returned"])
    story += [Paragraph("Precious metals", styles["Section"]),
              Paragraph("Gold can reflect defensive demand and inflation concerns; silver also carries an industrial-demand signal.", styles["Small"]),
              _table(metals_data, [2.5*inch, 1.25*inch, 1.25*inch, 1.35*inch])]
    story += [Paragraph("Atlas analyst notes", styles["Section"])]
    for note in pulse.get("analyst_notes", []):
        story.append(Paragraph(f"<b>{html.escape(str(note.get('Theme')))}:</b> {html.escape(str(note.get('Note')))}", styles["BodyText"]))
        story.append(Spacer(1, 4))
    story += [Paragraph("Priority actions", styles["Section"])]
    actions = report["briefing"].get("actions", [])
    story.append(_table([["Priority", "Action", "Why"]] + [[a.get("Priority"), a.get("Action"), a.get("Why")] for a in actions]
                        if actions else [["Status", "Action", "Why"], ["Monitor", "No urgent action", "Continue monitoring"]],
                        [.8*inch, 1.7*inch, 3.85*inch]))
    story += [Paragraph("Holdings guidance", styles["Section"])]
    holdings = report["holding_guidance"].get("rows", [])
    story.append(_table([["Ticker", "Direction", "Caution", "Why"]] + [[h.get("Ticker"), h.get("Direction"), h.get("Caution"), h.get("Why")] for h in holdings]
                        if holdings else [["Ticker", "Direction", "Caution", "Why"], ["-", "No holdings saved", "-", "Add holdings in Atlas"]],
                        [.65*inch, 1.15*inch, .75*inch, 3.8*inch]))
    story += [PageBreak(), Paragraph("Market Intelligence", styles["Section"]),
              Paragraph(html.escape(report["market_intelligence"].get("executive_summary", "No feed summary available.")), styles["BodyText"]),
              Paragraph("Discovery", styles["Section"])]
    discovery = report.get("discovery", [])
    story.append(_table([["Rank", "Ticker", "Label", "Score", "Evidence"]] + [[d.get("Rank"), d.get("Ticker"), d.get("Research label"), d.get("Discovery score"), d.get("Data status")] for d in discovery]
                        if discovery else [["Rank", "Ticker", "Label", "Score", "Evidence"], ["-", "-", "No saved candidates", "-", "-"]],
                        [.5*inch, .65*inch, 1.7*inch, .65*inch, 2.8*inch]))
    story += [Paragraph("Market-moving news", styles["Section"])]
    for index, article in enumerate(report["news"].get("articles", []), 1):
        link = html.escape(str(article.get("Article") or ""), quote=True)
        title = html.escape(str(article.get("Headline") or "Untitled"))
        story.append(Paragraph(f"<b>{index}. <a href='{link}' color='#1f5da8'>{title}</a></b> - Impact {article.get('Impact', 0):.0f}/100", styles["BodyText"]))
        story.append(Paragraph(html.escape(str(article.get("Why it matters") or "")), styles["Small"]))
        story.append(Paragraph(f"Source: {html.escape(str(article.get('Source') or 'Unknown'))} | Published: {html.escape(str(article.get('Published') or 'Unknown'))}", styles["Small"]))
        story.append(Spacer(1, 6))
    story += [Paragraph("Data sources and limitations", styles["Section"]),
              Paragraph(html.escape(", ".join(report.get("sources", [])) or "No sources recorded"), styles["Small"]),
              Paragraph("Atlas combines live and cached provider evidence. YahooQuery is an unofficial Yahoo Finance interface and may be delayed. News impact is a relevance score, not a price prediction. Analysis only - not investment advice.", styles["Small"])]
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)


def _table(data, widths):
    cell_style = ParagraphStyle("AtlasTableCell", parent=getSampleStyleSheet()["BodyText"], fontSize=7, leading=9)
    wrapped = [[Paragraph(html.escape(str(cell if cell is not None else "-")), cell_style) for cell in row] for row in data]
    table = Table(wrapped, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#15233c")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), .35, colors.HexColor("#cfd7e3")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f7fb")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#667085"))
    canvas.drawString(.55*inch, .3*inch, "Project Atlas - analysis only")
    canvas.drawRightString(7.95*inch, .3*inch, f"Page {doc.page}")
    canvas.restoreState()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--edition", choices=("morning", "afternoon"), default="morning")
    parser.add_argument("--output-dir", default="output/pdf")
    args = parser.parse_args()
    result = compile_report(args.edition, args.output_dir)
    print(json.dumps({key: result[key] for key in ("subject", "pdf_path", "manifest_path", "executive_summary")}, indent=2))


if __name__ == "__main__":
    main()
