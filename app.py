from __future__ import annotations

import importlib
import inspect
import json
import os
import re
from datetime import date, time, timedelta

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

import core.providers.demo_provider as demo_provider_module
import core.providers.market_provider as market_provider_module
import core.providers.cached_provider as cached_provider_module
import core.providers.hybrid_provider as hybrid_provider_module
import core.providers.tiingo_provider as tiingo_provider_module
from core.providers.demo_provider import DemoProvider
from core.providers.market_provider import AlphaVantageProvider, ProviderError
from core.providers.economic_provider import DemoEconomicProvider, FredProvider
from core.providers.event_provider import DemoEconomicEventProvider
from core.providers.calendar_provider import (
    AlphaVantageEarningsCalendarProvider, CombinedCatalystCalendarProvider,
    DemoCatalystCalendarProvider, FredReleaseCalendarProvider,
)
from core.providers.cached_provider import CachedEconomicDataProvider, CachedMarketDataProvider
from core.providers.fallback_provider import FallbackMarketDataProvider
from core.providers.sec_provider import SecCompanyFactsProvider
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
import core.services.opportunity_discovery_service as opportunity_discovery_service_module
import core.services.discovery_monitor_service as discovery_monitor_service_module
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
from core.services.thesis_service import (
    CONFIDENCE_LEVELS, STANCES, evaluate_thesis, validate_thesis,
)
from core.services.stress_test_service import SCENARIOS, analyze_stress_scenario
from core.services.decision_center_service import PRIORITIES, build_beginner_guidance, build_decision_center
from core.services.valuation_service import build_valuation, suggested_assumptions
from core.services.financial_health_service import analyze_financial_health
from core.services.sec_monitor_service import SecMonitorService
from core.services.guided_workflow_service import build_company_workflow, build_setup_status
from core.services.position_sizing_service import SIZING_PRESETS, build_position_plan
from core.services.decision_packet_service import build_decision_packet
from core.services.evidence_trust_service import assess_evidence_trust, build_trust_alert
from core.services.portfolio_action_service import build_portfolio_action_plan
from core.services.decision_accuracy_service import build_label_snapshot, evaluate_snapshot, summarize_accuracy
from core.services.discovery_scan_service import DiscoveryScanService
from core.services.discovery_scheduler_service import ScheduledDiscoveryService
from core.services.provider_health_service import build_provider_health
from core.services.settings_service import (
    DEFAULT_CONFIG, load_configuration, profile as settings_profile,
    save_configuration, validate_configuration,
)

try:
    import core.services.pdf_service as pdf_service_module
    if (not hasattr(pdf_service_module, "render_watchlist_pdf") or
            not hasattr(pdf_service_module, "render_portfolio_pdf") or
            not hasattr(pdf_service_module, "render_change_pdf") or
            not hasattr(pdf_service_module, "render_decision_packet_pdf") or
            not hasattr(pdf_service_module, "render_portfolio_action_plan_pdf") or
            not hasattr(pdf_service_module, "render_accuracy_report_pdf") or
            not hasattr(pdf_service_module, "render_discovery_pdf")):
        pdf_service_module = importlib.reload(pdf_service_module)
    render_comparison_pdf = pdf_service_module.render_comparison_pdf
    render_report_pdf = pdf_service_module.render_report_pdf
    render_watchlist_pdf = pdf_service_module.render_watchlist_pdf
    render_portfolio_pdf = pdf_service_module.render_portfolio_pdf
    render_change_pdf = pdf_service_module.render_change_pdf
    render_decision_packet_pdf = pdf_service_module.render_decision_packet_pdf
    render_portfolio_action_plan_pdf = pdf_service_module.render_portfolio_action_plan_pdf
    render_accuracy_report_pdf = pdf_service_module.render_accuracy_report_pdf
    render_discovery_pdf = pdf_service_module.render_discovery_pdf
except ModuleNotFoundError as exc:
    if exc.name != "reportlab":
        raise
    render_comparison_pdf = None
    render_report_pdf = None
    render_watchlist_pdf = None
    render_portfolio_pdf = None
    render_change_pdf = None
    render_decision_packet_pdf = None
    render_portfolio_action_plan_pdf = None
    render_accuracy_report_pdf = None
    render_discovery_pdf = None


# Streamlit can preserve imported project modules across app-only hot reloads.
modules_reloaded = False
if (not hasattr(cached_provider_module.CachedMarketDataProvider, "daily_history") or
        getattr(demo_provider_module, "DEMO_PROVIDER_VERSION", 0) < 2 or
        getattr(market_provider_module, "MARKET_PROVIDER_VERSION", 0) < 4):
    market_provider_module = importlib.reload(market_provider_module)
    demo_provider_module = importlib.reload(demo_provider_module)
    cached_provider_module = importlib.reload(cached_provider_module)
    DemoProvider = demo_provider_module.DemoProvider
    AlphaVantageProvider = market_provider_module.AlphaVantageProvider
    ProviderError = market_provider_module.ProviderError
    CachedMarketDataProvider = cached_provider_module.CachedMarketDataProvider
    CachedEconomicDataProvider = cached_provider_module.CachedEconomicDataProvider
    modules_reloaded = True
if (getattr(hybrid_provider_module, "HYBRID_PROVIDER_VERSION", 0) < 3 or
        getattr(tiingo_provider_module, "TIINGO_PROVIDER_VERSION", 0) < 2):
    tiingo_provider_module = importlib.reload(tiingo_provider_module)
    hybrid_provider_module = importlib.reload(hybrid_provider_module)
    modules_reloaded = True
TiingoProvider = tiingo_provider_module.TiingoProvider
HybridMarketDataProvider = hybrid_provider_module.HybridMarketDataProvider
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
if getattr(scheduler_service_module, "SCHEDULER_SERVICE_VERSION", 0) < 2:
    scheduler_service_module = importlib.reload(scheduler_service_module)
    DEFAULT_SCHEDULE = scheduler_service_module.DEFAULT_SCHEDULE
    SCOPES = scheduler_service_module.SCOPES
    ScheduledResearchService = scheduler_service_module.ScheduledResearchService
    modules_reloaded = True
if getattr(live_readiness_service_module, "LIVE_READINESS_SERVICE_VERSION", 0) < 2:
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
if (getattr(opportunity_discovery_service_module, "OPPORTUNITY_DISCOVERY_SERVICE_VERSION", 0) < 5 or
        not hasattr(opportunity_discovery_service_module, "select_market_candidates")):
    opportunity_discovery_service_module = importlib.reload(opportunity_discovery_service_module)
    modules_reloaded = True
build_discovery_result = opportunity_discovery_service_module.build_discovery_result
score_candidate = opportunity_discovery_service_module.score_candidate
select_market_candidates = opportunity_discovery_service_module.select_market_candidates
if getattr(discovery_monitor_service_module, "DISCOVERY_MONITOR_SERVICE_VERSION", 0) < 1:
    discovery_monitor_service_module = importlib.reload(discovery_monitor_service_module)
compare_discovery_runs = discovery_monitor_service_module.compare_discovery_runs
discovery_alerts = discovery_monitor_service_module.discovery_alerts
if (modules_reloaded or not hasattr(report_repository_module.ReportRepository, "portfolio_positions") or
        not hasattr(report_repository_module.ReportRepository, "report_tickers") or
        not hasattr(report_repository_module.ReportRepository, "scheduler_runs") or
        not hasattr(report_repository_module.ReportRepository, "add_tickers") or
        not hasattr(report_repository_module.ReportRepository, "latest_theses") or
        not hasattr(report_repository_module.ReportRepository, "latest_valuations") or
        not hasattr(report_repository_module.ReportRepository, "latest_financial_health") or
        not hasattr(report_repository_module.ReportRepository, "latest_sec_monitor_checks") or
        not hasattr(report_repository_module.ReportRepository, "position_plan_history") or
        not hasattr(report_repository_module.ReportRepository, "latest_discovery_run") or
        not hasattr(report_repository_module.ReportRepository, "discovery_runs") or
        not hasattr(report_repository_module.ReportRepository, "discovery_scheduler_runs")):
    report_repository_module = importlib.reload(report_repository_module)
    modules_reloaded = True
ReportRepository = report_repository_module.ReportRepository
if modules_reloaded or "benchmark_daily_history" not in inspect.signature(analysis_service_module.AnalysisService.analyze).parameters:
    analysis_service_module = importlib.reload(analysis_service_module)
    modules_reloaded = True
AnalysisService = analysis_service_module.AnalysisService
if modules_reloaded or getattr(comparison_service_module, "COMPARISON_SERVICE_VERSION", 0) < 8:
    comparison_service_module = importlib.reload(comparison_service_module)
ComparisonService = comparison_service_module.ComparisonService
if modules_reloaded or "discovery" not in alert_service_module.ALERT_TYPES:
    alert_service_module = importlib.reload(alert_service_module)
    ALERT_TYPES = alert_service_module.ALERT_TYPES
    AlertService = alert_service_module.AlertService
PRESETS = committee_service_module.PRESETS
STRATEGIES = committee_service_module.STRATEGIES
normalize_weights = committee_service_module.normalize_weights


def live_quota_message(data_provider, symbols: list[str]) -> str | None:
    estimator = getattr(data_provider, "estimated_requests_for_analysis", None)
    status_reader = getattr(data_provider, "status", None)
    if not estimator or not status_reader:
        return None
    status = status_reader()
    remaining = status.get("quota_remaining")
    estimate = estimator(symbols)
    if remaining is not None and estimate > remaining:
        return (
            f"This analysis needs about {estimate} Alpha Vantage requests, but only {remaining} remain "
            "in today's Atlas budget. No new live requests were made. Cached reports remain available; "
            "try again after the UTC reset or temporarily use demo mode."
        )
    return None


load_dotenv()
st.set_page_config(page_title="Project Atlas", page_icon="🧭", layout="wide")
SERVICE_CACHE_VERSION = "discovery-scheduler-v1"


@st.cache_resource
def services(cache_version: str):
    # Changing this key refreshes long-lived objects after service or database upgrades.
    _ = cache_version
    provider_name = os.getenv("ATLAS_DATA_PROVIDER", "demo").lower()
    macro_provider_name = os.getenv("ATLAS_MACRO_PROVIDER", "demo").lower()
    calendar_provider_name = os.getenv(
        "ATLAS_CALENDAR_PROVIDER", "fred" if os.getenv("FRED_API_KEY") else "demo"
    ).lower()
    base_macro_provider = FredProvider() if macro_provider_name == "fred" else DemoEconomicProvider()
    cache = ProviderCache(os.getenv("ATLAS_CACHE_PATH", "data/provider_cache.db"))
    if provider_name == "hybrid":
        base_provider = HybridMarketDataProvider(
            AlphaVantageProvider(usage_store=cache), TiingoProvider()
        )
    elif provider_name == "alpha_vantage":
        base_provider = AlphaVantageProvider(usage_store=cache)
    else:
        base_provider = DemoProvider()
    provider = CachedMarketDataProvider(base_provider, cache)
    if (provider_name in {"alpha_vantage", "hybrid"} and
            os.getenv("ATLAS_ALLOW_DEMO_FALLBACK", "true").lower() in {"1", "true", "yes", "on"}):
        provider = FallbackMarketDataProvider(provider, DemoProvider())
    macro_provider = CachedEconomicDataProvider(base_macro_provider, cache)
    repository = ReportRepository(os.getenv("ATLAS_DATABASE_PATH", "data/atlas.db"))
    event_provider = DemoEconomicEventProvider()
    if calendar_provider_name == "fred":
        economic_calendar = FredReleaseCalendarProvider(cache)
        calendar_provider = (
            CombinedCatalystCalendarProvider(economic_calendar, AlphaVantageEarningsCalendarProvider(cache))
            if os.getenv("ALPHA_VANTAGE_API_KEY") else economic_calendar
        )
    else:
        calendar_provider = DemoCatalystCalendarProvider()
    return provider, macro_provider, event_provider, calendar_provider, cache, repository, AnalysisService(provider, repository, macro_provider, event_provider, calendar_provider)


st.title("Project Atlas")
st.caption("Analysis-only investment research — no trading or brokerage connectivity")

try:
    provider, macro_provider, event_provider, calendar_provider, provider_cache, repository, analysis = services(SERVICE_CACHE_VERSION)
except RuntimeError as exc:
    st.error(f"Data provider configuration error: {exc}")
    st.info("Set ATLAS_DATA_PROVIDER=demo to use Atlas without a live-data API key.")
    st.stop()

