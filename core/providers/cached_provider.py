from __future__ import annotations

import threading
import time
from typing import Any, Callable

from core.providers.economic_provider import EconomicDataProvider
from core.providers.market_provider import MarketDataProvider, ProviderError
from core.services.provider_cache import ProviderCache

CACHED_PROVIDER_VERSION = 5


MARKET_TTLS = {"search": 86400, "market_movers": 21600, "market_dashboard": 300, "market_news": 3600, "snapshot": 900, "news": 900, "history": 43200, "daily_history": 43200}
MACRO_TTLS = {"snapshot": 21600}


class _CachedProvider:
    _locks: dict[str, threading.Lock] = {}
    _locks_guard = threading.Lock()

    def __init__(
        self,
        delegate: Any,
        cache: ProviderCache,
        namespace: str,
        ttls: dict[str, int],
        max_attempts: int = 3,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        self.delegate = delegate
        self.cache = cache
        self.namespace = namespace
        self.ttls = ttls
        self.max_attempts = max(1, max_attempts)
        self.sleeper = sleeper
        self._stats = {"cache_hits": 0, "live_requests": 0, "stale_fallbacks": 0, "retries": 0}
        self._last_event = {"operation": "None", "source": "No requests yet", "age_seconds": None}

    def _cached(self, operation: str, parameters: Any, fetch: Callable[[], Any]) -> Any:
        record = self.cache.get(self.namespace, operation, parameters)
        if record:
            self._record("cache_hits", operation, "Fresh cache", record.age_seconds)
            return record.value
        lock_key = ProviderCache._key(self.namespace, operation, parameters)
        lock = self._lock(lock_key)
        with lock:
            record = self.cache.get(self.namespace, operation, parameters)
            if record:
                self._record("cache_hits", operation, "Fresh cache", record.age_seconds)
                return record.value
            last_error = None
            for attempt in range(self.max_attempts):
                try:
                    self._stats["live_requests"] += 1
                    value = fetch()
                    self.cache.put(self.namespace, operation, parameters, value, self.ttls[operation])
                    self._last_event = {"operation": operation, "source": "Live provider", "age_seconds": 0.0}
                    return value
                except ProviderError as exc:
                    last_error = exc
                    if attempt + 1 >= self.max_attempts or not _retryable(exc):
                        break
                    self._stats["retries"] += 1
                    self.sleeper(0.25 * (3 ** attempt))
            stale = self.cache.get(self.namespace, operation, parameters, allow_expired=True)
            if stale:
                self._record("stale_fallbacks", operation, "Stale fallback", stale.age_seconds)
                return stale.value
            raise last_error or ProviderError(f"{operation} failed without a provider response.")

    def status(self) -> dict[str, Any]:
        status = {
            "provider": self.name,
            **self._stats,
            "cache_entries": self.cache.count(self.namespace),
            "last_operation": self._last_event["operation"],
            "last_source": self._last_event["source"],
            "last_age_seconds": self._last_event["age_seconds"],
        }
        if hasattr(self.delegate, "usage_status"):
            usage = self.delegate.usage_status()
            status.update({f"quota_{key}": value for key, value in usage.items()})
        return status

    def reset_status(self) -> None:
        for key in self._stats:
            self._stats[key] = 0
        self._last_event = {"operation": "None", "source": "No requests yet", "age_seconds": None}

    def _record(self, counter: str, operation: str, source: str, age_seconds: float) -> None:
        self._stats[counter] += 1
        self._last_event = {"operation": operation, "source": source, "age_seconds": round(age_seconds, 1)}

    @classmethod
    def _lock(cls, key: str) -> threading.Lock:
        with cls._locks_guard:
            return cls._locks.setdefault(key, threading.Lock())


class CachedMarketDataProvider(_CachedProvider, MarketDataProvider):
    def __init__(self, delegate: MarketDataProvider, cache: ProviderCache, **kwargs: Any):
        super().__init__(delegate, cache, f"market:{delegate.name}", kwargs.pop("ttls", MARKET_TTLS), **kwargs)
        self.name = delegate.name
        self.supports_no_credit_research = bool(getattr(delegate, "supports_no_credit_research", False))
        self.snapshot_schema_version = int(getattr(delegate, "snapshot_schema_version", 1))

    def search(self, query: str) -> list[dict[str, str]]:
        normalized = query.strip().lower()
        return self._cached("search", {"query": normalized}, lambda: self.delegate.search(query))

    def market_movers(self) -> dict[str, Any]:
        reader = getattr(self.delegate, "market_movers", None)
        if reader is None:
            raise ProviderError(f"{self.name} does not provide an automatic market-candidate feed.")
        return self._cached("market_movers", {}, reader)

    def market_dashboard(self, tickers: tuple[str, ...]) -> dict[str, Any]:
        symbols = tuple(dict.fromkeys(symbol.strip().upper() for symbol in tickers if symbol.strip()))
        reader = getattr(self.delegate, "market_dashboard", None)
        if reader is None:
            raise ProviderError(f"{self.name} does not provide batched dashboard quotes.")
        return self._cached("market_dashboard", {"tickers": symbols}, lambda: reader(symbols))
    def snapshot(self, ticker: str) -> dict[str, Any]:
        symbol = ticker.strip().upper()
        return self._cached(
            "snapshot", {"ticker": symbol, "schema": self.snapshot_schema_version},
            lambda: self.delegate.snapshot(symbol),
        )

    def market_news(self, limit: int = 50) -> dict[str, Any]:
        reader = getattr(self.delegate, "market_news", None)
        if reader is None:
            raise ProviderError(f"{self.name} does not provide a market-news feed.")
        return self._cached("market_news", {"limit": int(limit)}, lambda: reader(limit))
    def news(self, ticker: str) -> list[dict[str, Any]]:
        symbol = ticker.strip().upper()
        return self._cached("news", {"ticker": symbol}, lambda: self.delegate.news(symbol))

    def history(self, ticker: str) -> list[dict[str, Any]]:
        symbol = ticker.strip().upper()
        return self._cached("history", {"ticker": symbol}, lambda: self.delegate.history(symbol))

    def daily_history(self, ticker: str) -> list[dict[str, Any]]:
        symbol = ticker.strip().upper()
        return self._cached(
            "daily_history", {"ticker": symbol}, lambda: self.delegate.daily_history(symbol)
        )

    def estimated_requests_for_analysis(self, tickers: list[str]) -> int:
        symbols = list(dict.fromkeys(ticker.strip().upper() for ticker in tickers if ticker.strip()))
        cost = getattr(self.delegate, "quota_cost", lambda operation: {
            "snapshot": 2, "news": 1, "history": 1, "daily_history": 1,
        }.get(operation, 0))
        estimate = self._uncached_cost("history", {"ticker": "SPY"}, cost("history"))
        estimate += self._uncached_cost("daily_history", {"ticker": "SPY"}, cost("daily_history"))
        for symbol in symbols:
            estimate += self._uncached_cost(
                "snapshot", {"ticker": symbol, "schema": self.snapshot_schema_version}, cost("snapshot")
            )
            estimate += self._uncached_cost("news", {"ticker": symbol}, cost("news"))
            estimate += self._uncached_cost("history", {"ticker": symbol}, cost("history"))
            estimate += self._uncached_cost("daily_history", {"ticker": symbol}, cost("daily_history"))
        return estimate

    def _uncached_cost(self, operation: str, parameters: dict[str, str], cost: int) -> int:
        return 0 if self.cache.get(self.namespace, operation, parameters) else cost


class CachedEconomicDataProvider(_CachedProvider, EconomicDataProvider):
    def __init__(self, delegate: EconomicDataProvider, cache: ProviderCache, **kwargs: Any):
        super().__init__(delegate, cache, f"macro:{delegate.name}", kwargs.pop("ttls", MACRO_TTLS), **kwargs)
        self.name = delegate.name
        self.supports_no_credit_research = bool(getattr(delegate, "supports_no_credit_research", False))
        self.snapshot_schema_version = int(getattr(delegate, "snapshot_schema_version", 1))

    def snapshot(self) -> dict[str, Any]:
        return self._cached("snapshot", {"schema": 3}, self.delegate.snapshot)


def _retryable(error: ProviderError) -> bool:
    message = str(error).lower()
    if any(token in message for token in ("rate limit", "429", "frequency", "limit reached")):
        return False
    return any(token in message for token in (
        "request failed", "timeout", "timed out", "connection", "temporar", "500", "502", "503", "504"
    ))
