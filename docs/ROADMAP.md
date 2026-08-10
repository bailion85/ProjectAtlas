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
- Configurable strategy weights with explainable scoring
- Side-by-side company and report comparison
- Exportable research reports
- Provider caching, rate-limit handling, and broader test coverage

## Milestone 3 — Decision support

- Portfolio exposure analysis without transaction execution
- Thesis tracking and catalyst monitoring
- Report-to-report change detection
- Watchlist alerts and scheduled research refreshes
