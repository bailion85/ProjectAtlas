from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from core.providers.market_provider import ProviderError
from core.services.financial_health_service import analyze_financial_health

SEC_PROVIDER_VERSION = 2


class SecCompanyFactsProvider:
    name = "SEC EDGAR company facts"
    tickers_url = "https://www.sec.gov/files/company_tickers.json"
    facts_url = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

    def __init__(self, cache, user_agent: str | None = None, timeout: int = 20):
        self.cache = cache
        self.user_agent = (user_agent or os.getenv("SEC_USER_AGENT", "")).strip()
        self.timeout = timeout

    def company_facts(self, ticker: str) -> dict[str, Any]:
        if not self.user_agent or "@" not in self.user_agent:
            raise ProviderError("Set SEC_USER_AGENT to an application name and contact email before using SEC EDGAR.")
        symbol = ticker.strip().upper()
        cached = self.cache.get("sec_edgar", "company_facts", {"ticker": symbol})
        if cached:
            return {**cached.value, "cache_status": "Fresh cache", "cache_age_seconds": round(cached.age_seconds)}
        cik_map = self._ticker_map()
        if symbol not in cik_map:
            raise ProviderError(f"SEC EDGAR did not return a CIK for {symbol}.")
        cik = str(cik_map[symbol]["cik"]).zfill(10)
        payload = self._get(self.facts_url.format(cik=cik))
        result = {
            "ticker": symbol, "cik": cik, "company": payload.get("entityName") or cik_map[symbol]["title"],
            "facts": payload.get("facts", {}), "provider": self.name,
            "retrieved_at": datetime.now(timezone.utc).isoformat(), "cache_status": "Fresh live response",
        }
        self.cache.put("sec_edgar", "company_facts", {"ticker": symbol}, result, 24 * 60 * 60)
        return {**result, "cache_age_seconds": 0}

    def fundamentals(self, ticker: str, price: float | None = None) -> dict[str, Any]:
        snapshot = self.company_facts(ticker)
        health = analyze_financial_health(snapshot)
        latest = health["rows"][-1]
        previous = health["rows"][-2]
        revenue = latest.get("Revenue")
        net_income = latest.get("Net income")
        operating_income = latest.get("Operating income")
        equity = latest.get("Equity")
        liabilities = latest.get("Liabilities")
        shares = latest.get("Shares")
        earnings_per_share = _ratio(net_income, shares)
        book_value_per_share = _ratio(equity, shares)
        return {
            "symbol": snapshot["ticker"], "name": snapshot["company"], "description": "",
            "sector": "Unknown", "industry": "Unknown", "price": price,
            "change_percent": None,
            "market_cap": price * shares if price is not None and shares else None,
            "pe_ratio": _ratio(price, earnings_per_share), "forward_pe": None,
            "peg_ratio": None, "price_to_book": _ratio(price, book_value_per_share),
            "profit_margin": _ratio(net_income, revenue),
            "operating_margin": _ratio(operating_income, revenue),
            "return_on_equity": _ratio(net_income, equity),
            "revenue_growth": _growth(revenue, previous.get("Revenue")),
            "earnings_growth": _growth(net_income, previous.get("Net income")),
            "debt_to_equity": _ratio(liabilities, equity),
            "free_cashflow": latest.get("Free cash flow"), "beta": None,
            "fifty_two_week_high": None, "fifty_two_week_low": None,
            "analyst_target": None, "observed_at": snapshot["retrieved_at"],
            "source": self.name, "sec_financial_health": health,
        }
    def _ticker_map(self) -> dict[str, dict[str, Any]]:
        cached = self.cache.get("sec_edgar", "ticker_map", {})
        if cached:
            return cached.value
        payload = self._get(self.tickers_url)
        result = {str(row["ticker"]).upper(): {"cik": row["cik_str"], "title": row["title"]} for row in payload.values()}
        self.cache.put("sec_edgar", "ticker_map", {}, result, 7 * 86400)
        return result

    def _get(self, url: str) -> dict[str, Any]:
        try:
            import requests
            response = requests.get(url, headers={"User-Agent": self.user_agent, "Accept-Encoding": "gzip, deflate"}, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            raise ProviderError(f"SEC EDGAR request failed: {exc}") from exc
        except ValueError as exc:
            raise ProviderError("SEC EDGAR returned an invalid response.") from exc
def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return float(numerator) / float(denominator)


def _growth(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return round(float(current) / float(previous) - 1, 6)
