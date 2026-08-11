from __future__ import annotations

import importlib
import inspect
import json
import os

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

import core.providers.demo_provider as demo_provider_module
import core.providers.market_provider as market_provider_module
import core.providers.cached_provider as cached_provider_module
from core.providers.demo_provider import DemoProvider
from core.providers.market_provider import AlphaVantageProvider, ProviderError
from core.providers.economic_provider import DemoEconomicProvider, FredProvider
from core.providers.event_provider import DemoEconomicEventProvider
from core.providers.calendar_provider import DemoCatalystCalendarProvider
from core.providers.cached_provider import CachedEconomicDataProvider, CachedMarketDataProvider
from core.services.provider_cache import ProviderCache
import core.models.research as research_model_module
import core.services.committee_service as committee_service_module
import core.services.analysis_service as analysis_service_module
import core.services.comparison_service as comparison_service_module
import core.services.report_repository as report_repository_module
import core.services.risk_service as risk_service_module
import core.services.readiness_service as readiness_service_module
import core.services.watchlist_service as watchlist_service_module
import core.services.alert_service as alert_service_module
import core.services.portfolio_exposure_service as portfolio_exposure_service_module
import core.services.change_tracking_service as change_tracking_service_module
import core.services.scheduler_service as scheduler_service_module
import core.services.live_readiness_service as live_readiness_service_module
from core.services.market_regime_service import analyze_market_environment
from core.services.watchlist_service import RANKING_MODES, rank_watchlist
from core.services.catalyst_service import global_calendar
from core.services.backtest_service import backtest_golden_cross
from core.services.alert_service import ALERT_TYPES, AlertService
from core.services.portfolio_exposure_service import analyze_portfolio_exposure
from core.services.change_tracking_service import compare_reports
from core.services.scheduler_service import DEFAULT_SCHEDULE, SCOPES, ScheduledResearchService
from core.services.live_readiness_service import (
    environment_readiness, readiness_summary, test_macro_provider, test_market_provider,
)
from core.services.settings_service import (
    DEFAULT_CONFIG, load_configuration, profile as settings_profile,
    save_configuration, validate_configuration,
)

try:
    import core.services.pdf_service as pdf_service_module
    if (not hasattr(pdf_service_module, "render_watchlist_pdf") or
            not hasattr(pdf_service_module, "render_portfolio_pdf") or
            not hasattr(pdf_service_module, "render_change_pdf")):
        pdf_service_module = importlib.reload(pdf_service_module)
    render_comparison_pdf = pdf_service_module.render_comparison_pdf
    render_report_pdf = pdf_service_module.render_report_pdf
    render_watchlist_pdf = pdf_service_module.render_watchlist_pdf
    render_portfolio_pdf = pdf_service_module.render_portfolio_pdf
    render_change_pdf = pdf_service_module.render_change_pdf
except ModuleNotFoundError as exc:
    if exc.name != "reportlab":
        raise
    render_comparison_pdf = None
    render_report_pdf = None
    render_watchlist_pdf = None
    render_portfolio_pdf = None
    render_change_pdf = None


# Streamlit can preserve imported project modules across app-only hot reloads.
modules_reloaded = False
if (not hasattr(cached_provider_module.CachedMarketDataProvider, "daily_history") or
        getattr(demo_provider_module, "DEMO_PROVIDER_VERSION", 0) < 2 or
        getattr(market_provider_module, "MARKET_PROVIDER_VERSION", 0) < 2):
    market_provider_module = importlib.reload(market_provider_module)
    demo_provider_module = importlib.reload(demo_provider_module)
    cached_provider_module = importlib.reload(cached_provider_module)
    DemoProvider = demo_provider_module.DemoProvider
    AlphaVantageProvider = market_provider_module.AlphaVantageProvider
    ProviderError = market_provider_module.ProviderError
    CachedMarketDataProvider = cached_provider_module.CachedMarketDataProvider
    CachedEconomicDataProvider = cached_provider_module.CachedEconomicDataProvider
    modules_reloaded = True
if "configuration" not in research_model_module.ResearchReport.__dataclass_fields__:
    research_model_module = importlib.reload(research_model_module)
    modules_reloaded = True
if not hasattr(committee_service_module, "score_contributions"):
    committee_service_module = importlib.reload(committee_service_module)
    modules_reloaded = True
if "weights" not in inspect.signature(risk_service_module.analyze_risk).parameters:
    risk_service_module = importlib.reload(risk_service_module)
    modules_reloaded = True
if "weights" not in inspect.signature(readiness_service_module.analyze_entry_readiness).parameters:
    readiness_service_module = importlib.reload(readiness_service_module)
    modules_reloaded = True
if getattr(portfolio_exposure_service_module, "PORTFOLIO_EXPOSURE_SERVICE_VERSION", 0) < 1:
    portfolio_exposure_service_module = importlib.reload(portfolio_exposure_service_module)
    analyze_portfolio_exposure = portfolio_exposure_service_module.analyze_portfolio_exposure
    modules_reloaded = True
if getattr(change_tracking_service_module, "CHANGE_TRACKING_SERVICE_VERSION", 0) < 1:
    change_tracking_service_module = importlib.reload(change_tracking_service_module)
    compare_reports = change_tracking_service_module.compare_reports
    modules_reloaded = True
if getattr(scheduler_service_module, "SCHEDULER_SERVICE_VERSION", 0) < 1:
    scheduler_service_module = importlib.reload(scheduler_service_module)
    DEFAULT_SCHEDULE = scheduler_service_module.DEFAULT_SCHEDULE
    SCOPES = scheduler_service_module.SCOPES
    ScheduledResearchService = scheduler_service_module.ScheduledResearchService
    modules_reloaded = True
if getattr(live_readiness_service_module, "LIVE_READINESS_SERVICE_VERSION", 0) < 1:
    live_readiness_service_module = importlib.reload(live_readiness_service_module)
    environment_readiness = live_readiness_service_module.environment_readiness
    readiness_summary = live_readiness_service_module.readiness_summary
    test_macro_provider = live_readiness_service_module.test_macro_provider
    test_market_provider = live_readiness_service_module.test_market_provider
    modules_reloaded = True
if "weights" not in inspect.signature(watchlist_service_module.rank_watchlist).parameters:
    watchlist_service_module = importlib.reload(watchlist_service_module)
    RANKING_MODES = watchlist_service_module.RANKING_MODES
    rank_watchlist = watchlist_service_module.rank_watchlist
    modules_reloaded = True
if (modules_reloaded or not hasattr(report_repository_module.ReportRepository, "portfolio_positions") or
        not hasattr(report_repository_module.ReportRepository, "report_tickers") or
        not hasattr(report_repository_module.ReportRepository, "scheduler_runs")):
    report_repository_module = importlib.reload(report_repository_module)
    modules_reloaded = True
ReportRepository = report_repository_module.ReportRepository
if modules_reloaded or "benchmark_daily_history" not in inspect.signature(analysis_service_module.AnalysisService.analyze).parameters:
    analysis_service_module = importlib.reload(analysis_service_module)
    modules_reloaded = True
AnalysisService = analysis_service_module.AnalysisService
if modules_reloaded or getattr(comparison_service_module, "COMPARISON_SERVICE_VERSION", 0) < 7:
    comparison_service_module = importlib.reload(comparison_service_module)
ComparisonService = comparison_service_module.ComparisonService
if modules_reloaded or "readiness" not in alert_service_module.ALERT_TYPES:
    alert_service_module = importlib.reload(alert_service_module)
    ALERT_TYPES = alert_service_module.ALERT_TYPES
    AlertService = alert_service_module.AlertService
PRESETS = committee_service_module.PRESETS
STRATEGIES = committee_service_module.STRATEGIES
normalize_weights = committee_service_module.normalize_weights


load_dotenv()
st.set_page_config(page_title="Project Atlas", page_icon="🧭", layout="wide")
SERVICE_CACHE_VERSION = "live-readiness-v2"


@st.cache_resource
def services(cache_version: str):
    # Changing this key refreshes long-lived objects after service or database upgrades.
    _ = cache_version
    provider_name = os.getenv("ATLAS_DATA_PROVIDER", "demo").lower()
    base_provider = AlphaVantageProvider() if provider_name == "alpha_vantage" else DemoProvider()
    macro_provider_name = os.getenv("ATLAS_MACRO_PROVIDER", "demo").lower()
    base_macro_provider = FredProvider() if macro_provider_name == "fred" else DemoEconomicProvider()
    cache = ProviderCache(os.getenv("ATLAS_CACHE_PATH", "data/provider_cache.db"))
    provider = CachedMarketDataProvider(base_provider, cache)
    macro_provider = CachedEconomicDataProvider(base_macro_provider, cache)
    repository = ReportRepository(os.getenv("ATLAS_DATABASE_PATH", "data/atlas.db"))
    event_provider = DemoEconomicEventProvider()
    calendar_provider = DemoCatalystCalendarProvider()
    return provider, macro_provider, event_provider, calendar_provider, cache, repository, AnalysisService(provider, repository, macro_provider, event_provider, calendar_provider)


