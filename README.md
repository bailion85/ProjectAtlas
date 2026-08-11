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

## Run locally

1. Create a virtual environment and install `requirements.txt`.
2. Copy `.env.example` to `.env`.
3. Leave `ATLAS_DATA_PROVIDER=demo` for the credential-free sample, or set it to `alpha_vantage` and add your Alpha Vantage API key.
4. Leave `ATLAS_MACRO_PROVIDER=demo`, or set it to `fred` and add a free FRED API key.
5. Run `streamlit run app.py`.

Atlas caches provider responses in `data/provider_cache.db`. Use the Data status panel to inspect request activity or force a fresh provider request.

Demo mode contains only AAPL, MSFT, NVDA, GOOGL, and AMZN. Its values are illustrative, not live.

## Data policy

The production adapters call the documented Alpha Vantage and FRED APIs and do not scrape web pages. Provider limits and licensing remain the operator's responsibility. Every report records provider and observation timestamps. Strategy conclusions are deterministic and traceable to displayed evidence.

## Tests

Run `pytest -q`. Tests use the local demo provider and never call external services.

## Legacy prototype

The original command-line prototype remains in `main.py`, `atlas.py`, and the existing `core` modules for reference. Its yfinance dependency is intentionally not part of the new production path.
