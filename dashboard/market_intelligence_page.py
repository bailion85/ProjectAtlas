from __future__ import annotations

from datetime import date

import streamlit as st

from core.providers.x_provider import XFeedProvider
from core.services.market_intelligence_service import (
    ARGUMENT_TYPES, STANCES, build_market_intelligence, validate_commentary, validate_source,
)
from core.services.feed_intelligence_service import (
    build_entity_catalog, build_feed_analytics,
)

from core.services.x_feed_service import sync_x_sources
from core.services.trending_intelligence_service import build_trending_intelligence
MARKET_INTELLIGENCE_PAGE_VERSION = 5



def render_market_intelligence_snapshot(repository, ticker: str, sector: str | None = None) -> None:
    state = repository.configuration("market_intelligence") or {"sources": [], "commentary": []}
    result = build_market_intelligence(
        ticker, state.get("sources", []), state.get("commentary", []), sector=sector,
    )
    with st.container(border=True):
        st.markdown("##### Market Intelligence specialist")
        if not result["items"]:
            st.info("No current curated analyst commentary is saved for this company.")
            return
        with st.container(horizontal=True):
            st.metric("Advisory vote", result["vote"], border=True)
            st.metric("Confidence", f"{result['confidence']}%", border=True)
            st.metric("Analyst signal", f"{result['signal_score']}/100", border=True)
            st.metric("Influence signal", f"{result['influence_score']}/100", border=True)
        st.caption(
            result["summary"] + " This specialist is not yet included in the six-strategy committee vote."
        )