active_configuration = load_configuration(repository)
discovery_scanner = DiscoveryScanService(provider, repository, provider_cache)
discovery_scheduler = ScheduledDiscoveryService(discovery_scanner, repository)

if provider.name.startswith("Demo"):
    st.warning("Demo mode is active. Figures are illustrative and are not live market data.")
elif "demo fallback enabled" in provider.name:
    st.info(f"{provider.name}. Demo data is clearly labeled if a live source is unavailable.")
if macro_provider.name.startswith("Demo"):
    st.warning("Demo macro mode is active. Economic figures are illustrative and are not live.")
else:
    st.info("This product uses the FRED® API but is not endorsed or certified by the Federal Reserve Bank of St. Louis.")
if calendar_provider.name.startswith("Demo"):
    st.warning("Demo calendar mode is active. Demo events cannot create catalyst alerts or Decision Center catalyst flags.")
else:
    st.info("Economic dates use FRED and company earnings dates use Alpha Vantage. Live calendars are cached to conserve requests.")
if render_report_pdf is None:
    st.warning("PDF export requires the updated dependencies. Run: python -m pip install -r requirements.txt")

def atlas_page(name: str):
    def activate() -> None:
        st.session_state["atlas_active_page"] = name
    return activate


navigation = st.navigation(
    {
        "Home": [
            st.Page(atlas_page("Start here"), title="Start here", icon=":material/home:", url_path="home", default=True),
        ],
        "Ideas": [
            st.Page(atlas_page("Market"), title="Market and watchlist", icon=":material/monitoring:", url_path="market"),
            st.Page(atlas_page("Discover"), title="Discover", icon=":material/travel_explore:", url_path="discover"),
        ],
        "Research": [
            st.Page(atlas_page("Research"), title="Company research", icon=":material/search_insights:", url_path="research"),
            st.Page(atlas_page("Financial health"), title="Financial health", icon=":material/health_metrics:", url_path="financial-health"),
            st.Page(atlas_page("Valuation lab"), title="Valuation lab", icon=":material/calculate:", url_path="valuation"),
            st.Page(atlas_page("Backtest"), title="Backtest", icon=":material/query_stats:", url_path="backtest"),
            st.Page(atlas_page("Compare"), title="Compare", icon=":material/compare_arrows:", url_path="compare"),
        ],
        "Portfolio": [
            st.Page(atlas_page("Portfolio"), title="Portfolio and sizing", icon=":material/account_balance_wallet:", url_path="portfolio"),
            st.Page(atlas_page("Stress test"), title="Stress test", icon=":material/crisis_alert:", url_path="stress-test"),
        ],
        "Monitor": [
            st.Page(atlas_page("Alerts"), title="Alerts", icon=":material/notifications:", url_path="alerts"),
            st.Page(atlas_page("Changes"), title="Changes", icon=":material/change_circle:", url_path="changes"),
            st.Page(atlas_page("Thesis tracker"), title="Thesis tracker", icon=":material/edit_note:", url_path="thesis-tracker"),
            st.Page(atlas_page("Accuracy"), title="Accuracy", icon=":material/track_changes:", url_path="accuracy"),
        ],
        "System": [
            st.Page(atlas_page("Provider health"), title="Provider health", icon=":material/monitor_heart:", url_path="provider-health"),
            st.Page(atlas_page("Data readiness"), title="Data readiness", icon=":material/cloud_done:", url_path="data-readiness"),
            st.Page(atlas_page("Settings"), title="Settings", icon=":material/settings:", url_path="settings"),
            st.Page(atlas_page("Report history"), title="Report history", icon=":material/history:", url_path="report-history"),
        ],
    },
    position="sidebar",
    expanded=True,
)
navigation.run()
active_page = os.getenv("ATLAS_TEST_PAGE") or st.session_state.get("atlas_active_page", "Start here")

if active_page == "Start here":
    st.subheader("Start here")
    st.caption("Choose a company, see what evidence is ready, and complete the next research step. This view makes no provider requests until you click an action.")
    decision_watchlist = repository.watchlist()
    decision_positions = repository.portfolio_positions()
    decision_theses = repository.latest_theses()
    decision_valuations = repository.latest_valuations()
    decision_financial_health = repository.latest_financial_health()
    decision_symbols = list(dict.fromkeys(
        decision_watchlist + [item["ticker"] for item in decision_positions]
        + [item["ticker"] for item in decision_theses]
        + [item["ticker"] for item in decision_valuations]
        + [item["ticker"] for item in decision_financial_health]
    ))
    decision_reports = repository.latest_reports(decision_symbols)
    decision_health_map = {item["ticker"]: item for item in decision_financial_health}
    decision_trust = {
        ticker: assess_evidence_trust(
            decision_reports.get(ticker), decision_health_map.get(ticker),
            active_configuration["freshness_days"],
        ) for ticker in decision_symbols
    }
    decision_histories = {ticker: repository.recent_reports(ticker, 2) for ticker in decision_symbols}
    decision_stress = st.session_state.get("stress_result")
    if decision_stress is None and decision_positions and decision_reports:
        try:
            decision_stress = analyze_stress_scenario(
                decision_positions, decision_reports, "Broad market decline", theses=decision_theses,
            )
        except ValueError:
            decision_stress = None
    decision_center = build_decision_center(
        decision_watchlist, decision_reports, decision_histories, decision_theses,
        repository.alerts(50, unread_only=True), decision_positions, decision_stress,
        provider.status(), active_configuration["freshness_days"], valuations=decision_valuations,
        financial_health=decision_financial_health,
        evidence_trust=decision_trust,
    )
    home_options = decision_symbols or ["AAPL"]
    home_ticker = st.selectbox(
        "Company", home_options, key="home-company", accept_new_options=True,
        placeholder="Choose or enter a ticker",
    ).strip().upper()
    home_report = decision_reports.get(home_ticker) or repository.latest_reports([home_ticker]).get(home_ticker)
    home_valuation = next((item for item in decision_valuations if item["ticker"] == home_ticker), None)
    home_thesis = next((item for item in decision_theses if item["ticker"] == home_ticker), None)
    home_health = next((item for item in decision_financial_health if item["ticker"] == home_ticker), None)
    home_trust = decision_trust.get(home_ticker) or assess_evidence_trust(
        home_report, home_health, active_configuration["freshness_days"],
    )
    home_alerts = repository.alerts(100, unread_only=True)
    workflow = build_company_workflow(
        home_ticker, decision_watchlist, home_report, home_valuation, home_thesis,
        home_health, home_alerts, active_configuration["freshness_days"],
    )
    st.markdown("#### Your research path")
    with st.container(horizontal=True):
        st.metric("Workflow ready", f"{workflow['completion']}%", border=True)
        st.metric("Checks complete", f"{workflow['ready']} of {workflow['total']}", border=True)
        st.metric("Data mode", "Demo" if provider.name.startswith("Demo") else "Live / hybrid", border=True)
    st.info(workflow["summary"], icon=":material/route:")
    st.dataframe(
        workflow["checks"], hide_index=True,
        column_config={
            "Evidence": st.column_config.TextColumn(pinned=True),
            "Status": st.column_config.TextColumn(pinned=True),
        },
    )
    st.markdown("##### Evidence trust")
    with st.container(horizontal=True):
        st.metric("Trust status", home_trust["status"], border=True)
        st.metric("Evidence trust", f"{home_trust['score']}/100", border=True)
        st.metric("Buy label gate", "Open" if home_trust["buy_allowed"] else "Closed", border=True)
    if home_trust["status"] == "Live":
        st.success(home_trust["summary"], icon=":material/verified:")
    elif home_trust["status"] == "Partial":
        st.info(home_trust["summary"], icon=":material/info:")
    else:
        st.warning(home_trust["summary"], icon=":material/warning:")
    st.dataframe(
        home_trust["components"], hide_index=True,
        column_config={
            "Evidence": st.column_config.TextColumn(pinned=True),
            "Score": st.column_config.ProgressColumn(min_value=0, max_value=100),
        },
    )
    for warning in home_trust["warnings"]:
        st.caption(f"Warning: {warning}")
    st.markdown("##### Complete an action")
    with st.container(horizontal=True):
        if st.button(
            "Add to watchlist", icon=":material/add:", key="home-add-watchlist",
            disabled=home_ticker in decision_watchlist,
        ):
            try:
                repository.add_ticker(home_ticker)
                st.toast(f"Added {home_ticker} to the watchlist.", icon=":material/check_circle:")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
        if st.button("Run / refresh research", icon=":material/analytics:", key="home-run-research"):
            try:
                if quota_message := live_quota_message(provider, [home_ticker]):
                    raise ProviderError(quota_message)
                with st.spinner(f"Building {home_ticker} research…"):
                    st.session_state["report"] = analysis.analyze(
                        home_ticker, PRESETS[active_configuration["committee_preset"]],
                    )
                st.toast(f"Saved fresh research for {home_ticker}.", icon=":material/check_circle:")
                st.rerun()
            except (ProviderError, RuntimeError, ValueError) as exc:
                st.error(str(exc))
        if st.button("Check SEC filing", icon=":material/description:", key="home-check-sec"):
            result = SecMonitorService(SecCompanyFactsProvider(provider_cache), repository).refresh([home_ticker])
            if result["failed"]:
                st.error(result["rows"][0]["Message"])
            else:
                label = "saved a new filing" if result["saved"] else "confirmed the current filing"
                st.toast(f"SEC monitor {label} for {home_ticker}.", icon=":material/check_circle:")
                st.rerun()
        if st.button("Scan alerts", icon=":material/notifications:", key="home-scan-alerts"):
            alert_result = AlertService(repository).scan([home_ticker])
            st.toast(
                f"Alert scan complete: {alert_result['created']} new alert(s).",
                icon=":material/notifications_active:",
            )
            st.rerun()
        if st.button("Refresh stale evidence", icon=":material/sync:", key="home-refresh-evidence"):
            try:
                if quota_message := live_quota_message(provider, [home_ticker]):
                    raise ProviderError(quota_message)
                with st.spinner(f"Refreshing critical evidence for {home_ticker}…"):
                    fresh_report = analysis.analyze(
                        home_ticker, PRESETS[active_configuration["committee_preset"]],
                    )
                    if os.getenv("SEC_USER_AGENT"):
                        SecMonitorService(SecCompanyFactsProvider(provider_cache), repository).refresh([home_ticker])
                    fresh_health = next((
                        item for item in repository.latest_financial_health()
                        if item["ticker"] == home_ticker
                    ), None)
                    fresh_trust = assess_evidence_trust(
                        fresh_report, fresh_health, active_configuration["freshness_days"],
                    )
                    trust_alert = build_trust_alert(
                        home_ticker, fresh_trust, fresh_report.report_id or fresh_report.created_at,
                    )
                    if trust_alert:
                        repository.add_alert(trust_alert)
                st.toast(f"Refreshed evidence for {home_ticker}; trust is {fresh_trust['status']}.", icon=":material/check_circle:")
                st.rerun()
            except (ProviderError, RuntimeError, ValueError) as exc:
                st.error(str(exc))
    if not home_valuation or not home_thesis:
        missing_forms = []
        if not home_valuation:
            missing_forms.append("Valuation lab")
        if not home_thesis:
            missing_forms.append("Thesis tracker")
        st.caption("Next manual step: open " + " and ".join(missing_forms) + " above to review assumptions before saving.")
    with st.expander("App setup and live-data status", icon=":material/settings:"):
        st.dataframe(build_setup_status(
            provider.name, macro_provider.name, calendar_provider.name,
            bool(os.getenv("SEC_USER_AGENT")), render_report_pdf is not None,
        ), hide_index=True)
        st.caption("Demo status is acceptable while building. Switch providers only when you are ready to validate live data.")

    st.markdown("#### Beginner decision guide")
    st.caption("A plain-language research posture built from the latest saved evidence. It is a starting point for review, not a personalized instruction to trade.")
    beginner_guidance = decision_center["beginner_guidance"]
    if beginner_guidance:
        beginner_ticker = st.selectbox(
            "Company to explain", [item["Ticker"] for item in beginner_guidance], key="beginner-guide-company",
        )
        beginner_view = next(item for item in beginner_guidance if item["Ticker"] == beginner_ticker)
        with st.container(horizontal=True):
            st.metric("Beginner view", beginner_view["Beginner view"], border=True)
            st.metric("Evidence confidence", beginner_view["Confidence"], border=True)
            st.metric("Evidence score", "Not available" if beginner_view["Score"] is None else f"{beginner_view['Score']}/100", border=True)
            st.metric("Data trust", f"{beginner_view['Trust status']} ({beginner_view['Trust score']}/100)", border=True)
            st.metric("Saved position", "Yes" if beginner_view["Owned"] else "No", border=True)
        if beginner_view["Beginner view"] == "Buy candidate":
            st.success(beginner_view["Plain-language summary"])
        elif beginner_view["Beginner view"] in {"Sell / reduce review", "Avoid / review"}:
            st.error(beginner_view["Plain-language summary"])
        elif beginner_view["Beginner view"] == "Research first":
            st.warning(beginner_view["Plain-language summary"])
        else:
            st.info(beginner_view["Plain-language summary"])
        st.dataframe([{
            "What supports this view": beginner_view["What supports it"],
            "What could go wrong": beginner_view["What could go wrong"],
            "Suggested next step": beginner_view["Suggested next step"],
        }], hide_index=True)
        with st.expander("Beginner checklist and label meanings"):
            st.markdown(
                """
**Before acting on any label:**

- Keep emergency savings separate from investing money.
- Avoid putting too much of your portfolio into one company or sector.
- Read the bear case, valuation assumptions, and upcoming catalysts.
- Decide the maximum loss and position size you can tolerate before buying.
- Recheck whether the report uses demo, fallback, stale, or live data.

**What the labels mean:**

- **Buy candidate:** evidence is constructive and a saved valuation supports the current price.
- **Hold:** an existing saved position has mixed or stable evidence without a strong change signal.
- **Watch:** interesting, but price or evidence is not strong enough yet.
- **Sell / reduce review:** a held position has a serious warning sign; review it rather than selling automatically.
- **Avoid / review:** a company not marked as held has serious warning signs.
- **Research first:** key evidence is missing or too old.
                """
            )
    else:
        st.info("Add companies to the watchlist and run Research to create beginner-friendly views.")
    home_guidance = next((item for item in beginner_guidance if item["Ticker"] == home_ticker), None)
    home_sizing_history = repository.position_plan_history(home_ticker, 1)
    decision_packet = build_decision_packet(
        home_ticker, home_report, home_guidance, workflow, home_valuation, home_thesis,
        home_health, home_sizing_history[0] if home_sizing_history else None, home_alerts,
        home_trust,
    )
    st.markdown("#### Company decision packet")
    st.caption("A unified snapshot of saved Atlas evidence. Opening or downloading it makes no provider requests.")
    with st.container(horizontal=True):
        st.metric("Decision posture", decision_packet["beginner_view"], border=True)
        st.metric("Evidence confidence", decision_packet["evidence_confidence"], border=True)
        st.metric("Missing or flagged", len(decision_packet["missing_evidence"]), border=True)
        st.metric("Active alerts", len(decision_packet["alerts"]), border=True)
    if home_trust["status"] == "Live":
        st.success(decision_packet["data_watermark"])
    else:
        st.warning(decision_packet["data_watermark"])
    if render_decision_packet_pdf:
        st.download_button(
            "Download decision packet PDF", data=render_decision_packet_pdf(decision_packet),
            file_name=f"atlas-{home_ticker.lower()}-decision-packet.pdf", mime="application/pdf",
            key=f"download-decision-packet-{home_ticker}", icon=":material/download:",
        )
    packet_view = st.expander("Open decision packet", icon=":material/article:", on_change="rerun")
    if packet_view.open:
        with packet_view:
            st.markdown("##### Decision explanation")
            st.write(decision_packet["plain_language_summary"])
            st.dataframe([{
                "What supports it": decision_packet["supports"],
                "What could change it": decision_packet["cautions"],
                "Next step": decision_packet["next_step"],
            }], hide_index=True)
            if decision_packet["committee"]:
                committee = decision_packet["committee"]
                with st.container(horizontal=True):
                    st.metric("Committee vote", committee["vote"], border=True)
                    st.metric("Committee confidence", f"{committee['confidence']}%", border=True)
                    st.metric("Committee score", f"{committee['score']:.1f}/100", border=True)
                    st.metric(
                        "Technical trend",
                        decision_packet["technical"].get("label", decision_packet["technical"].get("status", "Unavailable")),
                        border=True,
                    )
                st.write(decision_packet["report"].get("executive_summary", ""))
                evidence_columns = st.columns(2)
                with evidence_columns[0]:
                    st.markdown("**Bull case**")
                    for item in decision_packet["report"].get("bull_case", []):
                        st.write(f"- {item}")
                    st.markdown("**Risks**")
                    for item in decision_packet["report"].get("risks", []):
                        st.write(f"- {item}")
                with evidence_columns[1]:
                    st.markdown("**Bear case**")
                    for item in decision_packet["report"].get("bear_case", []):
                        st.write(f"- {item}")
                    st.markdown("**Catalysts**")
                    for item in decision_packet["report"].get("catalysts", []):
                        st.write(f"- {item}")
            else:
                st.warning("Run Research to add the committee, investment case, trend, and market evidence.")
            st.markdown("##### Valuation, SEC health, thesis, and sizing")
            packet_rows = [{
                "Evidence": "Valuation", "Status": (decision_packet["valuation"] or {}).get("status", "Not saved"),
                "Key result": "Unavailable" if not decision_packet["valuation"] else
                    f"{decision_packet['valuation'].get('margin_of_safety', 0):+.1f}% margin of safety",
            }, {
                "Evidence": "SEC financial health", "Status": (decision_packet["financial_health"] or {}).get("posture", "Not analyzed"),
                "Key result": "Unavailable" if not decision_packet["financial_health"] else
                    f"{decision_packet['financial_health'].get('score')}/100",
            }, {
                "Evidence": "Personal thesis", "Status": (decision_packet["thesis_evaluation"] or {}).get("status", "Not saved"),
                "Key result": (decision_packet["thesis"] or {}).get("stance", "Unavailable"),
            }, {
                "Evidence": "Position sizing", "Status": "Saved" if decision_packet["position_plan"] else "Not saved",
                "Key result": "Unavailable" if not decision_packet["position_plan"] else
                    f"{decision_packet['position_plan'].get('suggested_shares', 0):,} share ceiling",
            }]
            st.dataframe(packet_rows, hide_index=True)
            if decision_packet["alerts"]:
                st.markdown("##### Active alerts")
                st.dataframe([{
                    "Severity": item.get("severity"), "Title": item.get("title"),
                    "Message": item.get("message"), "Created": item.get("created_at"),
                } for item in decision_packet["alerts"]], hide_index=True)
            st.markdown("##### Sources and freshness")
            st.dataframe(decision_packet["sources"], hide_index=True)
            st.caption(decision_packet["disclosure"])
    st.divider()
    st.markdown("#### Priority research queue")
    with st.container(horizontal=True):
        st.metric("Critical", decision_center["counts"]["Critical"], border=True)
        st.metric("High priority", decision_center["counts"]["High"], border=True)
        st.metric("Medium priority", decision_center["counts"]["Medium"], border=True)
        st.metric("Companies flagged", decision_center["companies"], border=True)
        st.metric("Unread alerts", repository.unread_alert_count(), border=True)
    if decision_center["items"]:
        st.warning(decision_center["summary"])
        filters = st.container(horizontal=True, vertical_alignment="bottom")
        with filters:
            priority_filter = st.selectbox("Priority", ["All", *PRIORITIES], key="decision-priority")
            category_options = sorted({item["Category"] for item in decision_center["items"]})
            category_filter = st.selectbox("Category", ["All", *category_options], key="decision-category")
            ticker_options = sorted({item["Ticker"] for item in decision_center["items"]})
            ticker_filter = st.selectbox("Company", ["All", *ticker_options], key="decision-ticker")
        filtered_items = [
            item for item in decision_center["items"]
            if (priority_filter == "All" or item["Priority"] == priority_filter)
            and (category_filter == "All" or item["Category"] == category_filter)
            and (ticker_filter == "All" or item["Ticker"] == ticker_filter)
        ]
        st.dataframe(
            filtered_items, hide_index=True,
            column_config={
                "Priority": st.column_config.TextColumn(pinned=True),
                "Ticker": st.column_config.TextColumn(pinned=True),
            },
        )
        st.caption("Use the Research follow-up column to identify the relevant Atlas tab.")
    else:
        st.success(decision_center["summary"])
    if st.button("Refresh decision queue", icon=":material/refresh:", key="refresh-decision-center"):
        st.rerun()
    st.caption(decision_center["disclosure"])