st.title("Project Atlas")
st.caption("Analysis-only investment research — no trading or brokerage connectivity")

try:
    provider, macro_provider, event_provider, calendar_provider, provider_cache, repository, analysis = services(SERVICE_CACHE_VERSION)
except ProviderError as exc:
    st.error(f"Data provider configuration error: {exc}")
    st.info("Set ATLAS_DATA_PROVIDER=demo to use Atlas without a live-data API key.")
    st.stop()

active_configuration = load_configuration(repository)

if provider.name.startswith("Demo"):
    st.warning("Demo mode is active. Figures are illustrative and are not live market data.")
if macro_provider.name.startswith("Demo"):
    st.warning("Demo macro mode is active. Economic figures are illustrative and are not live.")
else:
    st.info("This product uses the FRED® API but is not endorsed or certified by the Federal Reserve Bank of St. Louis.")
if render_report_pdf is None:
    st.warning("PDF export requires the updated dependencies. Run: python -m pip install -r requirements.txt")

dashboard, portfolio_tab, research_tab, backtest_tab, compare_tab, changes_tab, alerts_tab, readiness_tab, settings_tab, history_tab = st.tabs(
    ["Dashboard", "Portfolio", "Research", "Backtest", "Compare", "Changes", "Alerts", "Data readiness", "Settings", "Report history"]
)

with dashboard:
    st.subheader("Market environment")
    try:
        dashboard_environment = analyze_market_environment(event_provider.snapshot(), macro_provider.snapshot())
        with st.container(horizontal=True):
            st.metric("Environment score", f"{dashboard_environment['score']:.1f}/100", border=True)
            st.metric("Market posture", dashboard_environment["label"], border=True)
            st.metric("Economic events", len(dashboard_environment["events"]), border=True)
        st.info(dashboard_environment["buying_context"])
        st.dataframe(
            [
                {
                    "Event": event["title"],
                    "Category": event["category"],
                    "Direction": event["expected_direction"],
                    "Impact": event["impact"],
                    "Confidence": event["confidence"],
                    "Duration": event["duration"],
                    "Affected sectors": ", ".join(event["affected_sectors"]),
                }
                for event in dashboard_environment["events"]
            ],
            column_config={
                "Confidence": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%d%%"),
            },
            hide_index=True,
        )
        with st.expander("How Atlas reached this view"):
            st.write(dashboard_environment["macro_thesis"])
            for event in dashboard_environment["events"]:
                st.markdown(f"**{event['title']}**")
                st.write(event["supporting_evidence"])
                st.caption(f"Counterpoint: {event['counterpoint']} · Source: {event['source']}")
        st.caption(f"Event source: {dashboard_environment['event_provider']} · Macro source: {dashboard_environment['macro_provider']}")
    except (ProviderError, ValueError) as exc:
        st.warning(f"Market environment is temporarily unavailable: {exc}")

    st.subheader("Watchlist")
    query = st.text_input("Search by ticker or company", placeholder="AAPL or Apple")
    if query:
        try:
            for match in provider.search(query):
                c1, c2 = st.columns([5, 1])
                c1.write(f"**{match['symbol']}** — {match['name']}")
                if c2.button("Add", key=f"add-{match['symbol']}"):
                    repository.add_ticker(match["symbol"])
                    st.rerun()
        except (ProviderError, ValueError) as exc:
            st.error(str(exc))
    watchlist = repository.watchlist()
    if not watchlist:
        st.info("Your watchlist is empty. Search above to add a company.")
    for ticker in watchlist:
        c1, c2 = st.columns([5, 1])
        c1.write(ticker)
        if c2.button("Remove", key=f"remove-{ticker}"):
            repository.remove_ticker(ticker)
            st.rerun()

    st.markdown("#### Earnings and catalyst calendar")
    dashboard_calendar_snapshot = calendar_provider.snapshot()
    calendar_rows = global_calendar(dashboard_calendar_snapshot, watchlist)
    if calendar_rows:
        st.dataframe(
            [{
                "Date": event["date"], "Days": event["days_until"], "Event": event["title"],
                "Category": event["category"], "Scope": event["scope"].title(),
                "Importance": event["importance"], "Confidence": event["confidence"],
            } for event in calendar_rows],
            column_config={
                "Date": st.column_config.DateColumn(format="MMM DD, YYYY"),
                "Importance": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%d"),
                "Confidence": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%d%%"),
            },
            hide_index=True,
        )
        st.caption(f"Source: {dashboard_calendar_snapshot['provider']} · Dates and scenarios are illustrative.")

    if watchlist:
        st.markdown("#### Ranked watchlist")
        controls = st.container(horizontal=True, vertical_alignment="bottom")
        with controls:
            watchlist_preset = st.selectbox("Analysis preset", list(PRESETS), key="watchlist_preset")
            ranking_mode = st.selectbox("Rank by", RANKING_MODES, key="watchlist_ranking_mode")
            analyze_watchlist = st.button("Analyze all", type="primary", key="analyze-watchlist")
        if analyze_watchlist:
            try:
                macro_snapshot = macro_provider.snapshot()
                environment_snapshot = analyze_market_environment(event_provider.snapshot(), macro_snapshot)
                calendar_snapshot = calendar_provider.snapshot()
                benchmark_history = provider.history("SPY")
                benchmark_daily_history = provider.daily_history("SPY")
                progress = st.progress(0, text="Analyzing watchlist…")
                for index, symbol in enumerate(watchlist, start=1):
                    progress.progress((index - 1) / len(watchlist), text=f"Analyzing {symbol}…")
                    analysis.analyze(
                        symbol,
                        PRESETS[watchlist_preset],
                        macro_snapshot=macro_snapshot,
                        benchmark_history=benchmark_history,
                        market_environment=environment_snapshot,
                        calendar_snapshot=calendar_snapshot,
                        benchmark_daily_history=benchmark_daily_history,
                    )
                progress.progress(1.0, text="Watchlist analysis complete")
                st.success(f"Analyzed {len(watchlist)} companies using the {watchlist_preset} preset.")
                st.rerun()
            except (ProviderError, ValueError) as exc:
                st.error(f"Watchlist analysis failed: {exc}")
        latest_reports = repository.latest_reports(watchlist)
        ranking = rank_watchlist(
            watchlist, latest_reports, ranking_mode,
            active_configuration["ranking_weights"], active_configuration["freshness_days"],
        )
        if ranking["missing"]:
            st.warning("Run Analyze all to create reports for: " + ", ".join(ranking["missing"]))
        if ranking["stale"]:
            st.warning("Reports older than seven days: " + ", ".join(ranking["stale"]))
        if ranking["rows"]:
            display_rows = [{key: value for key, value in row.items() if key != "report_id"} for row in ranking["rows"]]
            st.dataframe(
                display_rows,
                column_config={
                    "Rank": st.column_config.NumberColumn(pinned=True, format="%d"),
                    "Ticker": st.column_config.TextColumn(pinned=True),
                    "Opportunity score": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f"),
                    "Entry readiness": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f"),
                    "Committee score": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f"),
                    "Risk score": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f"),
                    "Momentum score": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f"),
                    "Market environment": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f"),
                    "1Y vs S&P 500": st.column_config.NumberColumn(format="%+.2f pp"),
                },
                hide_index=True,
            )
            if render_watchlist_pdf:
                st.download_button(
                    "Download ranked watchlist PDF",
                    data=render_watchlist_pdf(ranking),
                    file_name="atlas-ranked-watchlist.pdf",
                    mime="application/pdf",
                    key="download-ranked-watchlist",
                )
            with st.expander("Why companies ranked this way"):
                for row in ranking["rows"]:
                    st.markdown(f"**#{row['Rank']} {row['Ticker']} — {row['Company']}**")
                    st.write(row["Why"])
            ranking_weights = active_configuration["ranking_weights"]
            st.caption(
                "Opportunity score = " + " + ".join(
                    f"{value:.0f}% {name.replace('_', ' ')}" for name, value in ranking_weights.items()
                ) + "."
            )