def render_market_intelligence_page(repository, provider_cache) -> None:
    st.subheader("Market intelligence")
    st.caption(
        "Turn curated analyst commentary into an advisory specialist vote. "
        "Predictive credibility and market-moving influence remain separate signals."
    )
    state = repository.configuration("market_intelligence") or {"sources": [], "commentary": []}
    sources, commentary = state.get("sources", []), state.get("commentary", [])
    raw_posts = state.get("raw_posts", [])
    discovery = repository.latest_discovery_run() or {}
    universe = list(dict.fromkeys(
        repository.watchlist() + repository.report_tickers()
        + [str(row.get("Ticker", "")).upper() for row in discovery.get("rows", []) if row.get("Ticker")]
    ))
    reports = repository.latest_reports(universe)
    catalog = build_entity_catalog(repository.watchlist(), discovery, reports)
    analytics = build_feed_analytics(sources, raw_posts, commentary, catalog, reports)
    last_sync = state.get("last_x_sync") or {}
    if last_sync.get("errors"):
        st.error(
            "The last X refresh failed: "
            + "; ".join(str(item.get("Error", "Unknown X error")) for item in last_sync["errors"])
        )
        st.caption("Atlas cannot produce feed analytics until X returns posts. Check the X developer credit balance.")
    captured = [item.get("ticker") for item in commentary if item.get("ticker")]
    tickers = list(dict.fromkeys(universe + captured)) or ["AAPL"]
    trending = build_trending_intelligence(sources, commentary)
    st.markdown("#### What's hot in your feeds")
    with st.container(horizontal=True):
        st.metric("Trending stocks", trending["tickers"], border=True)
        st.metric("Recent mentions", trending["mentions"], border=True)
        st.metric("Independent analysts", trending["analysts"], border=True)
        st.metric("Most discussed", trending["top_ticker"] or "No signal", border=True)
    if trending["rows"]:
        st.dataframe(
            trending["rows"], hide_index=True,
            column_config={
                "Ticker": st.column_config.TextColumn(pinned=True),
                "Attention score": st.column_config.ProgressColumn(min_value=0, max_value=100),
                "Sentiment score": st.column_config.ProgressColumn(min_value=0, max_value=100),
                "Average influence": st.column_config.ProgressColumn(min_value=0, max_value=100),
            },
        )
        st.caption(
            "Attention ranks what is hot; sentiment shows direction. A highly discussed bearish stock "
            "is hot, but it is not a bullish recommendation."
        )
        discovered = [row["Ticker"] for row in trending["rows"]]
        tickers = discovered + [symbol for symbol in tickers if symbol not in discovered]
    else:
        st.info(
            "Refresh the curated X feeds to discover trending stocks. Atlas ranks explicit cashtags "
            "found during the last seven days."
        )
    st.markdown("#### Market Intelligence agent decisions")
    with st.container(horizontal=True):
        st.metric("Posts retained", analytics["posts"], border=True)
        st.metric("Matched posts", analytics["matched_posts"], border=True)
        st.metric("Unmatched posts", analytics["unmatched_posts"], border=True)
        st.metric("Universe coverage", f"{analytics['coverage']}%", border=True)
    actionable = [row for row in analytics["decisions"] if row["Decision"] != "No feed signal"]
    if actionable:
        st.dataframe(
            actionable, hide_index=True,
            column_config={
                "Ticker": st.column_config.TextColumn(pinned=True),
                "Feed confidence": st.column_config.ProgressColumn(min_value=0, max_value=100),
                "Committee score": st.column_config.ProgressColumn(min_value=0, max_value=100),
                "Risk": st.column_config.ProgressColumn(min_value=0, max_value=100),
            },
        )
    else:
        st.info("No Watchlist or Discovery decision has enough matched feed evidence yet.")
    with st.expander("Feed audit: fetched and unmatched posts", icon=":material/fact_check:"):
        if raw_posts:
            st.dataframe([{
                "Source": item.get("source"), "Published": item.get("published_at"),
                "Matched stocks": ", ".join(match.get("ticker", "") for match in item.get("matches", [])),
                "Match method": ", ".join(match.get("method", "") for match in item.get("matches", [])),
                "Post": item.get("text"), "Source URL": item.get("url"),
            } for item in raw_posts], hide_index=True, column_config={
                "Source URL": st.column_config.LinkColumn(display_text="Open post"),
            })
        else:
            st.info("No posts have been returned by X yet.")
    st.markdown("#### Stock drill-down")
    ticker = st.selectbox(
        "Inspect a discovered stock (optional)", tickers, key="market-intelligence-ticker", accept_new_options=True,
        placeholder="Choose or enter a ticker",
    ).strip().upper()
    report = repository.latest_reports([ticker]).get(ticker)
    sector = str(report.company_metrics.get("sector", "")).strip() if report else ""
    result = build_market_intelligence(ticker, sources, commentary, sector=sector or None)

    with st.container(horizontal=True):
        st.metric("Specialist vote", result["vote"], border=True)
        st.metric("Confidence", f"{result['confidence']}%", border=True)
        st.metric("Analyst signal", f"{result['signal_score']}/100", border=True)
        st.metric("Influence signal", f"{result['influence_score']}/100", border=True)
        st.metric("Independent analysts", result["analysts"], border=True)
    if not result["items"]:
        st.info("Capture commentary for this company to create its first Market Intelligence vote.")
    elif result["vote"] == "Bullish":
        st.success(result["summary"], icon=":material/trending_up:")
    elif result["vote"] == "Bearish":
        st.warning(result["summary"], icon=":material/trending_down:")
    else:
        st.info(result["summary"], icon=":material/balance:")
    for warning in result["warnings"]:
        st.caption(f"Evidence warning: {warning}")

    if result["rows"]:
        st.markdown("#### Analyst consensus")
        with st.container(horizontal=True):
            st.metric("Bullish", result["bullish"], border=True)
            st.metric("Neutral", result["neutral"], border=True)
            st.metric("Bearish", result["bearish"], border=True)
        st.dataframe(
            result["rows"], hide_index=True,
            column_config={
                "Analyst": st.column_config.TextColumn(pinned=True),
                "Conviction": st.column_config.ProgressColumn(min_value=0, max_value=100),
                "Credibility": st.column_config.ProgressColumn(min_value=0, max_value=100),
                "Influence": st.column_config.ProgressColumn(min_value=0, max_value=100),
                "Expertise fit": st.column_config.ProgressColumn(min_value=0, max_value=100),
                "Source URL": st.column_config.LinkColumn(display_text="Open source"),
            },
        )
        st.markdown("#### Major themes")
        st.dataframe(result["themes"], hide_index=True)

    st.markdown("#### Live X feeds")
    x_provider = XFeedProvider(provider_cache)
    x_sources = [
        item for item in sources
        if str(item.get("platform", "")).lower() == "x" and item.get("handle")
    ]
    usage = x_provider.usage_status()
    with st.container(horizontal=True):
        st.metric("Token", "Configured" if x_provider.configured else "Missing", border=True)
        st.metric("Curated X handles", len(x_sources), border=True)
        st.metric("Atlas attempts today", f"{usage['used']} / {usage['usable_limit']}", border=True)
        st.metric("Cache window", "1 hour", border=True)
    if not x_sources:
        st.info("Add an analyst source with platform X and its @handle before syncing.")
    if st.button(
        "Refresh X feeds", type="primary", icon=":material/sync:",
        disabled=not x_provider.configured or not x_sources, key="refresh-x-feeds",
    ):
        with st.status("Reading curated X feeds...", expanded=True) as sync_status:
            sync_result = sync_x_sources(
                x_provider, sources, commentary, catalog=catalog, raw_posts=raw_posts,
            )
            repository.save_configuration("market_intelligence", {
                "sources": sources, "commentary": sync_result["commentary"], "raw_posts": sync_result["raw_posts"],
                "last_x_sync": {key: value for key, value in sync_result.items()
                                if key not in {"commentary", "raw_posts"}},
            })
            if sync_result["errors"]:
                sync_status.write(sync_result["errors"])
                sync_status.update(label="X feed refresh completed with errors", state="error")
            else:
                sync_status.update(label="X feed refresh completed", state="complete")
        st.toast(f"Read {sync_result['posts_fetched']} post(s); added {sync_result['items_added']} ticker signal(s).")
        st.rerun()
    st.caption("Atlas retains every fetched post and matches cashtags, saved tickers, and saved company names.")
    st.markdown("#### Capture evidence")
    commentary_tab, sources_tab = st.tabs(["Commentary", "Analyst sources"])
    with commentary_tab:
        _commentary_form(repository, ticker, sources, commentary)
    with sources_tab:
        _source_form(repository, sources, commentary)
    st.caption(result["disclosure"])


