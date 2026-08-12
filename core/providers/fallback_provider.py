from __future__ import annotations

from typing import Any, Callable

from core.providers.market_provider import MarketDataProvider, ProviderError


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

    def snapshot(self, ticker: str) -> dict[str, Any]:
        return self._call("snapshot", ticker)

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