with portfolio_tab:
    st.subheader("Portfolio exposure")
    st.caption("Enter percentage allocations to assess concentration and shared research risks. No brokerage connection or trading is available.")
    saved_positions = repository.portfolio_positions()
    if saved_positions:
        position_frame = pd.DataFrame([
            {"Ticker": item["ticker"], "Allocation": item["allocation"]} for item in saved_positions
        ])
    else:
        position_frame = pd.DataFrame({
            "Ticker": pd.Series(dtype="string"),
            "Allocation": pd.Series(dtype="float"),
        })
    edited_positions = st.data_editor(
        position_frame,
        key="portfolio-position-editor",
        num_rows="dynamic",
        hide_index=True,
        column_config={
            "Ticker": st.column_config.TextColumn("Ticker", required=True, pinned=True),
            "Allocation": st.column_config.NumberColumn(
                "Allocation %", min_value=0.0, max_value=100.0, step=1.0, format="%.1f%%", required=True,
            ),
        },
    )
    scenario_positions = edited_positions.to_dict("records")
    scenario_symbols = list(dict.fromkeys(
        str(item.get("Ticker") or "").strip().upper() for item in scenario_positions
        if str(item.get("Ticker") or "").strip()
    ))
    portfolio_actions = st.container(horizontal=True, vertical_alignment="bottom")
    with portfolio_actions:
        if st.button("Save allocations", type="primary", key="save-portfolio-allocations"):
            try:
                repository.save_portfolio_positions(scenario_positions)
                st.success("Portfolio allocations saved.")
            except (TypeError, ValueError) as exc:
                st.error(f"Portfolio could not be saved: {exc}")
        portfolio_preset = st.selectbox(
            "Refresh preset", list(PRESETS),
            index=list(PRESETS).index(active_configuration["committee_preset"]),
            key="portfolio-refresh-preset",
        )
        refresh_portfolio = st.button(
            "Refresh holding research", key="refresh-portfolio-research", disabled=not scenario_symbols,
        )
    if refresh_portfolio:
        try:
            macro_snapshot = macro_provider.snapshot()
            environment_snapshot = analyze_market_environment(event_provider.snapshot(), macro_snapshot)
            calendar_snapshot = calendar_provider.snapshot()
            benchmark_history = provider.history("SPY")
            benchmark_daily_history = provider.daily_history("SPY")
            progress = st.progress(0, text="Refreshing portfolio researchâ€¦")
            for index, symbol in enumerate(scenario_symbols, start=1):
                progress.progress((index - 1) / len(scenario_symbols), text=f"Analyzing {symbol}â€¦")
                analysis.analyze(
                    symbol, PRESETS[portfolio_preset], macro_snapshot=macro_snapshot,
                    benchmark_history=benchmark_history, market_environment=environment_snapshot,
                    calendar_snapshot=calendar_snapshot, benchmark_daily_history=benchmark_daily_history,
                )
            progress.progress(1.0, text="Portfolio research refreshed")
            st.success(f"Refreshed {len(scenario_symbols)} holding reports.")
            st.rerun()
        except (ProviderError, ValueError) as exc:
            st.error(f"Portfolio refresh failed: {exc}")

    if scenario_symbols:
        try:
            portfolio_analysis = analyze_portfolio_exposure(
                scenario_positions, repository.latest_reports(scenario_symbols), active_configuration["freshness_days"],
            )
            with st.container(horizontal=True):
                st.metric("Portfolio posture", portfolio_analysis["posture"], border=True)
                st.metric(
                    "Weighted risk", "N/A" if portfolio_analysis["weighted_risk"] is None else f"{portfolio_analysis['weighted_risk']:.1f}/100",
                    border=True,
                )
                st.metric(
                    "Entry readiness", "N/A" if portfolio_analysis["weighted_readiness"] is None else f"{portfolio_analysis['weighted_readiness']:.1f}/100",
                    border=True,
                )
                st.metric(
                    "Committee score", "N/A" if portfolio_analysis["weighted_committee"] is None else f"{portfolio_analysis['weighted_committee']:.1f}/100",
                    border=True,
                )
                st.metric(
                    "Weighted beta", "N/A" if portfolio_analysis["weighted_beta"] is None else f"{portfolio_analysis['weighted_beta']:.2f}",
                    border=True,
                )
                st.metric("Effective positions", f"{portfolio_analysis['effective_positions']:.1f}", border=True)
            if portfolio_analysis["missing"]:
                st.warning("Refresh holding research to cover: " + ", ".join(portfolio_analysis["missing"]))
            if portfolio_analysis["warnings"]:
                st.markdown("#### Exposure flags")
                for warning in portfolio_analysis["warnings"]:
                    message = f"**{warning['title']}:** {warning['message']}"
                    if warning["severity"] == "High":
                        st.error(message)
                    else:
                        st.warning(message)
            if portfolio_analysis["rows"]:
                st.markdown("#### Holding-level analysis")
                holding_rows = [{key: value for key, value in row.items() if key != "report_id"} for row in portfolio_analysis["rows"]]
                st.dataframe(
                    holding_rows,
                    column_config={
                        "Ticker": st.column_config.TextColumn(pinned=True),
                        "Portfolio weight": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f%%"),
                        "Committee score": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f"),
                        "Risk score": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f"),
                        "Entry readiness": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f"),
                    },
                    hide_index=True,
                )
                sector_frame = pd.DataFrame(portfolio_analysis["sector_exposure"])
                if not sector_frame.empty:
                    st.markdown("#### Sector exposure")
                    st.bar_chart(sector_frame, x="Sector", y="Allocation", horizontal=True)
                if render_portfolio_pdf:
                    st.download_button(
                        "Download portfolio exposure PDF", data=render_portfolio_pdf(portfolio_analysis),
                        file_name="atlas-portfolio-exposure.pdf", mime="application/pdf", key="download-portfolio-exposure",
                    )
            st.caption(portfolio_analysis["disclosure"])
        except (TypeError, ValueError) as exc:
            st.info(str(exc))
    else:
        st.info("Add a ticker and allocation to begin. You can test changes before saving them.")

