# Project Atlas Roadmap

Atlas is an analysis-only investment research application. Brokerage connectivity,
order entry, paper trading, and live trading are outside the product scope.

## Milestone 1 — Research foundation (stabilization)

- Streamlit dashboard with ticker search and persistent watchlist
- Six transparent strategy assessments and a committee decision
- Evidence, source attribution, and observation timestamps
- SQLite-backed report history
- Offline demo provider and documented Alpha Vantage adapter
- Automated coverage for the core demo workflow

Exit criteria: the demo workflow passes locally, live-provider failures are shown
clearly, documentation matches the product, and the milestone is committed as a
clean baseline.

## Milestone 2 — Research depth (in progress)

- Historical performance and benchmark comparisons (complete)
- Real macroeconomic evidence for the Macro strategy (complete)
- Configurable strategy weights with explainable scoring (complete)
- Side-by-side company and report comparison (complete)
- Exportable research and comparison PDF reports (complete)
- Provider caching, rate-limit handling, and broader test coverage (complete)

## Milestone 3 — Decision support

- Portfolio exposure analysis without transaction execution (complete)
- Portfolio stress testing with preset and custom economic scenarios (complete)
- Decision Center with prioritized cross-feature research follow-ups (complete)
- Versioned thesis tracking, decision journaling, review dates, and automated invalidation checks (complete)
- Report-to-report change detection (complete)
- Watchlist alerts and scheduled research refreshes (complete)

## Milestone 4 — Live-data readiness

- Manual Alpha Vantage endpoint, coverage, freshness, cache, retry, and fallback diagnostics (complete)
- Manual FRED coverage and staleness diagnostics (complete)
- Explicit 200-day technical-history readiness gate and safe provider-switch instructions (complete)
- Free hybrid provider using Tiingo price history with Alpha Vantage fundamentals/news (complete)
- SEC 10-K/10-Q watchlist monitoring, filing-version detection, and financial-health change alerts (complete)
- Guided Home workflow and consolidated evidence-readiness checklist (complete)
- Position-sizing and diversification planning with versioned assumptions (complete)
- Unified company decision packet and PDF export (complete)
- Evidence trust scoring and conservative live-data label gates (complete)
- Portfolio-level weekly action plan with sizing gaps and PDF export (complete)
- Historical label accuracy, benchmark-relative outcomes, and model-capacity reporting (complete)
- Opportunity discovery with capped broad screening, explicit finalist selection, and PDF export (complete)
- Versioned discovery monitoring with new-candidate, rank, evidence, and removal alerts (complete)
- Native grouped navigation with lazy page execution and full-route regression coverage (complete)
- Scheduled weekday Discovery scans with independent audit history and Windows background worker (complete)
- Unified provider-health dashboard with no-request telemetry, remedies, quota reset, and scheduler status (complete)
