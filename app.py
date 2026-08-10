from __future__ import annotations

import importlib
import inspect
import os

import streamlit as st
from dotenv import load_dotenv

from core.providers.demo_provider import DemoProvider
from core.providers.market_provider import AlphaVantageProvider, ProviderError
from core.providers.economic_provider import DemoEconomicProvider, FredProvider
import core.models.research as research_model_module
import core.services.committee_service as committee_service_module
import core.services.analysis_service as analysis_service_module
import core.services.comparison_service as comparison_service_module
import core.services.report_repository as report_repository_module


# Streamlit can preserve imported project modules across app-only hot reloads.
modules_reloaded = False
if "committee_score" not in research_model_module.ResearchReport.__dataclass_fields__:
    research_model_module = importlib.reload(research_model_module)
    modules_reloaded = True
if not hasattr(committee_service_module, "score_contributions"):
    committee_service_module = importlib.reload(committee_service_module)
    modules_reloaded = True
if modules_reloaded or not hasattr(report_repository_module.ReportRepository, "comparison_history"):
    report_repository_module = importlib.reload(report_repository_module)
    modules_reloaded = True
ReportRepository = report_repository_module.ReportRepository
if modules_reloaded or "macro_snapshot" not in inspect.signature(analysis_service_module.AnalysisService.analyze).parameters:
    analysis_service_module = importlib.reload(analysis_service_module)
    modules_reloaded = True
AnalysisService = analysis_service_module.AnalysisService
if modules_reloaded or getattr(comparison_service_module, "COMPARISON_SERVICE_VERSION", 0) < 2:
    comparison_service_module = importlib.reload(comparison_service_module)
ComparisonService = comparison_service_module.ComparisonService
PRESETS = committee_service_module.PRESETS
STRATEGIES = committee_service_module.STRATEGIES
normalize_weights = committee_service_module.normalize_weights


load_dotenv()
st.set_page_config(page_title="Project Atlas", page_icon="🧭", layout="wide")
SERVICE_CACHE_VERSION = "comparison-schema-v3"


@st.cache_resource
def services(cache_version: str):
    # Changing this key refreshes long-lived objects after service or database upgrades.
    _ = cache_version
    provider_name = os.getenv("ATLAS_DATA_PROVIDER", "demo").lower()
    provider = AlphaVantageProvider() if provider_name == "alpha_vantage" else DemoProvider()
    macro_provider_name = os.getenv("ATLAS_MACRO_PROVIDER", "demo").lower()
    macro_provider = FredProvider() if macro_provider_name == "fred" else DemoEconomicProvider()
    repository = ReportRepository(os.getenv("ATLAS_DATABASE_PATH", "data/atlas.db"))
    return provider, macro_provider, repository, AnalysisService(provider, repository, macro_provider)


st.title("Project Atlas")
st.caption("Analysis-only investment research — no trading or brokerage connectivity")

try:
    provider, macro_provider, repository, analysis = services(SERVICE_CACHE_VERSION)
except ProviderError as exc:
    st.error(f"Data provider configuration error: {exc}")
    st.info("Set ATLAS_DATA_PROVIDER=demo to use Atlas without a live-data API key.")
    st.stop()

if provider.name.startswith("Demo"):
    st.warning("Demo mode is active. Figures are illustrative and are not live market data.")
if macro_provider.name.startswith("Demo"):
    st.warning("Demo macro mode is active. Economic figures are illustrative and are not live.")
else:
    st.info("This product uses the FRED® API but is not endorsed or certified by the Federal Reserve Bank of St. Louis.")

dashboard, research_tab, compare_tab, history_tab = st.tabs(["Dashboard", "Research", "Compare", "Report history"])

with dashboard:
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

with research_tab:
    ticker = st.text_input("Ticker to analyze", value=(repository.watchlist() or ["AAPL"])[0]).upper().strip()
    with st.expander("Committee configuration"):
        preset_name = st.selectbox("Start from preset", list(PRESETS), index=0)
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
        contributions = getattr(report, "committee_contributions", [])
        st.subheader(f"{report.company} ({report.ticker})")
        a, b, c = st.columns(3)
        a.metric("Committee vote", report.committee_vote.title())
        b.metric("Confidence", f"{report.committee_confidence}%")
        c.metric("Data as of", report.data_as_of[:19].replace("T", " ") + " UTC")
        st.write(report.executive_summary)
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
                use_container_width=True,
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
                use_container_width=True,
            )
            st.caption(
                f"Annualized volatility: {performance['annualized_volatility']:.1f}% · "
                f"{performance['observations']} monthly observations · Growth indexed to 100"
            )
        elif not hasattr(report, "performance"):
            st.info("This report predates historical performance. Run the analysis again to add the comparison.")
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
        for warning in comparison["warnings"]:
            st.warning(warning)
        st.dataframe(comparison["summary"], hide_index=True, use_container_width=True)
        st.markdown("#### Normalized performance")
        st.line_chart(
            comparison["performance_history"],
            x="date",
            y=comparison["tickers"],
        )
        st.caption("Each company is indexed to 100 at the beginning of the comparison period.")
        st.markdown("#### Strategy-by-strategy")
        st.dataframe(comparison["strategy_table"], hide_index=True, use_container_width=True)
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
                st.dataframe(saved["summary"], hide_index=True, use_container_width=True)

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
