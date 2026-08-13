from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Any
from urllib.parse import quote

from core.providers.market_provider import MarketDataProvider, ProviderError


TIINGO_PROVIDER_VERSION = 4


class TiingoProvider(MarketDataProvider):
    name = "Tiingo"
    base_url = "https://api.tiingo.com/tiingo/daily"
    iex_url = "https://api.tiingo.com/iex"
    discovery_universe = (
        "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "BRK.B", "LLY", "AVGO", "JPM",
        "V", "XOM", "UNH", "MA", "COST", "HD", "PG", "JNJ", "ABBV", "WMT", "BAC", "KO",
        "PEP", "MRK", "CRM", "ORCL", "AMD", "NFLX", "CVX", "ADBE", "TMO", "MCD", "CSCO",
        "ACN", "ABT", "GE", "CAT", "IBM", "NOW", "INTU", "QCOM", "TXN", "AMAT", "ISRG",
        "BKNG", "SPGI", "LOW", "RTX", "HON", "UPS", "DE", "LRCX", "MU", "PANW", "UBER",
        "PGR", "SYK", "ETN", "C", "SCHW", "BLK", "MDT", "ADP", "VRTX", "REGN", "ADI",
        "CB", "MMC", "CI", "GILD", "SO", "DUK", "NEE", "CL", "MO", "TGT", "TJX", "CMG",
        "MAR", "MELI", "SHOP", "SNOW", "PLTR", "CRWD", "KLAC", "CDNS", "SNPS", "APH",
    )

    def __init__(self, api_key: str | None = None, timeout: int = 20):
        self.api_key = api_key or os.getenv("TIINGO_API_KEY")
        if not self.api_key:
            raise ProviderError("TIINGO_API_KEY is required for the hybrid market-data provider.")
        self.timeout = timeout

    def _get(self, ticker: str, endpoint: str = "prices", **params: str) -> Any:
        try:
            import requests
        except ImportError as exc:
            raise ProviderError("Install the requests package to use Tiingo.") from exc
        url = f"{self.base_url}/{quote(ticker.upper(), safe='')}"
        if endpoint:
            url += f"/{endpoint}"
        try:
            response = requests.get(
                url, params=params, headers={"Authorization": f"Token {self.api_key}"},
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise ProviderError(f"Tiingo request failed: {exc}") from exc
        except ValueError as exc:
            raise ProviderError("Tiingo returned an invalid response.") from exc
        if isinstance(payload, dict) and payload.get("detail"):
            raise ProviderError(f"Tiingo: {payload['detail']}")
        return payload

    def search(self, query: str) -> list[dict[str, str]]:
        symbol = query.strip().upper()
        try:
            metadata = self._get(symbol, endpoint="")
        except ProviderError:
            return []
        return [{"symbol": metadata.get("ticker", symbol), "name": metadata.get("name", symbol)}]

    def market_movers(self) -> dict[str, Any]:
        """Build a liquid broad-market candidate feed with one batched Tiingo IEX request."""
        payload = self._iex(self.discovery_universe)
        rows = []
        for item in payload:
            ticker = str(item.get("ticker", "")).upper()
            price = _value(item, "tngoLast", "last", "mid", "prevClose")
            previous = _value(item, "prevClose")
            volume = int(_value(item, "volume") or 0)
            if not ticker or price is None or not previous:
                continue
            change = (price / previous - 1) * 100
            rows.append({
                "ticker": ticker, "price": price, "change_amount": price - previous,
                "change_percentage": change, "volume": volume,
            })
        if not rows:
            raise ProviderError("Tiingo returned no usable broad-market quotes for discovery.")
        gainers = sorted(rows, key=lambda row: (-row["change_percentage"], -row["volume"]))[:15]
        losers = sorted(rows, key=lambda row: (row["change_percentage"], -row["volume"]))[:15]
        active = sorted(rows, key=lambda row: -row["volume"])[:20]
        grouped = []
        for group, values in (("Top gainer", gainers), ("Most active", active), ("Top loser", losers)):
            grouped.extend([{**row, "group": group} for row in values])
        observed = next((item.get("timestamp") or item.get("quoteTimestamp") for item in payload if item), None)
        return {"provider": f"{self.name} broad-market scan", "last_updated": observed, "rows": grouped}

    def market_dashboard(self, tickers: tuple[str, ...]) -> dict[str, Any]:
        """Return one batched IEX quote set for broad-market dashboard symbols."""
        payload = self._iex(tuple(dict.fromkeys(symbol.upper() for symbol in tickers)))
        quotes = []
        for item in payload:
            symbol = str(item.get("ticker", "")).upper()
            price = _value(item, "tngoLast", "last", "mid", "prevClose")
            previous = _value(item, "prevClose")
            if not symbol or price is None or not previous:
                continue
            quotes.append({
                "ticker": symbol,
                "price": price,
                "previous_close": previous,
                "change_percent": (price / previous - 1) * 100,
                "volume": int(_value(item, "volume") or 0),
                "observed_at": item.get("timestamp") or item.get("quoteTimestamp"),
            })
        if not quotes:
            raise ProviderError("Tiingo returned no usable market-dashboard quotes.")
        return {"provider": "Tiingo IEX", "quotes": quotes}
    def _iex(self, tickers: tuple[str, ...]) -> list[dict[str, Any]]:
        try:
            import requests
        except ImportError as exc:
            raise ProviderError("Install the requests package to use Tiingo.") from exc
        url = f"{self.iex_url}/{','.join(tickers)}"
        try:
            response = requests.get(
                url, headers={"Authorization": f"Token {self.api_key}"}, timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise ProviderError(f"Tiingo broad-market request failed: {exc}") from exc
        except ValueError as exc:
            raise ProviderError("Tiingo returned an invalid broad-market response.") from exc
        if isinstance(payload, dict) and payload.get("detail"):
            raise ProviderError(f"Tiingo: {payload['detail']}")
        if not isinstance(payload, list):
            raise ProviderError("Tiingo returned an unexpected broad-market response.")
        return payload

    def security_metadata(self, ticker: str) -> dict[str, Any]:
        metadata = self._get(ticker, endpoint="")
        description = str(metadata.get("description") or "")
        name = str(metadata.get("name") or ticker.upper())
        text = f"{name} {description}".lower()
        etf_markers = (
            "exchange traded fund", "exchange-traded fund", "historical etf prices",
            " etf ", " etf shares", "index fund etf",
        )
        asset_type = "ETF" if any(marker in f" {text} " for marker in etf_markers) else "Stock"
        return {
            "symbol": ticker.upper(), "name": name, "description": description,
            "asset_type": asset_type, "exchange": metadata.get("exchangeCode"),
        }
    def snapshot(self, ticker: str) -> dict[str, Any]:
        metadata = self._get(ticker, endpoint="")
        quote_data = self.price_snapshot(ticker)
        return {
            "symbol": ticker.upper(), "name": metadata.get("name") or ticker.upper(),
            "description": metadata.get("description") or "", "asset_type": metadata.get("asset_type", "Stock"),
            "sector": "Diversified fund" if metadata.get("asset_type") == "ETF" else None,
            "industry": "ETF" if metadata.get("asset_type") == "ETF" else None,
            **quote_data, "market_cap": None, "pe_ratio": None,
            "forward_pe": None, "peg_ratio": None, "price_to_book": None,
            "profit_margin": None, "operating_margin": None, "return_on_equity": None,
            "revenue_growth": None, "earnings_growth": None, "debt_to_equity": None,
            "free_cashflow": None, "beta": None, "fifty_two_week_high": None,
            "fifty_two_week_low": None, "analyst_target": None, "source": self.name,
        }

    def price_snapshot(self, ticker: str) -> dict[str, Any]:
        prices = self._prices(ticker, days=14)
        latest = prices[-1]
        previous = prices[-2] if len(prices) > 1 else latest
        price = _close(latest)
        prior = _close(previous)
        change = ((price / prior) - 1) * 100 if price is not None and prior else None
        return {
            "price": price, "change_percent": change,
            "observed_at": str(latest.get("date", "")),
        }

    def news(self, ticker: str) -> list[dict[str, Any]]:
        return []

    def history(self, ticker: str) -> list[dict[str, Any]]:
        monthly: dict[str, dict[str, Any]] = {}
        for point in self.daily_history(ticker):
            monthly[point["date"][:7]] = point
        return list(monthly.values())[-61:]

    def daily_history(self, ticker: str) -> list[dict[str, Any]]:
        points = []
        for row in self._prices(ticker):
            close = _close(row)
            if close is not None:
                points.append({"date": str(row.get("date", ""))[:10], "close": close})
        if not points:
            raise ProviderError(f"No Tiingo price history found for {ticker.upper()}.")
        return sorted(points, key=lambda point: point["date"])

    def _prices(self, ticker: str, days: int = 6 * 366) -> list[dict[str, Any]]:
        start = (date.today() - timedelta(days=days)).isoformat()
        payload = self._get(ticker, startDate=start, resampleFreq="daily")
        if not isinstance(payload, list) or not payload:
            raise ProviderError(f"No Tiingo prices found for {ticker.upper()}.")
        return sorted(payload, key=lambda row: str(row.get("date", "")))


def _close(row: dict[str, Any]) -> float | None:
    value = row.get("adjClose", row.get("close"))
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _value(row: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        try:
            value = row.get(key)
            if value is not None:
                return float(value)
        except (TypeError, ValueError):
            continue
    return None
