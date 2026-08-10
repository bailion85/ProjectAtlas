# Project Atlas

Project Atlas is an **analysis-only** investment research application. It has no order entry, brokerage connection, portfolio execution, or real-money trading capability.

## Milestone 1

- Streamlit dashboard with ticker search and a persistent watchlist
- Six independent, transparent strategy assessments: Value, GARP, Innovation, Macro, Quant, and Risk
- Committee vote, confidence, evidence, provider attribution, and data timestamps
- Executive summary, bull case, bear case, risks, and catalysts
- SQLite-backed research-report history
- Documented Alpha Vantage integration for legitimate market/fundamental/news data
- Clearly labeled offline demo mode

## Run locally

1. Create a virtual environment and install `requirements.txt`.
2. Copy `.env.example` to `.env`.
3. Leave `ATLAS_DATA_PROVIDER=demo` for the credential-free sample, or set it to `alpha_vantage` and add your Alpha Vantage API key.
4. Run `streamlit run app.py`.

Demo mode contains only AAPL, MSFT, NVDA, GOOGL, and AMZN. Its values are illustrative, not live.

## Data policy

The production adapter calls Alpha Vantage's documented API and does not scrape web pages. Provider limits and licensing remain the operator's responsibility. Every report records the provider and observation timestamp. AI prose is not required for Milestone 1; strategy conclusions are deterministic and traceable to displayed evidence.

## Tests

Run `pytest -q`. Tests use the local demo provider and never call external services.

## Legacy prototype

The original command-line prototype remains in `main.py`, `atlas.py`, and the existing `core` modules for reference. Its yfinance dependency is intentionally not part of the new production path.