with research_tab:
    ticker = st.text_input("Ticker to analyze", value=(repository.watchlist() or ["AAPL"])[0]).upper().strip()
    with st.expander("Committee configuration"):
        preset_name = st.selectbox(
            "Start from preset", list(PRESETS), index=list(PRESETS).index(active_configuration["committee_preset"])
        )
        if st.session_state.get("last_committee_preset") != preset_name:
            for strategy, value in PRESETS[preset_name].items():
                st.session_state[f"weight_{strategy}"] = value
            st.session_state["last_committee_preset"] = preset_name
        weight_columns = st.columns(3)
        strategy_weights = {}
        for index, strategy in enumerate(STRATEGIES):
            strategy_weights[strategy] = weight_columns[index % 3].slider(
                strategy,
                min_value=0,
                max_value=100,
                key=f"weight_{strategy}",
            )
        try:
            normalized_preview = normalize_weights(strategy_weights)
            st.caption("Normalized weights: " + " · ".join(
                f"{strategy} {weight:.1f}%" for strategy, weight in normalized_preview.items()
            ))
        except ValueError as exc:
            normalized_preview = {}
            st.error(str(exc))
    if st.button("Run six-strategy analysis", type="primary", disabled=not ticker or not normalized_preview):
        try:
            with st.spinner("Building evidence-based committee assessment…"):
                st.session_state["report"] = analysis.analyze(ticker, strategy_weights)
        except (ProviderError, ValueError) as exc:
            st.error(str(exc))
        except Exception as exc:
            st.error(f"Analysis failed: {exc}")
    report = st.session_state.get("report")
    if report:
        performance = getattr(report, "performance", {})
        performance_history = getattr(report, "performance_history", [])
        macro = getattr(report, "macro", {})
        technical = getattr(report, "technical", {})
        technical_history = getattr(report, "technical_history", [])
        risk = getattr(report, "risk", {})
        environment = getattr(report, "market_environment", {})
        catalyst_calendar = getattr(report, "catalyst_calendar", {})
        backtest = getattr(report, "backtest", {})
        entry_readiness = getattr(report, "entry_readiness", {})
        contributions = getattr(report, "committee_contributions", [])
        st.subheader(f"{report.company} ({report.ticker})")
        a, b, c = st.columns(3)
        a.metric("Committee vote", report.committee_vote.title())
        b.metric("Confidence", f"{report.committee_confidence}%")
        c.metric("Data as of", report.data_as_of[:19].replace("T", " ") + " UTC")
        st.write(report.executive_summary)
        if render_report_pdf:
            st.download_button(
                "Download PDF report",
                data=render_report_pdf(report),
                file_name=f"atlas-{report.ticker.lower()}-report.pdf",
                mime="application/pdf",
                key=f"download-report-{report.ticker}-{getattr(report, 'report_id', 'current')}",
            )
        if entry_readiness:
            st.markdown("#### Entry readiness")
            with st.container(horizontal=True):
                st.metric("Readiness score", f"{entry_readiness['score']:.1f}/100", border=True)
                st.metric("Research posture", entry_readiness["posture"], border=True)
                st.metric("Evidence coverage", f"{entry_readiness['coverage_percent']:.0f}%", border=True)
            st.info(entry_readiness["summary"])
            st.dataframe(
                entry_readiness["components"],
                column_config={
                    "factor": st.column_config.TextColumn("Factor", pinned=True),
                    "score": st.column_config.ProgressColumn("Readiness score", min_value=0, max_value=100, format="%.1f"),
                    "weight": st.column_config.NumberColumn("Weight", format="%.0f%%"),
                    "explanation": st.column_config.TextColumn("Evidence"),
                },
                hide_index=True,
            )
            readiness_columns = st.columns(2)
            with readiness_columns[0]:
                st.markdown("**What would improve the setup**")
                for condition in entry_readiness["improvement_conditions"]:
                    st.write(f"- {condition}")
            with readiness_columns[1]:
                st.markdown("**What would invalidate it**")
                for condition in entry_readiness["invalidation_conditions"]:
                    st.write(f"- {condition}")
            st.caption(f"Research horizon: {entry_readiness['research_horizon']}")
            st.warning(entry_readiness["position_sizing_caution"])
            st.caption(entry_readiness["disclosure"])
        if contributions:
            st.markdown("#### Why this decision?")
            st.dataframe(
                [
                    {
                        "Strategy": item["strategy"],
                        "Weight": f"{item['weight']:.1f}%",
                        "Vote": item["vote"].title(),
                        "Confidence": f"{item['confidence']}%",
                        "Weighted signal": f"{item['weighted_signal']:+.2f}",
                    }
                    for item in contributions
                ],
                hide_index=True,
                width="stretch",
            )
            st.caption("Positive signals support a bullish vote; negative signals support a bearish vote.")
        if performance and performance_history:
            st.markdown("#### Historical performance")
            periods = performance["periods"]
            one_year = periods["1Y"]
            p1, p2, p3 = st.columns(3)
            p1.metric("1-year return", f"{one_year['company']:.1f}%")
            p2.metric("vs. S&P 500", f"{one_year['relative']:+.1f} pp")
            p3.metric("Maximum drawdown", f"{performance['max_drawdown']:.1f}%")
            st.line_chart(
                performance_history,
                x="date",
                y=["Company", "S&P 500"],
            )
            st.dataframe(
                [
                    {
                        "Period": period,
                        report.ticker: f"{values['company']:.2f}%",
                        "S&P 500": f"{values['benchmark']:.2f}%",
                        "Relative": f"{values['relative']:+.2f} pp",
                    }
                    for period, values in periods.items()
                ],
                hide_index=True,
                width="stretch",
            )
            st.caption(
                f"Annualized volatility: {performance['annualized_volatility']:.1f}% · "
                f"{performance['observations']} monthly observations · Growth indexed to 100"
            )
        elif not hasattr(report, "performance"):
            st.info("This report predates historical performance. Run the analysis again to add the comparison.")
        if technical:
            st.markdown("#### Golden Cross analyzer")
            if technical.get("status") == "insufficient_history":
                st.warning(technical["message"])
            else:
                short_period = technical.get("short_window", 50)
                long_period = technical.get("long_window", 200)
                t1, t2, t3 = st.columns(3)
                t1.metric("Technical trend", technical["label"])
                t2.metric(f"{short_period}-day average", f"${technical.get('short_average', technical['sma_50']):,.2f}")
                t3.metric(
                    f"{long_period}-day average",
                    f"${technical.get('long_average', technical['sma_200']):,.2f}",
                    delta=f"{short_period}-day spread {technical['spread_percent']:+.2f}%",
                )
                if technical_history:
                    st.line_chart(
                        technical_history,
                        x="date",
                        y=["Price", f"SMA {short_period}", f"SMA {long_period}"],
                    )
                latest_cross = technical.get("latest_cross")
                if latest_cross:
                    st.caption(f"Latest signal: {latest_cross['label']} on {latest_cross['date']} · {technical['message']}")
                else:
                    st.caption(f"No crossover was detected in the available period · {technical['message']}")
                st.caption("A Golden Cross is a technical trend signal, not a prediction or investment recommendation.")
        if environment:
            st.markdown("#### Market environment")
            with st.container(horizontal=True):
                st.metric("Environment score", f"{environment['score']:.1f}/100", border=True)
                st.metric("Market posture", environment["label"], border=True)
                st.metric("Event signal", f"{environment['event_score']:.1f}/100", border=True)
                st.metric("Macro signal", f"{environment['macro_score']:.1f}/100", border=True)
            st.info(environment["buying_context"])
            st.dataframe(
                [{
                    "Event": event["title"], "Direction": event["expected_direction"],
                    "Impact": event["impact"], "Confidence": event["confidence"],
                    "Duration": event["duration"],
                } for event in environment["events"]],
                column_config={"Confidence": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%d%%")},
                hide_index=True,
            )
        if catalyst_calendar:
            st.markdown("#### Earnings and catalyst readiness")
            next_event = catalyst_calendar.get("next_event") or {}
            with st.container(horizontal=True):
                st.metric("Readiness", catalyst_calendar["readiness"], border=True)
                st.metric("Timing risk", f"{catalyst_calendar['risk_score']}/100", border=True)
                st.metric("Next event", next_event.get("title", "None available"), border=True)
                st.metric("Days remaining", next_event.get("days_until", "—"), border=True)
            if catalyst_calendar["readiness"] in {"Elevated", "Event imminent"}:
                st.warning(catalyst_calendar["summary"])
            else:
                st.info(catalyst_calendar["summary"])
            st.dataframe(
                [{
                    "Date": event["date"], "Days": event["days_until"], "Event": event["title"],
                    "Category": event["category"], "Readiness": event["readiness"],
                    "Importance": event["importance"], "Confidence": event["confidence"],
                    "Why it matters": event["rationale"],
                } for event in catalyst_calendar["events"]],
                column_config={
                    "Date": st.column_config.DateColumn(format="MMM DD, YYYY"),
                    "Importance": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%d"),
                    "Confidence": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%d%%"),
                },
                hide_index=True,
            )
        if backtest:
            st.markdown("#### Golden Cross backtest")
            if backtest.get("status") == "insufficient_history":
                st.warning(backtest["message"])
            else:
                with st.container(horizontal=True):
                    st.metric("Strategy return", f"{backtest['total_return']:+.1f}%", border=True)
                    st.metric("Buy and hold", f"{backtest['buy_hold_return']:+.1f}%", border=True)
                    st.metric("S&P 500", f"{backtest['benchmark_return']:+.1f}%", border=True)
                    st.metric("Maximum drawdown", f"{backtest['max_drawdown']:.1f}%", border=True)
                st.line_chart(backtest["curve"], x="date", y=["Golden Cross strategy", "Buy and hold", "S&P 500"])
                st.caption(f"{backtest['execution']} · {backtest['transaction_cost_bps']:.0f} bps per transaction · {backtest['disclosure']}")
        if risk:
            st.markdown("#### Risk dashboard")
            with st.container(horizontal=True):
                st.metric("Overall risk", f"{risk['score']:.1f}/100", border=True)
                st.metric("Risk level", risk["severity"], border=True)
                st.metric("Factor coverage", f"{risk['coverage_percent']:.0f}%", border=True)
            st.caption("Higher scores indicate greater measured risk. Scores are analytical estimates, not forecasts.")
            st.dataframe(
                risk["components"],
                column_config={
                    "factor": st.column_config.TextColumn("Risk factor", pinned=True),
                    "score": st.column_config.ProgressColumn("Risk score", min_value=0, max_value=100, format="%.1f"),
                    "weight": st.column_config.NumberColumn("Weight", format="%.0f%%"),
                    "severity": st.column_config.TextColumn("Level"),
                    "explanation": st.column_config.TextColumn("Why"),
                },
                hide_index=True,
            )
            if risk["flags"]:
                st.markdown("**Priority risk flags**")
                for flag in risk["flags"]:
                    st.warning(f"{flag['severity']} · {flag['factor']}: {flag['message']}")
        if macro:
            st.markdown("#### Macro environment")
            indicators = macro["indicators"]
            columns = st.columns(len(indicators))
            for column, indicator in zip(columns, indicators.values()):
                column.metric(indicator["label"], f"{indicator['value']:.2f} {indicator['unit']}")
                column.caption(f"As of {indicator['observed_at']} · {indicator['series_id']}")
            stale = [indicator["label"] for indicator in indicators.values() if indicator["stale"]]
            if stale:
                st.warning("Potentially stale macro series: " + ", ".join(stale))
            st.caption(f"Source: {macro['provider']} · Retrieved {macro['retrieved_at'][:19].replace('T', ' ')} UTC")
        for title, items in [
            ("Bull case", report.bull_case),
            ("Bear case", report.bear_case),
            ("Risks", report.risks),
            ("Catalysts", report.catalysts),
        ]:
            st.markdown(f"#### {title}")
            for item in items:
                st.write(f"- {item}")
        st.markdown("#### Strategy committee")
        for item in report.assessments:
            with st.expander(f"{item.strategy}: {item.vote.title()} ({item.confidence}% confidence)"):
                st.write(item.thesis)
                for evidence in item.evidence:
                    st.caption(f"{evidence.label}: {evidence.value} · {evidence.source} · {evidence.observed_at}")

with backtest_tab:
    st.subheader("Historical signal backtesting")
    configured_short = active_configuration["technical"]["short_window"]
    configured_long = active_configuration["technical"]["long_window"]
    st.caption(f"Tests the SMA {configured_short}/{configured_long} crossover using only information available at each historical date.")
    backtest_ticker = st.text_input(
        "Backtest ticker", value=(repository.watchlist() or ["AAPL"])[0], key="backtest-ticker"
    ).upper().strip()
    transaction_cost_bps = st.number_input(
        "Transaction cost per entry or exit (basis points)", min_value=0.0, max_value=500.0,
        value=float(active_configuration["backtest"]["transaction_cost_bps"]), step=5.0, key="backtest-cost",
    )
    if st.button("Run backtest", type="primary", disabled=not backtest_ticker, key="run-backtest"):
        try:
            with st.spinner("Running point-in-time crossover simulation…"):
                st.session_state["standalone_backtest"] = {
                    "ticker": backtest_ticker,
                    "result": backtest_golden_cross(
                        provider.daily_history(backtest_ticker), provider.daily_history("SPY"), transaction_cost_bps,
                        configured_short, configured_long,
                    ),
                }
        except (ProviderError, ValueError) as exc:
            st.error(f"Backtest failed: {exc}")
    standalone = st.session_state.get("standalone_backtest")
    if standalone:
        result = standalone["result"]
        st.markdown(f"#### {standalone['ticker']} results")
        if result.get("status") == "insufficient_history":
            st.warning(result["message"])
        else:
            with st.container(horizontal=True):
                st.metric("Strategy return", f"{result['total_return']:+.2f}%", border=True)
                st.metric("Annualized return", f"{result['annualized_return']:+.2f}%", border=True)
                st.metric("Buy and hold", f"{result['buy_hold_return']:+.2f}%", border=True)
                st.metric("S&P 500", f"{result['benchmark_return']:+.2f}%", border=True)
            with st.container(horizontal=True):
                st.metric("Maximum drawdown", f"{result['max_drawdown']:.2f}%", border=True)
                st.metric("Volatility", f"{result['annualized_volatility']:.2f}%", border=True)
                st.metric("Sharpe ratio", f"{result['sharpe_ratio']:.2f}", border=True)
                st.metric("Completed trades", result["completed_trades"], border=True)
                st.metric("Win rate", f"{result['win_rate']:.1f}%", border=True)
            st.line_chart(result["curve"], x="date", y=["Golden Cross strategy", "Buy and hold", "S&P 500"])
            if result["trades"]:
                st.markdown("#### Completed trades")
                st.dataframe(result["trades"], hide_index=True)
            else:
                st.info("No completed entry/exit cycle occurred in the available period.")
            st.caption(
                f"{result['strategy']} · {result['execution']} · {result['transaction_cost_bps']:.0f} bps per transaction · "
                f"{result['start_date']} through {result['end_date']}"
            )
            st.warning(result["disclosure"])

with compare_tab:
    st.subheader("Compare companies")
    st.caption("Comparisons use the committee weights configured in the Research tab.")
    available_tickers = repository.watchlist()
    if len(available_tickers) < 2:
        st.info("Add at least two companies to your watchlist before running a comparison.")
        selected_tickers = []
    else:
        selected_tickers = st.multiselect(
            "Companies",
            available_tickers,
            default=available_tickers[:2],
        )
        if len(selected_tickers) > 4:
            st.error("Select no more than four companies.")
    comparison_ready = 2 <= len(selected_tickers) <= 4 and bool(normalized_preview)
    if st.button("Run comparison", type="primary", disabled=not comparison_ready):
        try:
            with st.spinner("Building comparable research snapshots…"):
                st.session_state["comparison"] = ComparisonService(analysis, repository).compare(
                    selected_tickers, strategy_weights
                )
        except (ProviderError, ValueError) as exc:
            st.error(str(exc))
        except Exception as exc:
            st.error(f"Comparison failed: {exc}")

    comparison = st.session_state.get("comparison")
    if comparison:
        st.markdown(f"#### Comparison #{comparison['comparison_id']}")
        if render_comparison_pdf:
            st.download_button(
                "Download comparison PDF",
                data=render_comparison_pdf(comparison),
                file_name=f"atlas-{'-vs-'.join(ticker.lower() for ticker in comparison['tickers'])}.pdf",
                mime="application/pdf",
                key=f"download-comparison-{comparison['comparison_id']}",
            )
        for warning in comparison["warnings"]:
            st.warning(warning)
        st.dataframe(comparison["summary"], hide_index=True, width="stretch")
        st.markdown("#### Normalized performance")
        st.line_chart(
            comparison["performance_history"],
            x="date",
            y=comparison["tickers"],
        )
        st.caption("Each company is indexed to 100 at the beginning of the comparison period.")
        st.markdown("#### Strategy-by-strategy")
        st.dataframe(comparison["strategy_table"], hide_index=True, width="stretch")
        st.caption("Committee weights: " + " · ".join(
            f"{strategy} {weight:.1f}%" for strategy, weight in comparison["strategy_weights"].items()
        ))

    saved_comparisons = repository.comparison_history()
    if saved_comparisons:
        st.markdown("#### Saved comparisons")
        for saved_row in saved_comparisons:
            saved = repository.get_comparison(saved_row["id"])
            if not saved:
                continue
            label = f"#{saved_row['id']} · {' vs '.join(saved['tickers'])} · {saved_row['created_at']}"
            with st.expander(label):
                st.dataframe(saved["summary"], hide_index=True, width="stretch")
                if render_comparison_pdf:
                    st.download_button(
                        "Download saved comparison PDF",
                        data=render_comparison_pdf(saved),
                        file_name=f"atlas-{'-vs-'.join(ticker.lower() for ticker in saved['tickers'])}.pdf",
                        mime="application/pdf",
                        key=f"download-saved-comparison-{saved_row['id']}",
                    )

with changes_tab:
    st.subheader("Research change tracker")
    st.caption("Compare each company's newest saved report with the report immediately before it.")
    tracked_tickers = repository.report_tickers()
    change_overview = []
    for tracked_ticker in tracked_tickers:
        tracked_reports = repository.recent_reports(tracked_ticker, 2)
        if len(tracked_reports) < 2:
            continue
        tracked_change = compare_reports(tracked_reports[0], tracked_reports[1])
        change_overview.append({
            "Ticker": tracked_ticker,
            "Thesis status": tracked_change["thesis_status"],
            "Change score": tracked_change["thesis_score"],
            "Material changes": len(tracked_change["material_changes"]),
            "Current report": tracked_change["current_created_at"],
            "Previous report": tracked_change["previous_created_at"],
        })
    if change_overview:
        status_counts = {status: sum(row["Thesis status"] == status for row in change_overview) for status in (
            "Strengthening", "Unchanged", "Weakening", "Invalidated"
        )}
        with st.container(horizontal=True):
            st.metric("Companies tracked", len(change_overview), border=True)
            st.metric("Strengthening", status_counts["Strengthening"], border=True)
            st.metric("Weakening", status_counts["Weakening"], border=True)
            st.metric("Invalidated", status_counts["Invalidated"], border=True)
        st.dataframe(
            change_overview,
            column_config={
                "Ticker": st.column_config.TextColumn(pinned=True),
                "Change score": st.column_config.NumberColumn(format="%+.1f"),
                "Current report": st.column_config.DatetimeColumn(format="MMM DD, YYYY, h:mm a"),
                "Previous report": st.column_config.DatetimeColumn(format="MMM DD, YYYY, h:mm a"),
            },
            hide_index=True,
        )
    else:
        st.info("Create at least two reports for a company to begin tracking research changes.")

    if tracked_tickers:
        change_ticker = st.selectbox("Company to inspect", tracked_tickers, key="change-tracker-ticker")
        selected_reports = repository.recent_reports(change_ticker, 2)
        if len(selected_reports) < 2:
            st.info(f"{change_ticker} has only one saved report. Run its research analysis again to create a comparison.")
        else:
            change = compare_reports(selected_reports[0], selected_reports[1])
            st.markdown(f"#### {change['company']} ({change['ticker']})")
            st.info(change["summary"])
            metric_map = {item["Metric"]: item for item in change["metrics"]}
            with st.container(horizontal=True):
                committee_change = metric_map["Committee score"]
                st.metric(
                    "Committee score", f"{committee_change['Current']:.1f}/100",
                    delta=f"{committee_change['Change']:+.1f}", border=True,
                )
                risk_change = metric_map["Risk score"]
                st.metric(
                    "Risk score", f"{risk_change['Current']:.1f}/100",
                    delta=f"{risk_change['Change']:+.1f}", delta_color="inverse", border=True,
                )
                readiness_change = metric_map["Entry readiness"]
                st.metric(
                    "Entry readiness", f"{readiness_change['Current']:.1f}/100",
                    delta=f"{readiness_change['Change']:+.1f}", border=True,
                )
                environment_change = metric_map["Market environment"]
                st.metric(
                    "Market environment", f"{environment_change['Current']:.1f}/100",
                    delta=f"{environment_change['Change']:+.1f}", border=True,
                )
                st.metric("Thesis status", change["thesis_status"], delta=f"{change['thesis_score']:+.1f}", border=True)

            st.markdown("#### What changed?")
            if change["material_changes"]:
                st.dataframe(change["material_changes"], hide_index=True)
            else:
                st.success("No material report-to-report movement was detected.")
            st.markdown("#### Measured evidence")
            st.dataframe(
                change["metrics"],
                column_config={"Change": st.column_config.NumberColumn(format="%+.2f")},
                hide_index=True,
            )
            if change["state_changes"]:
                st.markdown("#### State changes")
                st.dataframe(change["state_changes"], hide_index=True)
            evidence_columns = st.columns(2)
            with evidence_columns[0]:
                st.markdown("#### Added evidence")
                for item in change["added_risks"]:
                    st.warning(f"Risk: {item}")
                for item in change["added_catalysts"]:
                    st.success(f"Catalyst: {item}")
                if not change["added_risks"] and not change["added_catalysts"]:
                    st.caption("No new risks or catalysts.")
            with evidence_columns[1]:
                st.markdown("#### Removed evidence")
                for item in change["removed_risks"]:
                    st.success(f"Risk removed: {item}")
                for item in change["removed_catalysts"]:
                    st.warning(f"Catalyst removed: {item}")
                if not change["removed_risks"] and not change["removed_catalysts"]:
                    st.caption("No risks or catalysts were removed.")
            with st.expander("Why Atlas assigned this thesis status"):
                for reason in change["reasons"]:
                    st.write(reason)
                st.caption("Strengthening >= +4; weakening <= -4. Major vote, risk, readiness, or technical reversals can invalidate a thesis.")
            if render_change_pdf:
                st.download_button(
                    "Download research change PDF", data=render_change_pdf(change),
                    file_name=f"atlas-{change['ticker'].lower()}-research-change.pdf",
                    mime="application/pdf", key=f"download-change-{change['current_report_id']}-{change['previous_report_id']}",
                )
            st.caption(change["disclosure"])

with alerts_tab:
    scheduler = ScheduledResearchService(
        analysis, repository, provider, macro_provider, event_provider, calendar_provider,
    )

    @st.fragment(run_every="60s")
    def scheduled_research_monitor():
        scheduler_status = scheduler.status()
        if scheduler_status["due"]:
            with st.status("Scheduled research refresh is runningâ€¦", expanded=False) as run_status:
                scheduled_result = scheduler.run("Scheduled")
                if scheduled_result["status"] == "Complete":
                    run_status.update(label="Scheduled research refresh completed", state="complete")
                else:
                    run_status.update(label=f"Scheduled refresh {scheduled_result['status'].lower()}", state="error")
        refreshed_status = scheduler.status()
        if refreshed_status["configuration"]["enabled"]:
            next_run = refreshed_status["next_run"] or "Pending"
            st.caption(f"Automatic monitor active. Next due check: {next_run[:19].replace('T', ' ')} UTC.")
        else:
            st.caption("Automatic research refresh is disabled.")

    st.subheader("Scheduled research")
    st.caption("Schedules run while Atlas is open. Every completed refresh automatically updates reports and can scan alerts.")
    scheduled_research_monitor()
    schedule = scheduler.configuration()
    schedule_intervals = {
        "Hourly": 1, "Every 4 hours": 4, "Every 12 hours": 12,
        "Daily": 24, "Every 3 days": 72, "Weekly": 168,
    }
    interval_label = next((label for label, hours in schedule_intervals.items() if hours == schedule["interval_hours"]), "Daily")
    with st.form("scheduled-research-settings"):
        schedule_enabled = st.toggle("Enable automatic research refresh", value=schedule["enabled"])
        schedule_controls = st.container(horizontal=True)
        with schedule_controls:
            schedule_interval_label = st.selectbox(
                "Refresh frequency", list(schedule_intervals), index=list(schedule_intervals).index(interval_label),
            )
            schedule_scope = st.selectbox("Research scope", SCOPES, index=SCOPES.index(schedule["scope"]))
            schedule_preset = st.selectbox("Analysis preset", list(PRESETS), index=list(PRESETS).index(schedule["preset"]))
            schedule_retries = st.number_input("Retry limit", 0, 3, int(schedule["retry_limit"]), 1)
        schedule_scan_alerts = st.toggle("Scan alert rules after each refresh", value=schedule["scan_alerts"])
        save_schedule = st.form_submit_button("Save schedule", type="primary")
    if save_schedule:
        try:
            scheduler.save_configuration({
                "enabled": schedule_enabled,
                "interval_hours": schedule_intervals[schedule_interval_label],
                "scope": schedule_scope,
                "preset": schedule_preset,
                "retry_limit": schedule_retries,
                "scan_alerts": schedule_scan_alerts,
            })
            st.success("Scheduled research settings saved.")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
    scheduler_actions = st.container(horizontal=True)
    with scheduler_actions:
        if st.button("Run scheduled workflow now", key="run-scheduled-workflow-now"):
            with st.status("Refreshing scheduled researchâ€¦", expanded=True) as manual_status:
                manual_result = scheduler.run("Manual")
                if manual_result["status"] == "Complete":
                    manual_status.update(label="Research refresh and alert scan completed", state="complete")
                else:
                    manual_status.write("\n".join(manual_result["errors"]))
                    manual_status.update(label=f"Research refresh {manual_result['status'].lower()}", state="error")
            st.rerun()
    schedule_status = scheduler.status()
    last_schedule_run = schedule_status["last_run"]
    with st.container(horizontal=True):
        st.metric("Schedule", "Enabled" if schedule["enabled"] else "Disabled", border=True)
        st.metric("Scope", schedule["scope"], border=True)
        st.metric("Frequency", f"Every {schedule['interval_hours']}h", border=True)
        st.metric("Last result", last_schedule_run["status"] if last_schedule_run else "Never run", border=True)
        st.metric("Last analyzed", last_schedule_run["analyzed"] if last_schedule_run else 0, border=True)
        st.metric("Alerts created", last_schedule_run["alerts_created"] if last_schedule_run else 0, border=True)
    schedule_runs = repository.scheduler_runs()
    if schedule_runs:
        st.markdown("#### Scheduled workflow history")
        st.dataframe(
            [{
                "Run": row["id"], "Started": row["started_at"], "Completed": row["completed_at"],
                "Status": row["status"], "Scope": row["scope"], "Requested": row["requested"],
                "Analyzed": row["analyzed"], "Alerts": row["alerts_created"],
                "Errors": "; ".join(row["errors"]),
            } for row in schedule_runs],
            column_config={
                "Started": st.column_config.DatetimeColumn(format="MMM DD, YYYY, h:mm a"),
                "Completed": st.column_config.DatetimeColumn(format="MMM DD, YYYY, h:mm a"),
            },
            hide_index=True,
        )
    st.divider()

    alert_service = AlertService(repository)
    alert_watchlist = repository.watchlist()
    unread_count = repository.unread_alert_count()
    st.subheader("Alert center")
    with st.container(horizontal=True):
        st.metric("Unread alerts", unread_count, border=True)
        st.metric("Monitored companies", len(alert_watchlist), border=True)
        st.metric("Saved alerts", len(repository.alerts()), border=True)
    if not alert_watchlist:
        st.info("Add companies to the watchlist before configuring or scanning alerts.")
    else:
        actions = st.container(horizontal=True)
        with actions:
            if st.button("Run alert scan", type="primary", key="run-alert-scan"):
                result = alert_service.scan(alert_watchlist)
                if result["missing"]:
                    st.warning("No saved report for: " + ", ".join(result["missing"]))
                st.success(f"Evaluated {result['evaluated']} companies and created {result['created']} new alerts.")
                st.rerun()
            if provider.name.startswith("Demo") and st.button("Create demo alert", key="create-demo-alert"):
                alert_service.simulate_demo_alert(alert_watchlist[0])
                st.rerun()
            if unread_count and st.button("Mark all read", key="mark-alerts-read"):
                repository.mark_alerts_read()
                st.rerun()

        st.markdown("#### Alert rules")
        alert_ticker = st.selectbox("Company", alert_watchlist, key="alert-rule-ticker")
        current_rule = alert_service.rule(alert_ticker)
        with st.form(f"alert-rule-form-{alert_ticker}"):
            enabled_alerts = st.multiselect(
                "Conditions to monitor", list(ALERT_TYPES), default=current_rule["enabled"],
                format_func=lambda name: ALERT_TYPES[name],
            )
            rule_row_one = st.container(horizontal=True)
            with rule_row_one:
                risk_threshold = st.number_input("Risk threshold", 0.0, 100.0, float(current_rule["risk_threshold"]), 5.0)
                confidence_change = st.number_input("Confidence change", 1.0, 100.0, float(current_rule["confidence_change"]), 5.0)
                catalyst_days = st.number_input("Catalyst warning days", 1, 90, int(current_rule["catalyst_days"]), 1)
            rule_row_two = st.container(horizontal=True)
            with rule_row_two:
                rank_change = st.number_input("Rank movement", 1, 20, int(current_rule["rank_change"]), 1)
                backtest_floor = st.number_input("Backtest return floor (%)", -100.0, 500.0, float(current_rule["backtest_floor"]), 5.0)
                stale_days = st.number_input("Report stale after days", 1, 90, int(current_rule["stale_days"]), 1)
            save_alert_rule = st.form_submit_button("Save alert rules", type="primary")
        if save_alert_rule:
            alert_service.save_rule(alert_ticker, {
                "enabled": enabled_alerts,
                "risk_threshold": risk_threshold,
                "confidence_change": confidence_change,
                "catalyst_days": catalyst_days,
                "rank_change": rank_change,
                "backtest_floor": backtest_floor,
                "stale_days": stale_days,
            })
            st.success(f"Saved alert rules for {alert_ticker}.")

    alert_rows = repository.alerts()
    st.markdown("#### Alert history")
    if not alert_rows:
        st.info("No alerts have been created yet. Run a scan after generating watchlist reports.")
    else:
        st.dataframe(
            [{
                "Status": "Read" if alert["is_read"] else "Unread",
                "Created": alert["created_at"], "Ticker": alert["ticker"],
                "Severity": alert["severity"], "Type": alert["alert_type"].replace("_", " ").title(),
                "Alert": alert["title"], "Details": alert["message"],
            } for alert in alert_rows],
            column_config={
                "Created": st.column_config.DatetimeColumn(format="MMM DD, YYYY, h:mm a"),
                "Ticker": st.column_config.TextColumn(pinned=True),
            },
            hide_index=True,
        )
    st.caption("Alerts are generated from saved Atlas reports. Re-running a scan does not duplicate an unchanged condition.")

with readiness_tab:
    st.subheader("Live data readiness")
    st.caption("Run connection and coverage checks before changing providers. API keys are detected but never displayed or stored in reports.")
    environment_status = environment_readiness()
    with st.container(horizontal=True):
        st.metric("Current market mode", environment_status["market_mode"].replace("_", " ").title(), border=True)
        st.metric("Current macro mode", environment_status["macro_mode"].replace("_", " ").title(), border=True)
        st.metric("Alpha Vantage key", "Detected" if environment_status["alpha_vantage_key"] else "Missing", border=True)
        st.metric("FRED key", "Detected" if environment_status["fred_key"] else "Missing", border=True)
        st.metric("Provider cache entries", provider_cache.count(), border=True)

    readiness_ticker = st.text_input("Ticker for readiness tests", value="AAPL", key="readiness-test-ticker").strip().upper()
    readiness_actions = st.container(horizontal=True)
    with readiness_actions:
        run_demo_readiness = st.button("Validate demo providers", key="validate-demo-providers")
        run_live_market = st.button(
            "Test Alpha Vantage", key="test-alpha-vantage-readiness",
            disabled=not environment_status["alpha_vantage_key"], type="primary",
        )
        run_live_macro = st.button(
            "Test FRED", key="test-fred-readiness", disabled=not environment_status["fred_key"],
        )
    st.caption("A full Alpha Vantage test can use up to six provider requests when no cached responses exist.")

    if run_demo_readiness:
        with st.status("Validating demo providersâ€¦", expanded=True) as demo_status:
            demo_market_result = test_market_provider(
                provider if provider.name.startswith("Demo") else CachedMarketDataProvider(DemoProvider(), provider_cache),
                readiness_ticker, active_configuration["technical"]["long_window"],
            )
            demo_macro_result = test_macro_provider(
                macro_provider if macro_provider.name.startswith("Demo") else CachedEconomicDataProvider(DemoEconomicProvider(), provider_cache)
            )
            repository.save_configuration("demo_market_readiness", demo_market_result)
            repository.save_configuration("demo_macro_readiness", demo_macro_result)
            demo_status.update(label="Demo provider validation complete", state="complete")
        st.rerun()
    if run_live_market:
        try:
            with st.status("Testing Alpha Vantage endpointsâ€¦", expanded=True) as market_status:
                live_market_provider = CachedMarketDataProvider(AlphaVantageProvider(), provider_cache)
                live_market_result = test_market_provider(
                    live_market_provider, readiness_ticker, active_configuration["technical"]["long_window"],
                )
                repository.save_configuration("live_market_readiness", live_market_result)
                final_state = "complete" if live_market_result["status"] == "Ready" else "error"
                market_status.update(label=f"Alpha Vantage test: {live_market_result['status']}", state=final_state)
            st.rerun()
        except ProviderError as exc:
            st.error(f"Alpha Vantage readiness test could not start: {exc}")
    if run_live_macro:
        try:
            with st.status("Testing FRED economic seriesâ€¦", expanded=True) as macro_status:
                live_macro_provider = CachedEconomicDataProvider(FredProvider(), provider_cache)
                live_macro_result = test_macro_provider(live_macro_provider)
                repository.save_configuration("live_macro_readiness", live_macro_result)
                final_state = "complete" if live_macro_result["status"] == "Ready" else "error"
                macro_status.update(label=f"FRED test: {live_macro_result['status']}", state=final_state)
            st.rerun()
        except ProviderError as exc:
            st.error(f"FRED readiness test could not start: {exc}")

    live_market_result = repository.configuration("live_market_readiness")
    live_macro_result = repository.configuration("live_macro_readiness")
    readiness = readiness_summary(environment_status, live_market_result, live_macro_result)
    st.markdown("#### Live-mode decision")
    if readiness["overall"] == "Ready for live mode":
        st.success(readiness["overall"])
    else:
        st.warning(readiness["overall"])
    for blocker in readiness["blockers"]:
        st.write(f"- {blocker}")

    if live_market_result:
        st.markdown(f"#### Alpha Vantage: {live_market_result['status']}")
        with st.container(horizontal=True):
            st.metric("Ticker tested", live_market_result["ticker"], border=True)
            st.metric("Field coverage", f"{live_market_result['snapshot_coverage']:.1f}%", border=True)
            st.metric("Daily observations", live_market_result["daily_observations"], border=True)
            st.metric("Required observations", live_market_result["required_daily_observations"], border=True)
        st.dataframe(live_market_result["checks"], hide_index=True)
        if live_market_result.get("provider_status"):
            status = live_market_result["provider_status"]
            st.caption(
                f"Cache entries {status.get('cache_entries', 0)} | Cache hits {status.get('cache_hits', 0)} | "
                f"Live requests {status.get('live_requests', 0)} | Retries {status.get('retries', 0)} | "
                f"Stale fallbacks {status.get('stale_fallbacks', 0)}"
            )
    else:
        st.info("Alpha Vantage has not been tested yet.")

    if live_macro_result:
        st.markdown(f"#### FRED: {live_macro_result['status']}")
        with st.container(horizontal=True):
            st.metric("Indicator coverage", f"{live_macro_result['indicator_coverage']:.1f}%", border=True)
            st.metric("Stale indicators", live_macro_result["stale_indicators"], border=True)
            st.metric("Tested", live_macro_result["tested_at"][:19].replace("T", " ") + " UTC", border=True)
        st.dataframe(live_macro_result["checks"], hide_index=True)
    else:
        st.info("FRED has not been tested yet.")

    demo_market_result = repository.configuration("demo_market_readiness")
    demo_macro_result = repository.configuration("demo_macro_readiness")
    if demo_market_result or demo_macro_result:
        with st.expander("Demo-provider validation"):
            if demo_market_result:
                st.write(f"Market demo: {demo_market_result['status']} ({demo_market_result['ticker']})")
                st.dataframe(demo_market_result["checks"], hide_index=True)
            if demo_macro_result:
                st.write(f"Macro demo: {demo_macro_result['status']}")
                st.dataframe(demo_macro_result["checks"], hide_index=True)

    with st.expander("How to switch providers safely"):
        st.code(
            "ATLAS_DATA_PROVIDER=alpha_vantage\n"
            "ALPHA_VANTAGE_API_KEY=your_key_here\n"
            "ATLAS_MACRO_PROVIDER=fred\n"
            "FRED_API_KEY=your_key_here",
            language="text",
        )
        st.write("Keep these values in your local .env file, never in source code. Restart Atlas after changing provider modes.")
        st.write("If the daily-history check is blocked at 100 observations, keep demo market mode or use an Alpha Vantage plan that supports full daily history before relying on the 200-day analyzer.")

with settings_tab:
    st.subheader("Settings and calibration")
    st.caption("Settings are versioned and embedded in each new report. API credentials remain environment-controlled.")
    with st.container(horizontal=True):
        st.metric("Configuration version", active_configuration["version"], border=True)
        st.metric("Active profile", active_configuration["profile"], border=True)
        st.metric("Market provider", provider.name, border=True)
        st.metric("Macro provider", macro_provider.name, border=True)

    profile_choice = st.segmented_control(
        "Apply a calibration profile", ["Balanced", "Growth", "Value", "Defensive"],
        default=active_configuration["profile"] if active_configuration["profile"] in {"Balanced", "Growth", "Value", "Defensive"} else "Balanced",
        key="settings-profile-choice",
    )
    profile_actions = st.container(horizontal=True)
    with profile_actions:
        if st.button("Apply profile", type="primary", key="apply-settings-profile"):
            save_configuration(repository, settings_profile(profile_choice))
            st.success(f"Applied the {profile_choice} profile.")
            st.rerun()
        if st.button("Restore defaults", key="restore-settings-defaults"):
            save_configuration(repository, DEFAULT_CONFIG)
            st.success("Restored balanced defaults.")
            st.rerun()
        st.download_button(
            "Export configuration", data=json.dumps(active_configuration, indent=2),
            file_name="atlas-configuration.json", mime="application/json", key="export-settings",
        )

    with st.form("calibration-settings-form"):
        st.markdown("#### General assumptions")
        general = st.container(horizontal=True)
        with general:
            settings_committee = st.selectbox(
                "Default committee preset", list(PRESETS),
                index=list(PRESETS).index(active_configuration["committee_preset"]),
            )
            short_window = st.number_input("Short moving average", 5, 250, int(active_configuration["technical"]["short_window"]), 5)
            long_window = st.number_input("Long moving average", 20, 500, int(active_configuration["technical"]["long_window"]), 5)
            settings_cost = st.number_input("Backtest cost (bps)", 0.0, 500.0, float(active_configuration["backtest"]["transaction_cost_bps"]), 5.0)
        timing = st.container(horizontal=True)
        with timing:
            freshness_days = st.number_input("Report freshness days", 1, 365, int(active_configuration["freshness_days"]), 1)
            catalyst_warning_days = st.number_input("Catalyst warning days", 1, 90, int(active_configuration["catalyst_warning_days"]), 1)

        st.markdown("#### Risk-factor weights")
        risk_weight_values = {}
        with st.container(horizontal=True):
            for factor, value in active_configuration["risk_weights"].items():
                risk_weight_values[factor] = st.number_input(
                    factor, 0.0, 100.0, float(value), 1.0, key=f"settings-risk-{factor}"
                )
        st.caption(f"Current total: {sum(risk_weight_values.values()):.1f}%")

        st.markdown("#### Entry-readiness weights")
        readiness_weight_values = {}
        with st.container(horizontal=True):
            for factor, value in active_configuration["readiness_weights"].items():
                readiness_weight_values[factor] = st.number_input(
                    factor, 0.0, 100.0, float(value), 1.0, key=f"settings-readiness-{factor}"
                )
        st.caption(f"Current total: {sum(readiness_weight_values.values()):.1f}%")

        st.markdown("#### Watchlist-ranking weights")
        ranking_weight_values = {}
        with st.container(horizontal=True):
            for factor, value in active_configuration["ranking_weights"].items():
                ranking_weight_values[factor] = st.number_input(
                    factor.replace("_", " ").title(), 0.0, 100.0, float(value), 1.0,
                    key=f"settings-ranking-{factor}",
                )
        st.caption(f"Current total: {sum(ranking_weight_values.values()):.1f}%")

        st.markdown("#### Default alert thresholds")
        alert_defaults = active_configuration["alert_defaults"]
        alert_settings = st.container(horizontal=True)
        with alert_settings:
            default_risk_threshold = st.number_input("Default risk threshold", 0.0, 100.0, float(alert_defaults["risk_threshold"]), 5.0)
            default_confidence_change = st.number_input("Default confidence change", 1.0, 100.0, float(alert_defaults["confidence_change"]), 5.0)
            default_rank_change = st.number_input("Default rank movement", 1, 20, int(alert_defaults["rank_change"]), 1)
            default_backtest_floor = st.number_input("Default backtest floor", -100.0, 500.0, float(alert_defaults["backtest_floor"]), 5.0)
            default_stale_days = st.number_input("Default stale days", 1, 365, int(alert_defaults["stale_days"]), 1)
        save_settings = st.form_submit_button("Validate and save configuration", type="primary")
    if save_settings:
        candidate = {
            "version": active_configuration["version"], "profile": "Custom",
            "committee_preset": settings_committee,
            "technical": {"short_window": short_window, "long_window": long_window},
            "backtest": {"transaction_cost_bps": settings_cost},
            "freshness_days": freshness_days, "catalyst_warning_days": catalyst_warning_days,
            "risk_weights": risk_weight_values, "readiness_weights": readiness_weight_values,
            "ranking_weights": ranking_weight_values,
            "alert_defaults": {
                "risk_threshold": default_risk_threshold, "confidence_change": default_confidence_change,
                "rank_change": default_rank_change, "backtest_floor": default_backtest_floor,
                "stale_days": default_stale_days,
            },
        }
        try:
            save_configuration(repository, candidate)
            st.success("Configuration validated and saved. New reports will use these assumptions.")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

    st.markdown("#### Import configuration")
    imported_file = st.file_uploader("Choose an Atlas configuration JSON file", type=["json"], key="import-settings-file")
    if imported_file and st.button("Validate and import", key="import-settings"):
        try:
            imported = json.loads(imported_file.getvalue().decode("utf-8"))
            validate_configuration(imported)
            save_configuration(repository, imported)
            st.success("Configuration imported successfully.")
            st.rerun()
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            st.error(f"Configuration import failed: {exc}")

    with st.expander("Methodology and safeguards"):
        st.write("All scoring weights must total 100%. Moving-average periods must satisfy 5 ≤ short < long ≤ 500.")
        st.write("Provider selection is controlled through the environment file so credentials are not exposed or rewritten by the app.")
        st.write("Every newly generated report stores a complete configuration snapshot for auditability.")

with history_tab:
    rows = repository.history()
    if not rows:
        st.info("No saved reports yet.")
    for row in rows:
        with st.expander(f"#{row['id']} · {row['ticker']} · {row['created_at']}"):
            saved = repository.get(row["id"])
            if saved:
                st.write(saved.executive_summary)
                st.caption(f"Provider: {saved.provider} · Data as of: {saved.data_as_of}")
                if render_report_pdf:
                    st.download_button(
                        "Download saved report PDF",
                        data=render_report_pdf(saved),
                        file_name=f"atlas-{saved.ticker.lower()}-report.pdf",
                        mime="application/pdf",
                        key=f"download-saved-report-{row['id']}",
                    )

with st.expander("Data status"):
    status_rows = []
    for status in (provider.status(), macro_provider.status()):
        age = status["last_age_seconds"]
        status_rows.append({
            "Provider": status["provider"],
            "Last operation": status["last_operation"],
            "Last source": status["last_source"],
            "Cache age": "-" if age is None else f"{age:.0f}s",
            "Cache entries": status["cache_entries"],
            "Cache hits": status["cache_hits"],
            "Live requests": status["live_requests"],
            "Retries": status["retries"],
            "Stale fallbacks": status["stale_fallbacks"],
        })
    st.dataframe(status_rows, hide_index=True, width="stretch")
    if st.button("Refresh provider cache"):
        provider_cache.clear()
        provider.reset_status()
        macro_provider.reset_status()
        st.success("Provider cache cleared. The next analysis will request fresh data.")
        st.rerun()