if active_page == "Market":
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
    except (RuntimeError, ValueError) as exc:
        st.warning(f"Market environment is temporarily unavailable: {exc}")

    st.subheader("Watchlist")
    watchlist_notice = st.session_state.pop("watchlist_notice", None)
    if watchlist_notice:
        if watchlist_notice[0] == "success":
            st.success(watchlist_notice[1])
        else:
            st.info(watchlist_notice[1])
    st.caption("There is no watchlist size limit. Enter exact symbols and press Enter to add them without using an API request.")
    with st.form("watchlist-direct-add", border=False):
        direct_tickers = st.text_input(
            "Add exact ticker symbols", placeholder="AAPL, MSFT, NVDA",
            help="Enter one or several symbols separated by commas or spaces.",
        )
        add_direct = st.form_submit_button(
            "Add to watchlist", type="primary", icon=":material/add:"
        )
    if add_direct:
        try:
            symbols = [item for item in re.split(r"[\s,;]+", direct_tickers.strip()) if item]
            if not symbols:
                raise ValueError("Enter at least one ticker symbol.")
            before = set(repository.watchlist())
            if hasattr(repository, "add_tickers"):
                repository.add_tickers(symbols)
            else:
                for symbol in symbols:
                    repository.add_ticker(symbol)
            added = len(set(repository.watchlist()) - before)
            if added:
                message = f"Added {added} new compan{'y' if added == 1 else 'ies'}: " + ", ".join(symbol.upper() for symbol in symbols)
                st.session_state["watchlist_notice"] = ("success", message)
            else:
                st.session_state["watchlist_notice"] = ("info", "Those ticker symbols are already on the watchlist.")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

    with st.expander("Search by company name"):
        with st.form("watchlist-company-search", border=False):
            query = st.text_input("Company name or ticker", placeholder="Apple")
            run_search = st.form_submit_button("Search", icon=":material/search:")
        if run_search:
            try:
                st.session_state["watchlist_search_results"] = provider.search(query) if query.strip() else []
                st.session_state["watchlist_search_completed"] = True
            except (RuntimeError, ValueError) as exc:
                st.error(str(exc))
        search_results = st.session_state.get("watchlist_search_results", [])
        if st.session_state.get("watchlist_search_completed") and not search_results:
            st.info("No matching companies were returned. If you know the ticker, add it with the exact-symbol box above.")
        for match in search_results:
            with st.container(horizontal=True, vertical_alignment="center"):
                st.write(f"**{match['symbol']}** — {match['name']}")
                if st.button("Add", key=f"add-search-{match['symbol']}"):
                    repository.add_ticker(match["symbol"])
                    st.session_state["watchlist_notice"] = (
                        "success", f"Added {match['symbol']} — {match['name']} to the watchlist."
                    )
                    st.rerun()
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
    if dashboard_calendar_snapshot.get("error"):
        st.warning(
            "One or more live calendar sources are temporarily unavailable. "
            + ("Available or stale dates are labeled; stale dates cannot generate alerts." if dashboard_calendar_snapshot.get("events") else "No dates are being inferred.")
        )
    calendar_rows = global_calendar(dashboard_calendar_snapshot, watchlist)
    if calendar_rows:
        st.dataframe(
            [{
                "Date": event["date"], "Days": event["days_until"], "Event": event["title"],
                "Category": event["category"], "Scope": event["scope"].title(),
                "Importance": event["importance"], "Confidence": event["confidence"],
                "Date status": event.get("timing_status", "Scheduled"),
                "EPS estimate": event.get("eps_estimate"),
                "Source": event.get("source", "Unknown"),
            } for event in calendar_rows],
            column_config={
                "Date": st.column_config.DateColumn(format="MMM DD, YYYY"),
                "Importance": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%d"),
                "Confidence": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%d%%"),
                "EPS estimate": st.column_config.NumberColumn(format="%.2f"),
            },
            hide_index=True,
        )
        source_status = "Live" if dashboard_calendar_snapshot.get("live") and not dashboard_calendar_snapshot.get("stale") else "Stale cache" if dashboard_calendar_snapshot.get("stale") else "Demo"
        st.caption(
            f"Source: {dashboard_calendar_snapshot['provider']} · {source_status} · "
            f"{dashboard_calendar_snapshot.get('cache_status', 'Direct')} · Retrieved {dashboard_calendar_snapshot.get('retrieved_at', 'unknown')}"
        )
    elif not dashboard_calendar_snapshot.get("error"):
        st.info("No recognized economic releases are scheduled in the next 180 days.")
    with st.container(horizontal=True):
        if st.button("Refresh live calendars", icon=":material/refresh:", key="refresh-live-calendars"):
            provider_cache.clear("fred_calendar")
            provider_cache.clear("alpha_vantage_earnings")
            st.rerun()
        st.caption("Earnings dates are provider estimates until the company confirms its reporting schedule.")

    if watchlist:
        st.markdown("#### Ranked watchlist")
        controls = st.container(horizontal=True, vertical_alignment="bottom")
        with controls:
            watchlist_preset = st.selectbox("Analysis preset", list(PRESETS), key="watchlist_preset")
            ranking_mode = st.selectbox("Rank by", RANKING_MODES, key="watchlist_ranking_mode")
            analyze_watchlist = st.button("Analyze all", type="primary", key="analyze-watchlist")
        if analyze_watchlist:
            try:
                if quota_message := live_quota_message(provider, watchlist):
                    raise ProviderError(quota_message)
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
            except (RuntimeError, ValueError) as exc:
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

