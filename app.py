from __future__ import annotations

import os

import streamlit as st
from dotenv import load_dotenv

from core.providers.demo_provider import DemoProvider
from core.providers.market_provider import AlphaVantageProvider, ProviderError
from core.providers.economic_provider import DemoEconomicProvider, FredProvider
from core.services.analysis_service import AnalysisService
from core.services.report_repository import ReportRepository


load_dotenv()
st.set_page_config(page_title="Project Atlas", page_icon="🧭", layout="wide")


@st.cache_resource
def services():
    provider_name = os.getenv("ATLAS_DATA_PROVIDER", "demo").lower()
    provider = AlphaVantageProvider() if provider_name == "alpha_vantage" else DemoProvider()
    macro_provider_name = os.getenv("ATLAS_MACRO_PROVIDER", "demo").lower()
    macro_provider = FredProvider() if macro_provider_name == "fred" else DemoEconomicProvider()
    repository = ReportRepository(os.getenv("ATLAS_DATABASE_PATH", "data/atlas.db"))
    return provider, macro_provider, repository, AnalysisService(provider, repository, macro_provider)


st.title("Project Atlas")
st.caption("Analysis-only investment research — no trading or brokerage connectivity")

try:
    provider, macro_provider, repository, analysis = services()
except ProviderError as exc:
    st.error(f"Data provider configuration error: {exc}")
    st.info("Set ATLAS_DATA_PROVIDER=demo to use Atlas without a live-data API key.")
    st.stop()

if provider.name.startswith("Demo"):
    st.warning("Demo mode is active. Figures are illustrative and are not live market data.")
if macro_provider.name.startswith("Demo"):
    st.warning("Demo macro mode is active. Economic figures are illustrative and are not live.")

dashboard, research_tab, history_tab = st.tabs(["Dashboard", "Research", "Report history"])

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
    if st.button("Run six-strategy analysis", type="primary", disabled=not ticker):
        try:
            with st.spinner("Building evidence-based committee assessment…"):
                st.session_state["report"] = analysis.analyze(ticker)
        except (ProviderError, ValueError) as exc:
            st.error(str(exc))
        except Exception as exc:
            st.error(f"Analysis failed: {exc}")
    report = st.session_state.get("report")
    if report:
        performance = getattr(report, "performance", {})
        performance_history = getattr(report, "performance_history", [])
        macro = getattr(report, "macro", {})
        st.subheader(f"{report.company} ({report.ticker})")
        a, b, c = st.columns(3)
        a.metric("Committee vote", report.committee_vote.title())
        b.metric("Confidence", f"{report.committee_confidence}%")
        c.metric("Data as of", report.data_as_of[:19].replace("T", " ") + " UTC")
        st.write(report.executive_summary)
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
