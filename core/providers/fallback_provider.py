from __future__ import annotations

from typing import Any, Callable

from core.providers.market_provider import MarketDataProvider, ProviderError

LIVE_FALLBACK_PROVIDER_VERSION = 2


class LiveFallbackMarketDataProvider(MarketDataProvider):
    """Prefer one live provider and transparently use a second live provider on failure."""

    supports_no_credit_research = True
    snapshot_schema_version = 1

    def __init__(self, primary: MarketDataProvider, fallback: MarketDataProvider):
        self.primary = primary
        self.fallback = fallback
        self.name = f"{primary.name} + {fallback.name} fallback"
        self._fallbacks = 0
        self._last_fallback = "None"

    def _call(self, operation: str, *args: Any) -> Any:
        try:
            return getattr(self.primary, operation)(*args)
        except ProviderError as primary_error:
            try:
                value = getattr(self.fallback, operation)(*args)
            except (ProviderError, KeyError, TypeError, ValueError):
                raise primary_error
            self._fallbacks += 1
            self._last_fallback = f"{operation}: {args[0] if args else 'market'}"
            return value

    def search(self, query: str) -> list[dict[str, str]]:
        return self._call("search", query)

    def snapshot(self, ticker: str) -> dict[str, Any]:
        return self._call("snapshot", ticker)

    def price_snapshot(self, ticker: str) -> dict[str, Any]:
        return self._call("price_snapshot", ticker)

    def security_metadata(self, ticker: str) -> dict[str, Any]:
        return self._call("security_metadata", ticker)

    def market_movers(self) -> dict[str, Any]:
        return self._call("market_movers")

    def market_dashboard(self, tickers: tuple[str, ...]) -> dict[str, Any]:
        requested = tuple(dict.fromkeys(str(ticker).strip().upper() for ticker in tickers if str(ticker).strip()))
        try:
            primary = self.primary.market_dashboard(requested)
        except ProviderError:
            return self._call("market_dashboard", requested)
        primary_quotes = list(primary.get("quotes", []))
        returned = {str(row.get("ticker", "")).upper() for row in primary_quotes}
        missing = tuple(ticker for ticker in requested if ticker not in returned)
        if not missing:
            return primary
        try:
            supplement = self.fallback.market_dashboard(missing)
        except (ProviderError, KeyError, TypeError, ValueError):
            return primary
        self._fallbacks += 1
        self._last_fallback = f"market_dashboard missing: {', '.join(missing)}"
        return {
            **primary, "provider": f"{primary.get('provider', self.primary.name)} + {supplement.get('provider', self.fallback.name)}",
            "quotes": primary_quotes + list(supplement.get("quotes", [])),
        }

    def news(self, ticker: str) -> list[dict[str, Any]]:
        return self._call("news", ticker)

    def history(self, ticker: str) -> list[dict[str, Any]]:
        return self._call("history", ticker)

    def daily_history(self, ticker: str) -> list[dict[str, Any]]:
        return self._call("daily_history", ticker)

    def status(self) -> dict[str, Any]:
        return {"provider": self.name, "live_fallbacks": self._fallbacks,
                "last_live_fallback": self._last_fallback}

class FallbackMarketDataProvider(MarketDataProvider):
    """Use clearly identified demo data only when the live provider is unavailable."""

    def __init__(self, primary: MarketDataProvider, fallback: MarketDataProvider):
        self.primary = primary
        self.fallback = fallback
        self.name = f"{primary.name} (demo fallback enabled)"
        self._fallbacks = 0
        self._last_fallback = "None"

    def _call(self, operation: str, *args: Any) -> Any:
        try:
            return getattr(self.primary, operation)(*args)
        except ProviderError as primary_error:
            try:
                value = getattr(self.fallback, operation)(*args)
            except (ProviderError, KeyError, ValueError):
                raise primary_error
            self._fallbacks += 1
            self._last_fallback = f"{operation}: {args[0] if args else 'market'}"
            return value

    def search(self, query: str) -> list[dict[str, str]]:
        return self._call("search", query)

    def market_movers(self) -> dict[str, Any]:
        return self._call("market_movers")

    def market_dashboard(self, tickers: tuple[str, ...]) -> dict[str, Any]:
        return self._call("market_dashboard", tickers)
    def snapshot(self, ticker: str) -> dict[str, Any]:
        return self._call("snapshot", ticker)

    def market_news(self, limit: int = 50) -> dict[str, Any]:
        return self._call("market_news", limit)
    def news(self, ticker: str) -> list[dict[str, Any]]:
        return self._call("news", ticker)

    def history(self, ticker: str) -> list[dict[str, Any]]:
        return self._call("history", ticker)

    def daily_history(self, ticker: str) -> list[dict[str, Any]]:
        return self._call("daily_history", ticker)

    def status(self) -> dict[str, Any]:
        status = self.primary.status() if hasattr(self.primary, "status") else {"provider": self.primary.name}
        return {**status, "provider": self.name, "demo_fallbacks": self._fallbacks,
                "last_demo_fallback": self._last_fallback}

    def reset_status(self) -> None:
        if hasattr(self.primary, "reset_status"):
            self.primary.reset_status()
        self._fallbacks = 0
        self._last_fallback = "None"

    def estimated_requests_for_analysis(self, tickers: list[str]) -> int:
        estimator: Callable[[list[str]], int] | None = getattr(
            self.primary, "estimated_requests_for_analysis", None
        )
        return estimator(tickers) if estimator else 0
