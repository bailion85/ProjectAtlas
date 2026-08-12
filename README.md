# Project Atlas

Project Atlas is an **analysis-only** investment research application. It has no order entry, brokerage connection, portfolio execution, or real-money trading capability.

## Milestone 1

- Streamlit dashboard with ticker search and a persistent watchlist
- Six independent, transparent strategy assessments: Value, GARP, Innovation, Macro, Quant, and Risk
- Committee vote, confidence, evidence, provider attribution, and data timestamps
- Executive summary, bull case, bear case, risks, and catalysts
- SQLite-backed research-report history
- Five-year performance history with S&P 500 comparison
- Total return, relative return, volatility, and maximum drawdown metrics
- Sector-aware macro assessment covering inflation, rates, unemployment, and GDP growth
- Configurable strategy weights, committee presets, and weighted decision contributions
- Saved two-to-four company comparisons with rankings and normalized performance
- Downloadable PDF exports for current and historical reports and comparisons
- Persistent provider caching, bounded retries, stale fallback, and request-status diagnostics
- Documented Alpha Vantage integration for legitimate market/fundamental/news data
- Clearly labeled offline demo mode
- Analysis-only portfolio allocations with concentration, weighted risk, entry-readiness, sector, catalyst, and PDF reporting
- Report-to-report research change tracking with auditable thesis status and PDF export
- Scheduled watchlist and portfolio research refreshes with retry limits, automatic alert scans, and run history
- Opt-in live-data readiness diagnostics for Alpha Vantage, FRED, field coverage, freshness, cache behavior, and technical-history requirements
- SEC EDGAR-backed financial-health trends using annual 10-K facts with explicit missing-data coverage
- Watchlist SEC filing monitor with quarterly 10-Q trends, accession-based new-filing detection, version history, and material-change alerts
- Guided Start here workflow with company evidence completeness, live-data setup status, beginner explanations, and explicit research actions
- Educational position-sizing planner with loss budgets, concentration limits, evidence-based reductions, sector warnings, and saved versions
- Unified company decision packet in Start here with saved evidence review and a polished downloadable PDF
- Company-level evidence trust scoring with live/demo/stale gates for beginner labels and PDF watermarks
- Prioritized portfolio action plan combining risk, concentration, evidence trust, and saved position ceilings with PDF export
- Immutable decision-label snapshots with 7/30/90/365-day S&P 500-relative outcome tracking and accuracy PDF export
- Two-stage opportunity discovery for configurable companies outside the watchlist, with preliminary factor rankings and finalist research
- Native grouped page navigation that loads only the selected Atlas workflow instead of rendering every view at once
- Optional weekday Discovery worker with Eastern-time scheduling, provider-cache reuse, run history, and change alerts
- Read-only provider-health dashboard for live modes, saved readiness tests, cache state, quota, SEC setup, calendars, and scheduling

## Run locally

1. Create a virtual environment and install `requirements.txt`.
2. Copy `.env.example` to `.env`.
3. Leave `ATLAS_DATA_PROVIDER=demo`, set it to `alpha_vantage`, or use `hybrid` with free Alpha Vantage and Tiingo keys for long price history.
4. Leave `ATLAS_MACRO_PROVIDER=demo`, or set it to `fred` and add a free FRED API key.
5. Set `ATLAS_CALENDAR_PROVIDER=fred` to use official economic release dates from FRED. This uses the same FRED API key.
6. Run `streamlit run app.py`.

To use Financial health, set `SEC_USER_AGENT` to an application name and contact email, for example `Project Atlas research@example.com`. SEC data is requested only after clicking Analyze and is cached for 24 hours.
The Financial health filing monitor checks watchlist companies on demand. It saves a new version only when the latest SEC accession changes and alerts when the financial-health score moves by at least 10 points.

Atlas caches provider responses in `data/provider_cache.db`. Use the Data status panel to inspect request activity or force a fresh provider request.

The live economic calendar is cached for six hours. Atlas archives expired or demo catalyst alerts and will not create a catalyst alert from demo or stale calendar data.
The Alpha Vantage earnings calendar is cached for 24 hours and fetched as one three-month calendar request. Earnings dates are labeled as estimates and stale dates cannot create alerts.

Demo mode contains only AAPL, MSFT, NVDA, GOOG, GOOGL, and AMZN. Its values are illustrative, not live.

## Data policy

The production adapters call the documented Alpha Vantage, Tiingo, and FRED APIs and do not scrape web pages. Provider limits and licensing remain the operator's responsibility. Every report records provider and observation timestamps. Strategy conclusions are deterministic and traceable to displayed evidence.

## Tests

Run `powershell -ExecutionPolicy Bypass -File .\scripts\verify.ps1` from the ProjectAtlas directory.
The verifier uses Atlas's own Python environment, runs the complete offline test suite, and performs a headless Streamlit render. Tests use the local demo provider and never call external services.

## Legacy prototype

The original command-line prototype remains in `main.py`, `atlas.py`, and the existing `core` modules for reference. Its yfinance dependency is intentionally not part of the new production path.