def _commentary_form(repository, ticker: str, sources: list[dict], commentary: list[dict]) -> None:
    if not sources:
        st.info("Add an analyst source before capturing commentary.")
        return
    labels = {item["id"]: f"{item['name']} ({item.get('platform', 'Other')})" for item in sources}
    with st.form("market-intelligence-commentary-form", clear_on_submit=True):
        source_id = st.selectbox("Analyst source", list(labels), format_func=labels.get)
        symbol = st.text_input("Ticker", value=ticker, max_chars=10)
        stance = st.segmented_control("Stance", STANCES, default="Neutral")
        conviction = st.slider("Conviction", 0, 100, 70)
        argument = st.selectbox("Argument type", ARGUMENT_TYPES)
        theme = st.text_input("Theme", placeholder="Example: AI capex or valuation risk")
        text = st.text_area("Commentary or thesis", placeholder="Summarize the analyst's actual reasoning.")
        url = st.text_input("Source URL", placeholder="https://...")
        published = st.date_input("Published date", value=date.today())
        submitted = st.form_submit_button("Save commentary", type="primary", icon=":material/add_comment:")
    if submitted:
        try:
            item = validate_commentary({
                "source_id": source_id, "ticker": symbol, "published_at": published.isoformat(),
                "stance": stance, "conviction": conviction, "argument_type": argument,
                "theme": theme, "text": text, "url": url,
            }, set(labels))
            repository.save_configuration("market_intelligence", {
                **(repository.configuration("market_intelligence") or {}),
                "sources": sources, "commentary": [item, *commentary][:500],
            })
            st.toast("Analyst commentary saved.", icon=":material/check_circle:")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


def _source_form(repository, sources: list[dict], commentary: list[dict]) -> None:
    with st.form("market-intelligence-source-form", clear_on_submit=True):
        name = st.text_input("Analyst or publication name")
        platform = st.selectbox("Platform", ["X", "YouTube", "Newsletter", "Podcast", "Other"])
        handle = st.text_input("Handle or channel")
        credibility = st.slider(
            "Predictive credibility", 0, 100, 50,
            help="Your estimate of historical reasoning quality, not popularity.",
        )
        influence = st.slider(
            "Market influence", 0, 100, 50,
            help="Your estimate of whether this source can move attention or price.",
        )
        expertise = st.multiselect(
            "Areas of expertise",
            ["Technology", "Financial services", "Healthcare", "Consumer", "Energy", "Industrials",
             "Real estate", "Utilities", "Macro", "Precious metals", "Crypto"],
        )
        submitted = st.form_submit_button("Save analyst source", type="primary", icon=":material/person_add:")
    if submitted:
        try:
            source = validate_source({
                "name": name, "platform": platform, "handle": handle, "credibility": credibility,
                "influence": influence, "expertise": expertise,
            })
            updated = [item for item in sources if item.get("id") != source["id"]] + [source]
            repository.save_configuration("market_intelligence", {
                **(repository.configuration("market_intelligence") or {}),
                "sources": updated, "commentary": commentary,
            })
            st.toast("Analyst source saved.", icon=":material/check_circle:")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
    if sources:
        st.dataframe(
            sources, hide_index=True,
            column_config={
                "id": None,
                "credibility": st.column_config.ProgressColumn(min_value=0, max_value=100),
                "influence": st.column_config.ProgressColumn(min_value=0, max_value=100),
            },
        )
