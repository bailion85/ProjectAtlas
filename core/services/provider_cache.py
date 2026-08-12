from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator


@dataclass(frozen=True)
class CacheRecord:
    value: Any
    age_seconds: float
    expired: bool


class ProviderCache:
    def __init__(self, path: str | Path = "data/provider_cache.db", clock: Callable[[], float] = time.time):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        with self._connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS provider_cache ("
                "cache_key TEXT PRIMARY KEY, namespace TEXT NOT NULL, operation TEXT NOT NULL, "
                "created_at REAL NOT NULL, expires_at REAL NOT NULL, payload TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS provider_usage (provider TEXT NOT NULL, usage_date TEXT NOT NULL, "
                "requests INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(provider, usage_date))"
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def get(self, namespace: str, operation: str, parameters: Any, allow_expired: bool = False) -> CacheRecord | None:
        key = self._key(namespace, operation, parameters)
        with self._connect() as db:
            row = db.execute(
                "SELECT created_at, expires_at, payload FROM provider_cache WHERE cache_key = ?", (key,)
            ).fetchone()
        if not row:
            return None
        now = self.clock()
        expired = now >= float(row[1])
        if expired and not allow_expired:
            return None
        return CacheRecord(json.loads(row[2]), max(0.0, now - float(row[0])), expired)

    def put(self, namespace: str, operation: str, parameters: Any, value: Any, ttl_seconds: int) -> None:
        key = self._key(namespace, operation, parameters)
        now = self.clock()
        payload = json.dumps(value, separators=(",", ":"), sort_keys=True)
        with self._connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO provider_cache(cache_key, namespace, operation, created_at, expires_at, payload) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (key, namespace, operation, now, now + ttl_seconds, payload),
            )

    def clear(self, namespace: str | None = None) -> None:
        with self._connect() as db:
            if namespace:
                db.execute("DELETE FROM provider_cache WHERE namespace = ?", (namespace,))
            else:
                db.execute("DELETE FROM provider_cache")

    def count(self, namespace: str | None = None) -> int:
        with self._connect() as db:
            if namespace:
                row = db.execute("SELECT COUNT(*) FROM provider_cache WHERE namespace = ?", (namespace,)).fetchone()
            else:
                row = db.execute("SELECT COUNT(*) FROM provider_cache").fetchone()
        return int(row[0])

    def claim_request(self, provider: str, daily_limit: int, reserve: int = 0) -> bool:
        usage_date = time.strftime("%Y-%m-%d", time.gmtime(self.clock()))
        usable_limit = max(0, int(daily_limit) - max(0, int(reserve)))
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT requests FROM provider_usage WHERE provider = ? AND usage_date = ?",
                (provider, usage_date),
            ).fetchone()
            used = int(row[0]) if row else 0
            if used >= usable_limit:
                return False
            db.execute(
                "INSERT INTO provider_usage(provider, usage_date, requests) VALUES (?, ?, 1) "
                "ON CONFLICT(provider, usage_date) DO UPDATE SET requests = requests + 1",
                (provider, usage_date),
            )
        return True

    def usage_status(self, provider: str, daily_limit: int, reserve: int = 0) -> dict[str, int | str]:
        usage_date = time.strftime("%Y-%m-%d", time.gmtime(self.clock()))
        with self._connect() as db:
            row = db.execute(
                "SELECT requests FROM provider_usage WHERE provider = ? AND usage_date = ?",
                (provider, usage_date),
            ).fetchone()
        used = int(row[0]) if row else 0
        limit = max(0, int(daily_limit))
        protected = max(0, min(limit, int(reserve)))
        usable = limit - protected
        return {
            "usage_date": usage_date, "daily_limit": limit, "reserve": protected,
            "usable_limit": usable, "used": used, "remaining": max(0, usable - used),
        }

    @staticmethod
    def _key(namespace: str, operation: str, parameters: Any) -> str:
        serialized = json.dumps(parameters, separators=(",", ":"), sort_keys=True)
        digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        return f"{namespace}:{operation}:{digest}"
