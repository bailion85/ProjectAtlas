from __future__ import annotations

from fastapi.testclient import TestClient

import atlas_api


class FakeProvider:
    name = "Test live provider"
    def status(self):
        return {"cache_entries": 3, "last_source": "Fresh cache", "last_operation": "market_dashboard"}
    def market_dashboard(self, symbols):
        return {"provider": self.name, "quotes": [{"ticker": symbols[0], "price": 100}]}
    def daily_history(self, ticker):
        return [{"date": "2026-08-12", "close": 100}]
    def snapshot(self, ticker):
        return {"symbol": ticker.upper(), "price": 100, "source": self.name}


def test_fastapi_health_quotes_history_and_research(monkeypatch):
    monkeypatch.setattr(atlas_api, "services", lambda: (FakeProvider(), object(), object()))
    client = TestClient(atlas_api.app)
    assert client.get("/api/health").json()["status"] == "ready"
    assert client.get("/api/quotes", params={"symbols": "AAPL"}).json()["quotes"][0]["price"] == 100
    assert client.get("/api/history/AAPL").json()["points"][0]["close"] == 100
    assert client.get("/api/research/AAPL").json()["source"] == "Test live provider"