if active_page == "Discover":
    st.subheader("Opportunity discovery")
    st.caption(
        "Atlas automatically reads the U.S. market-movers feed, removes your watchlist and portfolio, then ranks a "
        "small liquid candidate set by valuation, quality, growth, trend, and risk."
    )
    discovery_schedule_status = discovery_scheduler.status()
    discovery_schedule_last = discovery_schedule_status["last_run"]
    with st.container(horizontal=True):
        st.metric(
            "Daily monitor", "Enabled" if discovery_schedule_status["configuration"]["enabled"] else "Paused",
            border=True,
        )
        st.metric(
            "Last scheduled result", discovery_schedule_last["status"] if discovery_schedule_last else "Never run",
            border=True,
        )
        st.metric(
            "Next scheduled scan",
            discovery_schedule_status["next_run"][:16].replace("T", " ") + " UTC"
            if discovery_schedule_status["next_run"] else "Not scheduled",
            border=True,
        )
    if not discovery_schedule_status["configuration"]["enabled"]:
        st.caption("Enable the daily Discovery monitor in Settings when you are ready.")
    radar = set(repository.watchlist()) | {item["ticker"] for item in repository.portfolio_positions()}
    with st.form("discovery-screen-form"):
        discovery_limit = st.number_input(
            "Automatic candidates to analyze", min_value=1, max_value=8, value=5, step=1,
            help="Atlas selects these automatically after excluding your radar. Each uncached finalist uses provider requests.",
        )
        run_discovery = st.form_submit_button("Scan market for new ideas", type="primary", icon=":material/travel_explore:")
    if run_discovery:
        try:
            with st.status("Scanning the market and analyzing unfamiliar candidates…", expanded=True):
                result = discovery_scanner.run(int(discovery_limit))
            st.session_state["discovery_result"] = result
            st.rerun()
        except (ProviderError, RuntimeError, TypeError, ValueError) as exc:
            st.error(str(exc))
    discovery_result = st.session_state.get("discovery_result") or repository.latest_discovery_run()
    if discovery_result:
        with st.container(horizontal=True):
            st.metric("Companies screened", len(discovery_result["rows"]), border=True)
            st.metric("Outside your radar", discovery_result["outside_radar"], border=True)
            st.metric("Strong candidates", discovery_result["strong_candidates"], border=True)
            st.metric("Unavailable", len(discovery_result["failures"]), border=True)
        st.info(discovery_result["summary"], icon=":material/radar:")
        st.caption(
            f"Candidate source: {discovery_result.get('market_source', 'Saved market feed')} · "
            f"Market feed as of {discovery_result.get('market_as_of', 'unknown')} · Existing radar excluded before analysis."
        )
        price_only_count = sum(row.get("Data status") == "Live price only" for row in discovery_result["rows"])
        sec_supported_count = sum(row.get("Data status") == "Live price + SEC" for row in discovery_result["rows"])
        if sec_supported_count:
            st.success(
                f"{sec_supported_count} candidate(s) combine live Tiingo market data with current SEC EDGAR "
                "filing fundamentals. Forward valuation estimates remain unavailable until Alpha Vantage resets."
            )
        if price_only_count:
            st.warning(
                f"{price_only_count} candidate(s) use live Tiingo price and trend data only because Alpha Vantage "
                "fundamentals are currently unavailable. These leads cannot receive a Strong candidate label. "
                "Run full research after the Alpha Vantage daily budget resets."
            )
        monitor = discovery_result.get("monitor") or {}
        st.markdown("#### Discovery monitor")
        if monitor.get("has_baseline"):
            with st.container(horizontal=True):
                st.metric("New candidates", monitor.get("new_candidates", 0), border=True)
                st.metric("Evidence upgrades", monitor.get("upgrades", 0), border=True)
                st.metric("Downgrades", monitor.get("downgrades", 0), border=True)
                st.metric("Left screen", monitor.get("removed", 0), border=True)
            st.caption(monitor.get("summary", ""))
            if monitor.get("events"):
                st.dataframe(
                    monitor["events"], hide_index=True,
                    column_config={
                        "Previous score": st.column_config.NumberColumn(format="%.1f"),
                        "Current score": st.column_config.NumberColumn(format="%.1f"),
                    },
                )
            else:
                st.info("No meaningful candidate changes since the previous scan.")
        else:
            st.info("This scan is the monitoring baseline. Run another scan after market data refreshes to see changes.")
        with st.expander("Discovery scan history"):
            history_rows = repository.discovery_runs(20)
            st.dataframe([{
                "Run": item["id"], "Saved": item.get("saved_at"),
                "Candidates": len(item.get("rows", [])),
                "Strong": item.get("strong_candidates", 0),
                "Changes": len((item.get("monitor") or {}).get("events", [])),
                "Source": item.get("market_source", "Unknown"),
                "Market as of": item.get("market_as_of"),
            } for item in history_rows], hide_index=True)
        st.dataframe(
            discovery_result["rows"], hide_index=True,
            column_config={
                "Rank": st.column_config.NumberColumn(pinned=True, format="%d"),
                "Ticker": st.column_config.TextColumn(pinned=True),
                "Discovery score": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f"),
                "Price": st.column_config.NumberColumn(format="$%.2f"),
                "Forward P/E": st.column_config.NumberColumn(format="%.2f"),
                "PEG": st.column_config.NumberColumn(format="%.2f"),
                "Valuation": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f"),
                "Quality": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f"),
                "Growth": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f"),
                "Trend": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f"),
                "Risk fit": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f"),
                "90-day momentum": st.column_config.NumberColumn(format="%+.1f%%"),
                "Market change": st.column_config.NumberColumn(format="%+.2f%%"),
                "Market volume": st.column_config.NumberColumn(format="compact"),
            },
        )
        eligible = [row["Ticker"] for row in discovery_result["rows"] if row["Research label"] != "Pass for now"]
        finalists = st.multiselect(
            "Finalists for deeper research", eligible,
            default=[row["Ticker"] for row in discovery_result["rows"][:3] if row["Ticker"] in eligible],
            key="discovery-finalists",
        )
        with st.container(horizontal=True):
            if st.button("Add finalists to watchlist", disabled=not finalists, icon=":material/playlist_add:", key="add-discovery-finalists"):
                added = repository.add_tickers(finalists)
                st.toast(f"Added {added} new company or companies to the watchlist.", icon=":material/check_circle:")
                st.rerun()
            if st.button("Run full research on finalists", disabled=not finalists, icon=":material/analytics:", key="research-discovery-finalists"):
                try:
                    if quota_message := live_quota_message(provider, finalists):
                        raise ProviderError(quota_message)
                    progress = st.progress(0, text="Researching discovery finalists…")
                    for index, symbol in enumerate(finalists, 1):
                        progress.progress((index - 1) / len(finalists), text=f"Analyzing {symbol}…")
                        analysis.analyze(symbol, PRESETS[active_configuration["committee_preset"]])
                    progress.progress(1.0, text="Finalist research complete")
                    st.success(f"Completed full Atlas research for {len(finalists)} finalist(s).")
                except (ProviderError, RuntimeError, ValueError) as exc:
                    st.error(str(exc))
        if discovery_result["failures"]:
            with st.expander("Unavailable companies"):
                st.dataframe(discovery_result["failures"], hide_index=True)
        if render_discovery_pdf:
            st.download_button(
                "Download discovery report PDF", data=render_discovery_pdf(discovery_result),
                file_name="atlas-opportunity-discovery.pdf", mime="application/pdf",
                key="download-discovery-report", icon=":material/download:",
            )
        st.caption(discovery_result["disclosure"])
    else:
        st.info("Run the broad screen to create your first opportunity-discovery ranking.")

