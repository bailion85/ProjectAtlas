from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query

from core.providers.market_provider import ProviderError
from core.services.discovery_scan_service import DiscoveryScanService
from core.services.market_provider_factory import build_live_market_provider
from core.services.provider_cache import ProviderCache
from core.services.report_repository import ReportRepository


load_dotenv(override=True)
app = FastAPI(
    title="Project Atlas data service",
    version="1.0.0",
    description="Cached live-market data and research endpoints for Project Atlas.",
)


@lru_cache(maxsize=1)
def services():
    cache = ProviderCache(os.getenv("ATLAS_CACHE_PATH", "data/provider_cache.db"))
    provider = build_live_market_provider(cache)
    repository = ReportRepository(os.getenv("ATLAS_DATABASE_PATH", "data/atlas.db"))
    return provider, repository, cache


@app.get("/api/health")
def health():
    provider, _, _ = services()
    status = provider.status()
    return {"status": "ready", "provider": provider.name, "cache_entries": status.get("cache_entries", 0),
            "last_source": status.get("last_source"), "last_operation": status.get("last_operation")}


@app.get("/api/quotes")
def quotes(symbols: list[str] = Query(..., min_length=1, max_length=50)):
    provider, _, _ = services()
    normalized = tuple(dict.fromkeys(symbol.strip().upper() for symbol in symbols if symbol.strip()))
    if not normalized:
        raise HTTPException(400, "At least one ticker is required.")
    try:
        return provider.market_dashboard(normalized)
    except ProviderError as exc:
        raise HTTPException(503, str(exc)) from exc


@app.get("/api/history/{ticker}")
def history(ticker: str):
    provider, _, _ = services()
    try:
        return {"ticker": ticker.upper(), "provider": provider.name,
                "points": provider.daily_history(ticker)}
    except ProviderError as exc:
        raise HTTPException(503, str(exc)) from exc


@app.get("/api/research/{ticker}")
def research(ticker: str):
    provider, _, _ = services()
    try:
        return provider.snapshot(ticker)
    except ProviderError as exc:
        raise HTTPException(503, str(exc)) from exc


@app.post("/api/discovery")
def discovery(limit: int = Query(5, ge=1, le=8)):
    provider, repository, cache = services()
    try:
        return DiscoveryScanService(provider, repository, cache).run(limit)
    except (ProviderError, RuntimeError, TypeError, ValueError) as exc:
        raise HTTPException(503, str(exc)) from exc
