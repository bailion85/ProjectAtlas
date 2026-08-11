from __future__ import annotations

import threading
import time
from typing import Any, Callable

from core.providers.economic_provider import EconomicDataProvider
from core.providers.market_provider import MarketDataProvider, ProviderError
from core.services.provider_cache import ProviderCache


MARKET_TTLS = {"search": 86400, "snapshot": 900, "news": 900, "history": 43200, "daily_history": 43200}
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
        return {
            "provider": self.name,
            **self._stats,
            "cache_entries": self.cache.count(self.namespace),
            "last_operation": self._last_event["operation"],
            "last_source": self._last_event["source"],
            "last_age_seconds": self._last_event["age_seconds"],
        }

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

    def search(self, query: str) -> list[dict[str, str]]:
        normalized = query.strip().lower()
        return self._cached("search", {"query": normalized}, lambda: self.delegate.search(query))

    def snapshot(self, ticker: str) -> dict[str, Any]:
        symbol = ticker.strip().upper()
        return self._cached("snapshot", {"ticker": symbol}, lambda: self.delegate.snapshot(symbol))

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


class CachedEconomicDataProvider(_CachedProvider, EconomicDataProvider):
    def __init__(self, delegate: EconomicDataProvider, cache: ProviderCache, **kwargs: Any):
        super().__init__(delegate, cache, f"macro:{delegate.name}", kwargs.pop("ttls", MACRO_TTLS), **kwargs)
        self.name = delegate.name

    def snapshot(self) -> dict[str, Any]:
        return self._cached("snapshot", {}, self.delegate.snapshot)


def _retryable(error: ProviderError) -> bool:
    message = str(error).lower()
    if any(token in message for token in ("rate limit", "429", "frequency", "limit reached")):
        return False
    return any(token in message for token in (
        "request failed", "timeout", "timed out", "connection", "temporar", "500", "502", "503", "504"
    ))