if active_page == "Portfolio":
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
            if quota_message := live_quota_message(provider, scenario_symbols):
                raise ProviderError(quota_message)
            macro_snapshot = macro_provider.snapshot()
            environment_snapshot = analyze_market_environment(event_provider.snapshot(), macro_snapshot)
            calendar_snapshot = calendar_provider.snapshot()
            benchmark_history = provider.history("SPY")
            benchmark_daily_history = provider.daily_history("SPY")
            progress = st.progress(0, text="Refreshing portfolio research…")
            for index, symbol in enumerate(scenario_symbols, start=1):
                progress.progress((index - 1) / len(scenario_symbols), text=f"Analyzing {symbol}…")
                analysis.analyze(
                    symbol, PRESETS[portfolio_preset], macro_snapshot=macro_snapshot,
                    benchmark_history=benchmark_history, market_environment=environment_snapshot,
                    calendar_snapshot=calendar_snapshot, benchmark_daily_history=benchmark_daily_history,
                )
            progress.progress(1.0, text="Portfolio research refreshed")
            st.success(f"Refreshed {len(scenario_symbols)} holding reports.")
            st.rerun()
        except (RuntimeError, ValueError) as exc:
            st.error(f"Portfolio refresh failed: {exc}")

    if scenario_symbols:
        try:
            portfolio_reports = repository.latest_reports(scenario_symbols)
            portfolio_analysis = analyze_portfolio_exposure(
                scenario_positions, portfolio_reports, active_configuration["freshness_days"],
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
            portfolio_health = repository.latest_financial_health()
            portfolio_health_map = {item["ticker"]: item for item in portfolio_health}
            portfolio_trust = {
                ticker: assess_evidence_trust(
                    portfolio_reports.get(ticker), portfolio_health_map.get(ticker),
                    active_configuration["freshness_days"],
                ) for ticker in scenario_symbols
            }
            portfolio_guidance = build_beginner_guidance(
                scenario_symbols, portfolio_reports, repository.latest_theses(), repository.alerts(100, unread_only=True),
                [{"ticker": str(item.get("Ticker", "")).strip().upper(), "allocation": item.get("Allocation", 0)}
                 for item in scenario_positions], repository.latest_valuations(),
                active_configuration["freshness_days"], portfolio_health, portfolio_trust,
            )
            portfolio_sizing = {}
            for ticker in scenario_symbols:
                history = repository.position_plan_history(ticker, 1)
                if history:
                    portfolio_sizing[ticker] = history[0]
            portfolio_action_plan = build_portfolio_action_plan(
                portfolio_analysis, portfolio_guidance, portfolio_trust, portfolio_sizing,
            )
            st.markdown("#### Portfolio action plan")
            st.caption(
                "A prioritized weekly review based on saved evidence, trust, risk, concentration, and position ceilings. "
                "Actions are review prompts, not trade instructions."
            )
            with st.container(horizontal=True):
                st.metric("Do now", portfolio_action_plan["counts"]["Do now"], border=True)
                st.metric("Review soon", portfolio_action_plan["counts"]["Review soon"], border=True)
                st.metric("Monitor", portfolio_action_plan["counts"]["Monitor"], border=True)
                st.metric(
                    "Portfolio evidence trust",
                    "N/A" if portfolio_action_plan["portfolio_trust"] is None else f"{portfolio_action_plan['portfolio_trust']}/100",
                    border=True,
                )
            if portfolio_action_plan["counts"]["Do now"]:
                st.warning(portfolio_action_plan["summary"], icon=":material/priority_high:")
            else:
                st.info(portfolio_action_plan["summary"], icon=":material/checklist:")
            st.dataframe(
                portfolio_action_plan["rows"], hide_index=True,
                column_config={
                    "Priority": st.column_config.TextColumn(pinned=True),
                    "Ticker": st.column_config.TextColumn(pinned=True),
                    "Current weight": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f%%"),
                    "Saved ceiling": st.column_config.NumberColumn(format="%.1f%%"),
                    "Room to ceiling": st.column_config.NumberColumn(format="%+.1f%%"),
                    "Trust score": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f"),
                    "Risk score": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f"),
                },
            )
            if render_portfolio_action_plan_pdf:
                st.download_button(
                    "Download portfolio action plan PDF", data=render_portfolio_action_plan_pdf(portfolio_action_plan),
                    file_name="atlas-portfolio-action-plan.pdf", mime="application/pdf",
                    key="download-portfolio-action-plan", icon=":material/download:",
                )
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

    st.markdown("#### Position-sizing and diversification planner")
    st.caption(
        "Estimate an educational position ceiling from a maximum loss budget and concentration limit. "
        "Atlas does not place trades, and actual losses can exceed the estimate."
    )
    planner_symbols = sorted(set(
        repository.watchlist() + repository.report_tickers()
        + [item["ticker"] for item in repository.portfolio_positions()]
    ))
    if planner_symbols:
        sizing_ticker = st.selectbox("Company to size", planner_symbols, key="position-sizing-company")
        sizing_report = repository.latest_reports([sizing_ticker]).get(sizing_ticker)
        sizing_health = next((
            item for item in repository.latest_financial_health() if item["ticker"] == sizing_ticker
        ), None)
        sizing_preset = st.segmented_control(
            "Sizing approach", list(SIZING_PRESETS), default="Balanced", key="position-sizing-preset",
        )
        preset_values = SIZING_PRESETS[sizing_preset]
        report_price = float((sizing_report.company_metrics.get("price") if sizing_report else None) or 100)
        with st.form("position-sizing-form", border=True):
            with st.container(horizontal=True):
                portfolio_value = st.number_input(
                    "Portfolio value ($)", min_value=1.0, value=100000.0, step=1000.0,
                    key=f"sizing-portfolio-{sizing_ticker}",
                )
                planned_entry = st.number_input(
                    "Planned entry price ($)", min_value=0.01, value=report_price, step=1.0,
                    key=f"sizing-entry-{sizing_ticker}",
                )
                invalidation_price = st.number_input(
                    "Thesis-invalidation price ($)", min_value=0.01,
                    value=round(report_price * 0.9, 2), step=1.0,
                    key=f"sizing-invalidation-{sizing_ticker}",
                )
            with st.container(horizontal=True):
                sizing_risk_percent = st.number_input(
                    "Maximum portfolio risk (%)", min_value=0.1, max_value=10.0,
                    value=float(preset_values["risk_percent"]), step=0.1,
                    key=f"sizing-risk-{sizing_preset}",
                )
                sizing_max_allocation = st.number_input(
                    "Maximum company allocation (%)", min_value=1.0, max_value=100.0,
                    value=float(preset_values["max_allocation"]), step=1.0,
                    key=f"sizing-allocation-{sizing_preset}",
                )
            calculate_position = st.form_submit_button(
                "Calculate position ceiling", type="primary", icon=":material/calculate:",
            )
        if calculate_position:
            try:
                saved_allocations = repository.portfolio_positions()
                existing_allocation = next((
                    float(item["allocation"]) for item in saved_allocations if item["ticker"] == sizing_ticker
                ), 0.0)
                sector_allocation = 0.0
                if sizing_report:
                    saved_reports = repository.latest_reports([item["ticker"] for item in saved_allocations])
                    selected_sector = sizing_report.company_metrics.get("sector")
                    sector_allocation = sum(
                        float(item["allocation"]) for item in saved_allocations
                        if saved_reports.get(item["ticker"])
                        and saved_reports[item["ticker"]].company_metrics.get("sector") == selected_sector
                    )
                st.session_state["position_plan"] = build_position_plan(
                    sizing_ticker, portfolio_value, planned_entry, invalidation_price,
                    sizing_risk_percent, sizing_max_allocation,
                    risk_score=sizing_report.risk.get("score") if sizing_report else None,
                    readiness_score=sizing_report.entry_readiness.get("score") if sizing_report else None,
                    financial_health_score=sizing_health.get("score") if sizing_health else None,
                    existing_allocation=existing_allocation, sector_allocation=sector_allocation,
                    preset=sizing_preset,
                )
            except ValueError as exc:
                st.error(str(exc))
        position_plan = st.session_state.get("position_plan")
        if position_plan and position_plan["ticker"] == sizing_ticker:
            with st.container(horizontal=True):
                st.metric("Suggested ceiling", f"{position_plan['suggested_shares']:,} shares", border=True)
                st.metric("Position value", f"${position_plan['position_value']:,.2f}", border=True)
                st.metric("Portfolio allocation", f"{position_plan['portfolio_allocation']:.2f}%", border=True)
                st.metric("Loss at invalidation", f"${position_plan['loss_at_invalidation']:,.2f}", border=True)
            st.info(position_plan["summary"])
            st.caption(
                f"Limiting factor: {position_plan['limiting_factor']} · risk budget "
                f"${position_plan['risk_budget']:,.2f} · adjusted company limit "
                f"{position_plan['adjusted_max_allocation']:.2f}%"
            )
            for modifier in position_plan["modifiers"]:
                st.warning(modifier)
            for warning in position_plan["warnings"]:
                st.error(warning)
            if st.button("Save sizing plan", icon=":material/save:", key="save-position-plan"):
                version_id = repository.save_position_plan(position_plan)
                st.success(f"Saved {sizing_ticker} sizing-plan version #{version_id}.")
            sizing_history = repository.position_plan_history(sizing_ticker)
            if sizing_history:
                with st.expander(f"Saved sizing plans ({len(sizing_history)})"):
                    st.dataframe([{
                        "Version": item["id"], "Saved": item["saved_at"], "Preset": item["preset"],
                        "Entry": item["entry_price"], "Invalidation": item["invalidation_price"],
                        "Shares": item["suggested_shares"], "Position value": item["position_value"],
                        "Allocation": item["portfolio_allocation"], "Modeled loss": item["loss_at_invalidation"],
                    } for item in sizing_history], hide_index=True, column_config={
                        "Entry": st.column_config.NumberColumn(format="$%.2f"),
                        "Invalidation": st.column_config.NumberColumn(format="$%.2f"),
                        "Position value": st.column_config.NumberColumn(format="$%.2f"),
                        "Allocation": st.column_config.NumberColumn(format="%.2f%%"),
                        "Modeled loss": st.column_config.NumberColumn(format="$%.2f"),
                    })
            st.caption(position_plan["disclosure"])
    else:
        st.info("Add a company to the watchlist or save a research report before creating a sizing plan.")

if active_page == "Accuracy":
    st.subheader("Decision accuracy")
    st.caption(
        "Track what happened after Atlas assigned a saved beginner label. Outcomes are measured against the S&P 500 "
        "and never rewrite the evidence that existed when the label was captured."
    )
    accuracy_horizon = st.segmented_control(
        "Outcome horizon", options=[7, 30, 90, 365], default=30,
        format_func=lambda value: f"{value} days" if value < 365 else "1 year",
        key="accuracy-horizon",
    ) or 30
    if st.button(
        "Capture latest labels and update outcomes", type="primary", icon=":material/query_stats:",
        key="capture-decision-labels",
    ):
        try:
            accuracy_symbols = repository.report_tickers()
            if not accuracy_symbols:
                raise ValueError("Run Research for at least one company before tracking label outcomes.")
            if quota_message := live_quota_message(provider, accuracy_symbols):
                raise ProviderError(quota_message)
            reports = repository.latest_reports(accuracy_symbols)
            health = repository.latest_financial_health()
            health_map = {item["ticker"]: item for item in health}
            trust_map = {
                ticker: assess_evidence_trust(
                    reports.get(ticker), health_map.get(ticker), active_configuration["freshness_days"],
                ) for ticker in accuracy_symbols
            }
            guidance = build_beginner_guidance(
                accuracy_symbols, reports, repository.latest_theses(), repository.alerts(100, unread_only=True),
                repository.portfolio_positions(), repository.latest_valuations(),
                active_configuration["freshness_days"], health, trust_map,
            )
            guidance_map = {item["Ticker"]: item for item in guidance}
            benchmark_history = provider.daily_history("SPY")
            benchmark_price = float(benchmark_history[-1]["close"])
            captured = 0
            for ticker, report in reports.items():
                snapshot = build_label_snapshot(
                    report, guidance_map[ticker], trust_map[ticker], benchmark_price,
                )
                captured += int(repository.save_decision_snapshot(snapshot) is not None)
            snapshots = repository.decision_snapshots()
            histories = {ticker: provider.daily_history(ticker) for ticker in sorted({item["ticker"] for item in snapshots})}
            updated = 0
            for snapshot in snapshots:
                evaluated = evaluate_snapshot(snapshot, histories[snapshot["ticker"]], benchmark_history)
                if evaluated.get("outcomes") != snapshot.get("outcomes"):
                    repository.update_decision_snapshot(snapshot["id"], evaluated)
                    updated += 1
            st.toast(
                f"Captured {captured} new label snapshot(s) and updated {updated} outcome record(s).",
                icon=":material/check_circle:",
            )
            st.rerun()
        except (ProviderError, RuntimeError, TypeError, ValueError) as exc:
            st.error(str(exc))

    accuracy_summary = summarize_accuracy(repository.decision_snapshots(), int(accuracy_horizon))
    with st.container(horizontal=True):
        st.metric("Model capacity", accuracy_summary["capacity"], border=True)
        st.metric("Saved snapshots", accuracy_summary["snapshots"], border=True)
        st.metric("Completed directional", accuracy_summary["completed_directional"], border=True)
        st.metric(
            "Observed win rate", "N/A" if accuracy_summary["win_rate"] is None else f"{accuracy_summary['win_rate']:.1f}%",
            border=True,
        )
        st.metric(
            "Average vs S&P 500",
            "N/A" if accuracy_summary["average_relative_return"] is None else f"{accuracy_summary['average_relative_return']:+.2f} pp",
            border=True,
        )
        st.metric(
            "Worst drawdown",
            "N/A" if accuracy_summary["worst_drawdown"] is None else f"{accuracy_summary['worst_drawdown']:.2f}%",
            border=True,
        )
    if accuracy_summary["capacity"] == "Insufficient":
        st.warning(
            "Accuracy evidence is still insufficient: at least 10 completed directional outcomes are required. "
            "Pending and informational labels do not count.",
            icon=":material/hourglass_top:",
        )
    else:
        st.info(accuracy_summary["summary"], icon=":material/analytics:")
    if accuracy_summary["rows"]:
        st.markdown("#### Label outcomes")
        st.dataframe(
            accuracy_summary["rows"], hide_index=True,
            column_config={
                "Ticker": st.column_config.TextColumn(pinned=True),
                "Captured": st.column_config.DatetimeColumn(format="MMM DD, YYYY"),
                "Start price": st.column_config.NumberColumn(format="$%.2f"),
                "Company return": st.column_config.NumberColumn(format="%+.2f%%"),
                "S&P 500 return": st.column_config.NumberColumn(format="%+.2f%%"),
                "Relative return": st.column_config.NumberColumn(format="%+.2f pp"),
                "Max drawdown": st.column_config.NumberColumn(format="%.2f%%"),
            },
        )
        if accuracy_summary["groups"]:
            st.markdown("#### Accuracy breakdown")
            st.dataframe(
                accuracy_summary["groups"], hide_index=True,
                column_config={
                    "Completed": st.column_config.NumberColumn(format="%d"),
                    "Win rate": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f%%"),
                    "Average relative return": st.column_config.NumberColumn(format="%+.2f pp"),
                },
            )
        if render_accuracy_report_pdf:
            st.download_button(
                "Download accuracy report PDF", data=render_accuracy_report_pdf(accuracy_summary),
                file_name=f"atlas-accuracy-{accuracy_horizon}-day.pdf", mime="application/pdf",
                key="download-accuracy-report", icon=":material/download:",
            )
    else:
        st.info("Capture the current saved labels to start the accuracy ledger. Outcomes will remain pending until each horizon elapses.")
    st.caption(accuracy_summary["disclosure"])

if active_page == "Financial health":
    st.subheader("SEC financial health")
    st.caption(
        "Review up to five annual 10-K periods from SEC EDGAR. Atlas makes no SEC request until you click Analyze; "
        "responses are cached for 24 hours."
    )
    monitor_watchlist = repository.watchlist()
    st.markdown("#### Filing monitor")
    st.caption(
        "Check the watchlist for new 10-K or 10-Q accessions. Atlas saves a new health version only when "
        "the newest filing changes and creates an alert for score moves of 10 points or more."
    )
    if st.button(
        "Refresh SEC watchlist", type="primary", key="refresh-sec-watchlist",
        disabled=not monitor_watchlist, icon=":material/refresh:",
    ):
        with st.status("Checking SEC filings…", expanded=True) as monitor_status:
            monitor_result = SecMonitorService(
                SecCompanyFactsProvider(provider_cache), repository,
            ).refresh(monitor_watchlist)
            st.session_state["sec_monitor_result"] = monitor_result
            if monitor_result["failed"]:
                monitor_status.update(label="SEC watchlist check completed with errors", state="error")
            else:
                monitor_status.update(label="SEC watchlist check complete", state="complete")
    monitor_result = st.session_state.get("sec_monitor_result")
    if monitor_result:
        with st.container(horizontal=True):
            st.metric("Companies checked", monitor_result["requested"], border=True)
            st.metric("New filing versions", monitor_result["saved"], border=True)
            st.metric("Unchanged", monitor_result["unchanged"], border=True)
            st.metric("Alerts created", monitor_result["alerts_created"], border=True)
            st.metric("Failed", monitor_result["failed"], border=True)
        st.dataframe(monitor_result["rows"], hide_index=True)
    latest_checks = repository.latest_sec_monitor_checks()
    if latest_checks:
        with st.expander(f"Latest monitor status ({len(latest_checks)} companies)"):
            st.dataframe(latest_checks, hide_index=True)
    elif not monitor_watchlist:
        st.info("Add companies to the watchlist before running the SEC filing monitor.")

    st.markdown("#### Single-company analysis")
    sec_ticker = st.text_input("U.S. company ticker", value="AAPL", key="sec-financial-health-ticker").strip().upper()
    if st.button("Analyze SEC filings", type="primary", key="analyze-sec-financial-health"):
        try:
            sec_snapshot = SecCompanyFactsProvider(provider_cache).company_facts(sec_ticker)
            result = analyze_financial_health(sec_snapshot)
            result["id"] = repository.save_financial_health(result)
            st.session_state["financial_health_result"] = result
            st.success(f"Saved {result['ticker']} SEC financial-health version #{result['id']}.")
        except (ProviderError, ValueError) as exc:
            st.error(str(exc))
    financial_health = st.session_state.get("financial_health_result")
    if financial_health:
        st.markdown(f"#### {financial_health['company']} ({financial_health['ticker']})")
        with st.container(horizontal=True):
            st.metric("Health posture", financial_health["posture"], border=True)
            st.metric("Trend score", f"{financial_health['score']}/100", border=True)
            st.metric("Metric coverage", f"{financial_health['coverage']}%", border=True)
            st.metric("CIK", financial_health["cik"], border=True)
        st.info(financial_health["summary"])
        latest_filing = financial_health.get("latest_filing") or {}
        if latest_filing:
            st.caption(
                f"Latest detected filing: {latest_filing.get('form')} filed {latest_filing.get('filed')} · "
                f"fiscal period {latest_filing.get('fiscal_period') or 'not reported'} · "
                f"accession {latest_filing.get('accession')}"
            )
        st.dataframe(financial_health["rows"], hide_index=True)
        if financial_health.get("quarterly_rows"):
            st.markdown("##### Quarterly filing trends")
            st.caption("Up to eight discrete SEC fiscal quarters. Missing fields remain blank rather than being treated as zero.")
            st.dataframe(financial_health["quarterly_rows"], hide_index=True)
        if financial_health["signals"]:
            st.markdown("##### Latest annual changes")
            st.dataframe(financial_health["signals"], hide_index=True)
        st.caption(
            f"Source: {financial_health['provider']} · {financial_health['cache_status']} · "
            f"retrieved {financial_health['retrieved_at']}"
        )
        st.caption(financial_health["disclosure"])
        health_history = repository.financial_health_history(financial_health["ticker"])
        if health_history:
            with st.expander(f"Saved SEC history ({len(health_history)})"):
                st.dataframe([
                    {"Version": item["id"], "Saved": item["saved_at"], "Score": item["score"],
                     "Posture": item["posture"], "Coverage": item["coverage"]}
                    for item in health_history
                ], hide_index=True)
    else:
        st.info("Set SEC_USER_AGENT in .env to an application name and contact email, then analyze a U.S. public company.")


if active_page == "Stress test":
    st.subheader("Portfolio stress testing")
    st.caption("Explore transparent sensitivity ranges using saved portfolio weights and Atlas research. Results are scenarios, not forecasts.")
    stress_positions = repository.portfolio_positions()
    if not stress_positions:
        st.info("Save portfolio allocations in the Portfolio tab before running a stress test.")
    else:
        stress_symbols = [item["ticker"] for item in stress_positions]
        stress_reports = repository.latest_reports(stress_symbols)
        missing_stress_reports = [symbol for symbol in stress_symbols if symbol not in stress_reports]
        if missing_stress_reports:
            st.warning("Missing saved research for: " + ", ".join(missing_stress_reports) + ". Refresh these holdings in Portfolio for complete coverage.")
        scenario_name = st.selectbox("Scenario", [*SCENARIOS, "Custom"], key="stress-scenario")
        custom_scenario = None
        if scenario_name == "Custom":
            with st.form("custom-stress-scenario", border=True):
                st.markdown("#### Custom assumptions")
                with st.container(horizontal=True):
                    market_shock = st.number_input("Broad market change (%)", -80.0, 80.0, -10.0, 1.0)
                    rate_change = st.number_input("Interest-rate change (basis points)", -500.0, 500.0, 0.0, 25.0)
                    inflation_change = st.number_input("Inflation change (percentage points)", -10.0, 10.0, 0.0, .25)
                    oil_change = st.number_input("Oil-price change (%)", -80.0, 200.0, 0.0, 5.0)
                sector_options = sorted({
                    str(report.company_metrics.get("sector") or "Unknown") for report in stress_reports.values()
                })
                stressed_sector = st.selectbox("Additional sector shock", ["None", *sector_options])
                sector_shock = st.number_input("Additional sector change (%)", -80.0, 80.0, 0.0, 1.0, disabled=stressed_sector == "None")
                run_stress = st.form_submit_button("Run custom stress test", type="primary", icon=":material/analytics:")
            custom_scenario = {
                "market_shock": market_shock, "rate_change_bps": rate_change,
                "inflation_change": inflation_change, "oil_change": oil_change,
                "sector_shocks": {} if stressed_sector == "None" else {stressed_sector: sector_shock},
            }
        else:
            assumptions = SCENARIOS[scenario_name]
            st.caption(
                f"Market {assumptions['market_shock']:+.0f}% · Rates {assumptions['rate_change_bps']:+.0f} bps · "
                f"Inflation {assumptions['inflation_change']:+.1f} pp · Oil {assumptions['oil_change']:+.0f}%"
            )
            run_stress = st.button("Run stress test", type="primary", icon=":material/analytics:", key="run-preset-stress")
        if run_stress:
            try:
                st.session_state["stress_result"] = analyze_stress_scenario(
                    stress_positions, stress_reports, scenario_name, custom_scenario,
                    repository.latest_theses(),
                )
            except ValueError as exc:
                st.error(str(exc))
        stress_result = st.session_state.get("stress_result")
        if stress_result:
            st.markdown(f"#### {stress_result['scenario']} results")
            with st.container(horizontal=True):
                st.metric("Portfolio sensitivity", f"{stress_result['estimated_impact']:+.1f}%", border=True)
                st.metric("Estimated range", f"{stress_result['lower_range']:+.1f}% to {stress_result['upper_range']:+.1f}%", border=True)
                st.metric("Stress posture", stress_result["posture"], border=True)
                st.metric("Research coverage", f"{stress_result['covered_weight']:.1f}%", border=True)
            st.info(stress_result["summary"])
            st.dataframe(
                stress_result["rows"], hide_index=True,
                column_config={
                    "Ticker": st.column_config.TextColumn(pinned=True),
                    "Portfolio weight": st.column_config.NumberColumn(format="%.1f%%"),
                    "Estimated impact": st.column_config.NumberColumn(format="%+.1f%%"),
                    "Lower range": st.column_config.NumberColumn(format="%+.1f%%"),
                    "Upper range": st.column_config.NumberColumn(format="%+.1f%%"),
                    "Portfolio contribution": st.column_config.NumberColumn(format="%+.2f pp"),
                },
            )
            if stress_result["sector_contributions"]:
                st.markdown("#### Sector contribution")
                st.bar_chart(
                    pd.DataFrame(stress_result["sector_contributions"]),
                    x="Sector", y="Portfolio impact", horizontal=True,
                )
            if stress_result["thesis_reviews"]:
                st.markdown("#### Thesis records to review")
                st.dataframe(stress_result["thesis_reviews"], hide_index=True)
            if stress_result["missing"]:
                st.warning("Unmodeled holdings: " + ", ".join(stress_result["missing"]))
            with st.expander("Scenario assumptions and methodology"):
                st.json(stress_result["assumptions"])
                st.write("Holding sensitivity combines the broad-market shock scaled by beta, sector-specific shocks, rate, inflation and oil sensitivities, and a modest risk-score amplification. The displayed range widens with estimated impact magnitude.")
            st.caption(stress_result["disclosure"])

if active_page == "Valuation lab":
    st.subheader("Valuation and margin-of-safety lab")
    st.caption("Test transparent bear, base, and bull assumptions against a saved Atlas report. No provider request is made from this tab.")
    valuation_tickers = repository.report_tickers()
    if not valuation_tickers:
        st.info("Run and save a Research report before building a valuation model.")
    else:
        valuation_ticker = st.selectbox("Company", valuation_tickers, key="valuation-company")
        valuation_report = repository.latest_reports([valuation_ticker]).get(valuation_ticker)
        if valuation_report is None:
            st.warning("The selected company does not have a readable saved report.")
        else:
            valuation_health = next((
                item for item in repository.latest_financial_health()
                if item["ticker"] == valuation_ticker
            ), None)
            defaults = suggested_assumptions(valuation_report, valuation_health)
            metrics = valuation_report.company_metrics
            st.caption(
                f"Using report #{valuation_report.report_id} · {valuation_report.provider} · "
                f"report price ${float(metrics.get('price') or 0):,.2f}"
            )
            if valuation_health:
                st.caption(
                    f"SEC health {valuation_health['score']}/100 ({valuation_health['posture']}) changed the "
                    f"suggested base P/E by {defaults['financial_health_adjustment']:+.1f}x. You can override it below."
                )
            with st.form("valuation-assumptions", border=True):
                st.markdown("#### Scenario assumptions")
                with st.container(horizontal=True):
                    bear_multiple = st.number_input("Bear P/E", 1.0, 100.0, defaults["bear_multiple"], 0.5)
                    base_multiple = st.number_input("Base P/E", 1.0, 100.0, defaults["base_multiple"], 0.5)
                    bull_multiple = st.number_input("Bull P/E", 1.0, 100.0, defaults["bull_multiple"], 0.5)
                    eps_adjustment = st.number_input("Forward EPS adjustment (%)", -50.0, 100.0, 0.0, 1.0)
                    desired_margin = st.number_input("Desired margin of safety (%)", 0.0, 60.0, 20.0, 1.0)
                run_valuation = st.form_submit_button("Run valuation", type="primary", icon=":material/calculate:")
            if run_valuation:
                try:
                    st.session_state["valuation_result"] = build_valuation(valuation_report, {
                        "bear_multiple": bear_multiple, "base_multiple": base_multiple,
                        "bull_multiple": bull_multiple, "eps_adjustment": eps_adjustment,
                        "desired_margin": desired_margin,
                    }, financial_health=valuation_health)
                except ValueError as exc:
                    st.error(str(exc))

            valuation = st.session_state.get("valuation_result")
            if valuation and valuation.get("ticker") == valuation_ticker:
                st.markdown("#### Scenario result")
                with st.container(horizontal=True):
                    st.metric("Report price", f"${valuation['current_price']:,.2f}", border=True)
                    st.metric("Bear value", f"${valuation['bear_value']:,.2f}", border=True)
                    st.metric("Base value", f"${valuation['base_value']:,.2f}", border=True)
                    st.metric("Bull value", f"${valuation['bull_value']:,.2f}", border=True)
                    st.metric("Margin of safety", f"{valuation['margin_of_safety']:+.1f}%", border=True)
                if valuation["status"] in {"Below bear value", "Within research entry range"}:
                    st.success(valuation["summary"])
                elif valuation["status"] == "Above base value":
                    st.warning(valuation["summary"])
                else:
                    st.info(valuation["summary"])
                st.dataframe(
                    valuation["scenarios"], hide_index=True,
                    column_config={
                        "Forward EPS": st.column_config.NumberColumn(format="$%.2f"),
                        "P/E multiple": st.column_config.NumberColumn(format="%.1fx"),
                        "Estimated value": st.column_config.NumberColumn(format="$%.2f"),
                        "Upside / downside": st.column_config.NumberColumn(format="%+.1f%%"),
                    },
                )
                with st.container(horizontal=True):
                    st.metric("Research entry range", f"${valuation['entry_low']:,.2f}–${valuation['entry_high']:,.2f}", border=True)
                    st.metric("Price-implied P/E", f"{valuation['implied_multiple']:.1f}x", border=True)
                    st.metric("Input coverage", f"{valuation['data_coverage']}%", border=True)

                latest_thesis = next((item for item in repository.latest_theses() if item["ticker"] == valuation_ticker), None)
                if latest_thesis:
                    st.markdown("#### Saved thesis comparison")
                    st.dataframe([{
                        "Source": "Valuation lab", "Entry low": valuation["entry_low"],
                        "Entry high": valuation["entry_high"], "Fair / base value": valuation["base_value"],
                    }, {
                        "Source": f"Thesis version {latest_thesis['id']}",
                        "Entry low": latest_thesis.get("entry_low"), "Entry high": latest_thesis.get("entry_high"),
                        "Fair / base value": latest_thesis.get("fair_value"),
                    }], hide_index=True, column_config={
                        "Entry low": st.column_config.NumberColumn(format="$%.2f"),
                        "Entry high": st.column_config.NumberColumn(format="$%.2f"),
                        "Fair / base value": st.column_config.NumberColumn(format="$%.2f"),
                    })
                else:
                    st.info("No saved thesis exists for comparison. You can create one in Thesis tracker.")

                with st.expander("Sensitivity and methodology"):
                    st.dataframe(
                        valuation["sensitivity"], hide_index=True,
                        column_config={
                            "Estimated value": st.column_config.NumberColumn(format="$%.2f"),
                            "Upside / downside": st.column_config.NumberColumn(format="%+.1f%%"),
                        },
                    )
                    st.write(f"Forward EPS source: {valuation['eps_source']}.")
                    st.write("Estimated value equals adjusted forward EPS multiplied by the selected scenario P/E. The research entry ceiling applies the selected margin of safety to base value.")
                if st.button("Save valuation version", type="primary", icon=":material/save:", key="save-valuation-version"):
                    version_id = repository.save_valuation(valuation)
                    st.success(f"Saved {valuation_ticker} valuation version #{version_id}.")
                st.caption(valuation["disclosure"])

            valuation_history = repository.valuation_history(valuation_ticker)
            if valuation_history:
                with st.expander(f"Saved valuation history ({len(valuation_history)})"):
                    st.dataframe([{
                        "Version": item["id"], "Saved": item["saved_at"], "Status": item["status"],
                        "Report price": item["current_price"], "Base value": item["base_value"],
                        "Margin of safety": item["margin_of_safety"],
                    } for item in valuation_history], hide_index=True, column_config={
                        "Saved": st.column_config.DatetimeColumn(format="MMM DD, YYYY, h:mm a"),
                        "Report price": st.column_config.NumberColumn(format="$%.2f"),
                        "Base value": st.column_config.NumberColumn(format="$%.2f"),
                        "Margin of safety": st.column_config.NumberColumn(format="%+.1f%%"),
                    })

if active_page == "Research":
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
            if quota_message := live_quota_message(provider, [ticker]):
                raise ProviderError(quota_message)
            with st.spinner("Building evidence-based committee assessment…"):
                st.session_state["report"] = analysis.analyze(ticker, strategy_weights)
        except (RuntimeError, ValueError) as exc:
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

if active_page == "Backtest":
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
        except (RuntimeError, ValueError) as exc:
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

if active_page == "Compare":
    st.subheader("Compare companies")
    comparison_weights = PRESETS[active_configuration["committee_preset"]]
    comparison_normalized = normalize_weights(comparison_weights)
    st.caption(
        f"Comparisons use the saved {active_configuration['committee_preset']} committee preset. "
        "Change it in Settings when you want a different comparison lens."
    )
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
    comparison_ready = 2 <= len(selected_tickers) <= 4 and bool(comparison_normalized)
    if st.button("Run comparison", type="primary", disabled=not comparison_ready):
        try:
            with st.spinner("Building comparable research snapshots…"):
                st.session_state["comparison"] = ComparisonService(analysis, repository).compare(
                    selected_tickers, comparison_weights
                )
        except (RuntimeError, ValueError) as exc:
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

if active_page == "Changes":
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

if active_page == "Thesis tracker":
    st.subheader("Thesis tracker and decision journal")
    st.caption("Record your reasoning, thresholds, and review schedule. Atlas evaluates them against the newest saved report; it does not place trades.")
    saved_theses = repository.latest_theses()
    latest_by_ticker = repository.latest_reports([item["ticker"] for item in saved_theses])
    thesis_health_by_ticker = {
        item["ticker"]: item for item in repository.latest_financial_health()
    }
    thesis_rows = []
    for saved_thesis in saved_theses:
        evaluation = evaluate_thesis(
            saved_thesis, latest_by_ticker.get(saved_thesis["ticker"]),
            financial_health=thesis_health_by_ticker.get(saved_thesis["ticker"]),
        )
        thesis_rows.append({
            "Ticker": saved_thesis["ticker"], "Stance": saved_thesis["stance"],
            "Confidence": saved_thesis["confidence"], "Status": evaluation["status"],
            "Latest price": evaluation["price"], "Review date": saved_thesis.get("review_date") or None,
            "Version": saved_thesis["id"],
        })
    if thesis_rows:
        invalidated_count = sum(row["Status"] == "Invalidated" for row in thesis_rows)
        review_count = sum(row["Status"] == "Review due" for row in thesis_rows)
        opportunity_count = sum(row["Status"] == "Opportunity" for row in thesis_rows)
        with st.container(horizontal=True):
            st.metric("Active thesis records", len(thesis_rows), border=True)
            st.metric("Opportunities", opportunity_count, border=True)
            st.metric("Reviews due", review_count, border=True)
            st.metric("Invalidated", invalidated_count, border=True)
        st.dataframe(
            thesis_rows, hide_index=True,
            column_config={
                "Latest price": st.column_config.NumberColumn(format="$%.2f"),
                "Review date": st.column_config.DateColumn(format="MMM DD, YYYY"),
            },
        )
    else:
        st.info("No thesis records have been saved yet. Create the first decision record below.")

    available_tickers = sorted(set(
        repository.report_tickers() + repository.watchlist()
        + [position["ticker"] for position in repository.portfolio_positions()]
    ))
    if available_tickers:
        thesis_ticker = st.selectbox("Company", available_tickers, key="thesis-company")
        existing_history = repository.thesis_history(thesis_ticker)
        existing = existing_history[0] if existing_history else {}
        latest_report = repository.latest_reports([thesis_ticker]).get(thesis_ticker)
        latest_thesis_health = thesis_health_by_ticker.get(thesis_ticker)
        if latest_report:
            st.caption(f"The latest evaluation will use report #{latest_report.report_id} from {latest_report.created_at}.")
            next_earnings = next((
                event for event in latest_report.catalyst_calendar.get("events", [])
                if event.get("category") == "Earnings" and event.get("source_live") is True
                and not event.get("source_stale")
            ), None)
            if next_earnings:
                st.info(
                    f"Next estimated earnings date: {next_earnings['date']} "
                    f"({next_earnings.get('days_until', '—')} days) · {next_earnings.get('source', 'Unknown source')}"
                )
        else:
            st.warning("This company has no saved report yet. You can save the thesis now and run Research later.")

        with st.form("thesis-editor", border=True):
            st.markdown("#### Decision record")
            stance = st.segmented_control(
                "Current stance", STANCES, default=existing.get("stance", "Watch"), key="thesis-stance"
            )
            confidence = st.segmented_control(
                "Confidence", CONFIDENCE_LEVELS, default=existing.get("confidence", "Medium"), key="thesis-confidence"
            )
            with st.container(horizontal=True):
                entry_low = st.number_input("Entry range low", min_value=0.0, value=existing.get("entry_low"), step=1.0)
                entry_high = st.number_input("Entry range high", min_value=0.0, value=existing.get("entry_high"), step=1.0)
                fair_value = st.number_input("Fair-value estimate", min_value=0.0, value=existing.get("fair_value"), step=1.0)
            with st.container(horizontal=True):
                max_risk = st.number_input("Invalidate at risk score", min_value=0.0, max_value=100.0, value=float(existing.get("max_risk_score", 70)), step=1.0)
                min_readiness = st.number_input("Minimum entry readiness", min_value=0.0, max_value=100.0, value=float(existing.get("min_readiness_score", 50)), step=1.0)
                saved_review = existing.get("review_date")
                review_value = date.fromisoformat(saved_review) if saved_review else date.today() + timedelta(days=30)
                review_date = st.date_input("Review date", value=review_value)
            supporting_reasons = st.text_area("Reasons supporting the thesis (one per line)", value="\n".join(existing.get("supporting_reasons", [])))
            risks = st.text_area("Known risks (one per line)", value="\n".join(existing.get("risks", [])))
            invalidation_conditions = st.text_area("Qualitative invalidation conditions (one per line)", value="\n".join(existing.get("invalidation_conditions", [])))
            catalysts = st.text_area("Expected catalysts (one per line)", value="\n".join(existing.get("catalysts", [])))
            notes = st.text_area("Decision notes", value=existing.get("notes", ""))
            save_thesis = st.form_submit_button("Save new thesis version", type="primary", icon=":material/save:")
        if save_thesis:
            try:
                thesis = validate_thesis({
                    "ticker": thesis_ticker, "stance": stance, "confidence": confidence,
                    "entry_low": entry_low, "entry_high": entry_high, "fair_value": fair_value,
                    "max_risk_score": max_risk, "min_readiness_score": min_readiness,
                    "review_date": review_date.isoformat(), "supporting_reasons": supporting_reasons,
                    "risks": risks, "invalidation_conditions": invalidation_conditions,
                    "catalysts": catalysts, "notes": notes,
                })
                repository.save_thesis(thesis)
                st.success(f"Saved a new {thesis_ticker} thesis version.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

        if existing:
            evaluation = evaluate_thesis(
                existing, latest_report, financial_health=latest_thesis_health,
            )
            st.markdown("#### Latest thesis check")
            if evaluation["status"] == "Invalidated":
                st.error(evaluation["summary"])
            elif evaluation["status"] in {"Review due", "Needs report"}:
                st.warning(evaluation["summary"])
            elif evaluation["status"] == "Opportunity":
                st.success(evaluation["summary"])
            else:
                st.info(evaluation["summary"])
            for flag in evaluation["flags"]:
                st.write(f"- **{flag['factor']} ({flag['severity']}):** {flag['message']}")
            with st.expander(f"Version history ({len(existing_history)})"):
                st.dataframe([
                    {"Version": item["id"], "Saved": item["created_at"], "Stance": item["stance"],
                     "Confidence": item["confidence"], "Review date": item.get("review_date")}
                    for item in existing_history
                ], hide_index=True)
    else:
        st.warning("Add a company to the watchlist or run a research report before creating a thesis.")

if active_page == "Alerts":
    scheduler = ScheduledResearchService(
        analysis, repository, provider, macro_provider, event_provider, calendar_provider,
    )

    @st.fragment(run_every="60s")
    def scheduled_research_monitor():
        scheduler_status = scheduler.status()
        if scheduler_status["due"]:
            with st.status("Scheduled research refresh is running…", expanded=False) as run_status:
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
            with st.status("Refreshing scheduled research…", expanded=True) as manual_status:
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

if active_page == "Provider health":
    st.subheader("Provider health")
    st.caption(
        "A read-only view of Atlas data sources, saved connection tests, cache telemetry, quota, and background jobs. "
        "Opening this page makes no provider requests."
    )
    provider_environment = environment_readiness()
    provider_health = build_provider_health(
        provider_environment, provider.status(), macro_provider.status(), calendar_provider.name,
        repository.configuration("live_market_readiness"),
        repository.configuration("live_macro_readiness"), discovery_scheduler.status(),
        bool(os.getenv("SEC_USER_AGENT") and "@" in os.getenv("SEC_USER_AGENT", "")),
        provider_cache.count(),
    )
    if provider_health["overall"] == "Ready":
        st.success(provider_health["summary"], icon=":material/check_circle:")
    elif provider_health["overall"] == "Degraded":
        st.warning(provider_health["summary"], icon=":material/warning:")
    else:
        st.error(provider_health["summary"], icon=":material/error:")
    with st.container(horizontal=True):
        st.metric("Overall status", provider_health["overall"], border=True)
        st.metric("Ready systems", provider_health["ready"], border=True)
        st.metric("Degraded systems", provider_health["degraded"], border=True)
        st.metric("Action required", provider_health["action_required"], border=True)
        st.metric("Cached responses", provider_health["cache_entries"], border=True)
    if provider_health["quota_remaining"] is not None:
        with st.container(horizontal=True):
            st.metric("Alpha requests used", provider_health["quota_used"], border=True)
            st.metric("Alpha requests available", provider_health["quota_remaining"], border=True)
            st.metric("Atlas usable limit", provider_health["quota_limit"], border=True)
            st.metric("Quota reset", provider_health["quota_reset"][:16].replace("T", " ") + " UTC", border=True)
    st.markdown("#### Data systems")
    st.dataframe(
        provider_health["rows"], hide_index=True,
        column_config={
            "Component": st.column_config.TextColumn(pinned=True),
            "Cache age": st.column_config.NumberColumn(format="%d seconds"),
        },
    )
    if provider_health["failures"]:
        st.markdown("#### Recent blockers")
        st.dataframe(
            provider_health["failures"], hide_index=True,
            column_config={"Observed": st.column_config.DatetimeColumn(format="MMM DD, YYYY, h:mm a")},
        )
    else:
        st.info("No failed saved readiness checks or Discovery job errors are recorded.")
    if st.button("Refresh local telemetry", icon=":material/refresh:", key="refresh-provider-health"):
        st.rerun()
    st.caption(
        "Use System → Data readiness to make explicit live connection tests. Those tests may consume provider requests; "
        "this health page does not."
    )

if active_page == "Data readiness":
    st.subheader("Live data readiness")
    st.caption("Run connection and coverage checks before changing providers. API keys are detected but never displayed or stored in reports.")
    environment_status = environment_readiness()
    with st.container(horizontal=True):
        st.metric("Current market mode", environment_status["market_mode"].replace("_", " ").title(), border=True)
        st.metric("Current macro mode", environment_status["macro_mode"].replace("_", " ").title(), border=True)
        st.metric("Alpha Vantage key", "Detected" if environment_status["alpha_vantage_key"] else "Missing", border=True)
        st.metric("Tiingo key", "Detected" if environment_status["tiingo_key"] else "Missing", border=True)
        st.metric("FRED key", "Detected" if environment_status["fred_key"] else "Missing", border=True)
        st.metric("Provider cache entries", provider_cache.count(), border=True)
    configured_market_status = provider.status()
    if configured_market_status.get("quota_daily_limit") is not None:
        with st.container(horizontal=True):
            st.metric("Alpha Vantage daily limit", configured_market_status["quota_daily_limit"], border=True)
            st.metric("Atlas reserve", configured_market_status["quota_reserve"], border=True)
            st.metric("Used today", configured_market_status["quota_used"], border=True)
            st.metric("Available to Atlas", configured_market_status["quota_remaining"], border=True)

    readiness_ticker = st.text_input("Ticker for readiness tests", value="AAPL", key="readiness-test-ticker").strip().upper()
    readiness_actions = st.container(horizontal=True)
    with readiness_actions:
        run_demo_readiness = st.button("Validate demo providers", key="validate-demo-providers")
        run_live_market = st.button(
            "Test Alpha Vantage", key="test-alpha-vantage-readiness",
            disabled=not environment_status["alpha_vantage_key"], type="primary",
        )
        run_hybrid_market = st.button(
            "Test Tiingo hybrid", key="test-tiingo-hybrid-readiness",
            disabled=not (environment_status["alpha_vantage_key"] and environment_status["tiingo_key"]),
        )
        run_live_macro = st.button(
            "Test FRED", key="test-fred-readiness", disabled=not environment_status["fred_key"],
        )
    st.caption("A full Alpha Vantage test can use up to six requests. The hybrid test uses about three Alpha Vantage requests plus Tiingo history calls when uncached.")

    if run_demo_readiness:
        with st.status("Validating demo providers…", expanded=True) as demo_status:
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
            with st.status("Testing Alpha Vantage endpoints…", expanded=True) as market_status:
                live_market_provider = CachedMarketDataProvider(
                    AlphaVantageProvider(usage_store=provider_cache), provider_cache
                )
                live_market_result = test_market_provider(
                    live_market_provider, readiness_ticker, active_configuration["technical"]["long_window"],
                )
                repository.save_configuration("live_market_readiness", live_market_result)
                final_state = "complete" if live_market_result["status"] == "Ready" else "error"
                market_status.update(label=f"Alpha Vantage test: {live_market_result['status']}", state=final_state)
            st.rerun()
        except RuntimeError as exc:
            st.error(f"Alpha Vantage readiness test could not start: {exc}")
    if run_hybrid_market:
        try:
            with st.status("Testing Tiingo and Alpha Vantage…", expanded=True) as hybrid_status:
                hybrid_provider = CachedMarketDataProvider(
                    HybridMarketDataProvider(
                        AlphaVantageProvider(usage_store=provider_cache), TiingoProvider()
                    ),
                    provider_cache,
                )
                live_market_result = test_market_provider(
                    hybrid_provider, readiness_ticker, active_configuration["technical"]["long_window"],
                )
                repository.save_configuration("live_market_readiness", live_market_result)
                final_state = "complete" if live_market_result["status"] == "Ready" else "error"
                hybrid_status.update(label=f"Tiingo hybrid test: {live_market_result['status']}", state=final_state)
            st.rerun()
        except RuntimeError as exc:
            st.error(f"Tiingo hybrid readiness test could not start: {exc}")
    if run_live_macro:
        try:
            with st.status("Testing FRED economic series…", expanded=True) as macro_status:
                live_macro_provider = CachedEconomicDataProvider(FredProvider(), provider_cache)
                live_macro_result = test_macro_provider(live_macro_provider)
                repository.save_configuration("live_macro_readiness", live_macro_result)
                final_state = "complete" if live_macro_result["status"] == "Ready" else "error"
                macro_status.update(label=f"FRED test: {live_macro_result['status']}", state=final_state)
            st.rerun()
        except RuntimeError as exc:
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
        st.markdown(f"#### {live_market_result.get('provider', 'Market provider')}: {live_market_result['status']}")
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
            if status.get("quota_remaining") is not None:
                st.caption(
                    f"Daily Alpha Vantage budget: {status.get('quota_used', 0)} used, "
                    f"{status['quota_remaining']} available, {status.get('quota_reserve', 0)} reserved."
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
            "ATLAS_DATA_PROVIDER=hybrid\n"
            "ALPHA_VANTAGE_API_KEY=your_key_here\n"
            "TIINGO_API_KEY=your_key_here\n"
            "ATLAS_MACRO_PROVIDER=fred\n"
            "ATLAS_CALENDAR_PROVIDER=fred\n"
            "FRED_API_KEY=your_key_here",
            language="text",
        )
        st.write("Keep these values in your local .env file, never in source code. Restart Atlas after changing provider modes.")
        st.write("Hybrid mode uses Tiingo history for the 200-day analyzer and Alpha Vantage for fundamentals and news.")

if active_page == "Settings":
    st.subheader("Settings and calibration")
    st.caption("Settings are versioned and embedded in each new report. API credentials remain environment-controlled.")
    with st.container(horizontal=True):
        st.metric("Configuration version", active_configuration["version"], border=True)
        st.metric("Active profile", active_configuration["profile"], border=True)
        st.metric("Market provider", provider.name, border=True)
        st.metric("Macro provider", macro_provider.name, border=True)
        st.metric("Calendar provider", calendar_provider.name, border=True)

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

    st.divider()
    st.subheader("Daily Discovery monitor")
    st.caption(
        "Configure the background market scan. The worker uses the provider cache, compares each result with the "
        "prior scan, and creates alerts only for meaningful changes. Times are U.S. Eastern."
    )
    discovery_schedule = discovery_scheduler.configuration()
    with st.form("discovery-scheduler-settings"):
        schedule_enabled = st.toggle("Enable daily Discovery scans", value=discovery_schedule["enabled"])
        schedule_row = st.container(horizontal=True)
        with schedule_row:
            schedule_time = st.time_input(
                "Run after market data updates", value=time(discovery_schedule["hour_et"], discovery_schedule["minute_et"]),
            )
            schedule_limit = st.number_input(
                "Candidates per scan", min_value=1, max_value=8,
                value=int(discovery_schedule["candidate_limit"]), step=1,
            )
            schedule_weekdays = st.toggle(
                "Weekdays only", value=discovery_schedule["weekdays_only"],
            )
        save_discovery_schedule = st.form_submit_button("Save Discovery schedule", type="primary")
    if save_discovery_schedule:
        try:
            discovery_scheduler.save_configuration({
                "enabled": schedule_enabled, "hour_et": schedule_time.hour,
                "minute_et": schedule_time.minute, "weekdays_only": schedule_weekdays,
                "candidate_limit": schedule_limit,
            })
            st.success("Daily Discovery schedule saved.")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
    schedule_state = discovery_scheduler.status()
    schedule_last = schedule_state["last_run"]
    with st.container(horizontal=True):
        if st.button("Run Discovery job now", icon=":material/play_arrow:", key="run-discovery-job-now"):
            with st.status("Running the scheduled Discovery workflow…", expanded=True) as job_status:
                job_result = discovery_scheduler.run("Manual", force=True)
                if job_result["status"] == "Complete":
                    job_status.update(label="Discovery job completed", state="complete")
                else:
                    job_status.write("\n".join(job_result.get("errors", [])))
                    job_status.update(label=f"Discovery job {job_result['status'].lower()}", state="error")
            st.rerun()
    with st.container(horizontal=True):
        st.metric("Status", "Enabled" if schedule_state["configuration"]["enabled"] else "Paused", border=True)
        st.metric("Last result", schedule_last["status"] if schedule_last else "Never run", border=True)
        st.metric("Candidates", schedule_last["candidates"] if schedule_last else 0, border=True)
        st.metric("Alerts", schedule_last["alerts_created"] if schedule_last else 0, border=True)
    if schedule_state["next_run"]:
        st.caption("Next due: " + schedule_state["next_run"][:16].replace("T", " ") + " UTC")
    discovery_job_runs = repository.discovery_scheduler_runs()
    if discovery_job_runs:
        with st.expander("Discovery job history"):
            st.dataframe([{
                "Run": row["id"], "Started": row["started_at"], "Completed": row["completed_at"],
                "Status": row["status"], "Trigger": row["trigger"], "Candidates": row["candidates"],
                "Alerts": row["alerts_created"], "Errors": "; ".join(row["errors"]),
            } for row in discovery_job_runs], hide_index=True)

if active_page == "Report history":
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
            "Daily quota left": str(status.get("quota_remaining", "-")),
            "Demo fallbacks": status.get("demo_fallbacks", 0),
        })
    st.dataframe(status_rows, hide_index=True, width="stretch")
    if st.button("Refresh provider cache"):
        provider_cache.clear()
        provider.reset_status()
        macro_provider.reset_status()
        st.success("Provider cache cleared. The next analysis will request fresh data.")
        st.rerun()
