from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.providers.market_provider import MarketDataProvider, ProviderError


YAHOOQUERY_PROVIDER_VERSION = 1


class YahooQueryProvider(MarketDataProvider):
    """No-key market-data fallback backed by Yahoo's unofficial public interface."""

    name = "YahooQuery"
    supports_no_credit_research = True
    snapshot_schema_version = 1
    discovery_universe = (
        "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "BRK-B", "LLY", "AVGO", "JPM",
        "V", "XOM", "UNH", "MA", "COST", "HD", "PG", "JNJ", "ABBV", "WMT", "BAC", "KO",
        "PEP", "MRK", "CRM", "ORCL", "AMD", "NFLX", "CVX", "ADBE", "GE", "CAT", "IBM",
        "QCOM", "MU", "PLTR", "UBER", "TGT", "MCD", "CSCO", "SPY", "QQQ", "IWM",
    )

    def __init__(self, asynchronous: bool = False):
        self.asynchronous = asynchronous

    def _ticker(self, symbols: str | tuple[str, ...]):
        try:
            from yahooquery import Ticker
        except ImportError as exc:
            raise ProviderError("Install yahooquery to use the Yahoo market-data fallback.") from exc
        joined = symbols if isinstance(symbols, str) else " ".join(symbols)
        try:
            return Ticker(joined, asynchronous=self.asynchronous, formatted=False)
        except Exception as exc:
            raise ProviderError(f"YahooQuery client failed: {exc}") from exc

    @staticmethod
    def _module(payload: Any, symbol: str) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return {}
        value = payload.get(symbol.upper(), payload)
        return value if isinstance(value, dict) and not value.get("error") else {}

    def search(self, query: str) -> list[dict[str, str]]:
        symbol = query.strip().upper()
        data = self.security_metadata(symbol)
        return [{"symbol": symbol, "name": data.get("name") or symbol}]

    def security_metadata(self, ticker: str) -> dict[str, Any]:
        symbol = ticker.strip().upper()
        client = self._ticker(symbol)
        try:
            quote_type = self._module(client.quote_type, symbol)
            profile = self._module(client.asset_profile, symbol)
        except Exception as exc:
            raise ProviderError(f"YahooQuery metadata failed for {symbol}: {exc}") from exc
        quote_name = quote_type.get("longName") or quote_type.get("shortName") or symbol
        quote_kind = str(quote_type.get("quoteType") or "").upper()
        asset_type = "ETF" if quote_kind == "ETF" else "Stock"
        return {
            "symbol": symbol, "name": quote_name,
            "description": profile.get("longBusinessSummary") or "",
            "asset_type": asset_type, "exchange": quote_type.get("exchange"),
            "sector": "Diversified fund" if asset_type == "ETF" else profile.get("sector"),
            "industry": "ETF" if asset_type == "ETF" else profile.get("industry"),
        }

    def price_snapshot(self, ticker: str) -> dict[str, Any]:
        symbol = ticker.strip().upper()
        try:
            price = self._module(self._ticker(symbol).price, symbol)
        except Exception as exc:
            raise ProviderError(f"YahooQuery quote failed for {symbol}: {exc}") from exc
        current = _number(price.get("regularMarketPrice"))
        previous = _number(price.get("regularMarketPreviousClose"))
        if current is None:
            raise ProviderError(f"YahooQuery returned no current price for {symbol}.")
        change = _number(price.get("regularMarketChangePercent"))
        if change is None and previous:
            change = (current / previous - 1) * 100
        elif change is not None and abs(change) <= 1:
            change *= 100
        observed = price.get("regularMarketTime")
        if isinstance(observed, (int, float)):
            observed = datetime.fromtimestamp(observed, timezone.utc).isoformat()
        return {"price": current, "change_percent": change, "observed_at": observed,
                "previous_close": previous, "source": self.name}

    def market_dashboard(self, tickers: tuple[str, ...]) -> dict[str, Any]:
        symbols = tuple(dict.fromkeys(symbol.strip().upper() for symbol in tickers if symbol.strip()))
        try:
            payload = self._ticker(symbols).price
        except Exception as exc:
            raise ProviderError(f"YahooQuery dashboard quotes failed: {exc}") from exc
        quotes = []
        for symbol in symbols:
            price = self._module(payload, symbol)
            current = _number(price.get("regularMarketPrice"))
            previous = _number(price.get("regularMarketPreviousClose"))
            if current is None:
                continue
            change = _number(price.get("regularMarketChangePercent"))
            if change is None and previous:
                change = (current / previous - 1) * 100
            elif change is not None and abs(change) <= 1:
                change *= 100
            observed = price.get("regularMarketTime")
            if isinstance(observed, (int, float)):
                observed = datetime.fromtimestamp(observed, timezone.utc).isoformat()
            quotes.append({
                "ticker": symbol, "price": current, "previous_close": previous,
                "change_percent": change, "volume": int(_number(price.get("regularMarketVolume")) or 0),
                "observed_at": observed,
            })
        if not quotes:
            raise ProviderError("YahooQuery returned no usable dashboard quotes.")
        return {"provider": self.name, "quotes": quotes}

    def market_movers(self) -> dict[str, Any]:
        dashboard = self.market_dashboard(self.discovery_universe)
        rows = [{
            "ticker": quote["ticker"], "price": quote["price"],
            "change_amount": quote["price"] - quote["previous_close"] if quote.get("previous_close") else None,
            "change_percentage": quote.get("change_percent"), "volume": quote.get("volume", 0),
        } for quote in dashboard["quotes"] if quote.get("change_percent") is not None]
        if not rows:
            raise ProviderError("YahooQuery returned no usable broad-market movers.")
        gainers = sorted(rows, key=lambda row: (-row["change_percentage"], -row["volume"]))[:15]
        losers = sorted(rows, key=lambda row: (row["change_percentage"], -row["volume"]))[:15]
        active = sorted(rows, key=lambda row: -row["volume"])[:20]
        grouped = []
        for group, values in (("Top gainer", gainers), ("Most active", active), ("Top loser", losers)):
            grouped.extend([{**row, "group": group} for row in values])
        observed = next((quote.get("observed_at") for quote in dashboard["quotes"] if quote.get("observed_at")), None)
        return {"provider": f"{self.name} broad-market scan", "last_updated": observed, "rows": grouped}
    def snapshot(self, ticker: str) -> dict[str, Any]:
        symbol = ticker.strip().upper()
        client = self._ticker(symbol)
        try:
            metadata = self.security_metadata(symbol)
            quote = self.price_snapshot(symbol)
            summary = self._module(client.summary_detail, symbol)
            stats = self._module(client.key_stats, symbol)
            financial = self._module(client.financial_data, symbol)
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"YahooQuery company snapshot failed for {symbol}: {exc}") from exc
        return {
            **metadata, **quote,
            "market_cap": _number(summary.get("marketCap")),
            "pe_ratio": _number(summary.get("trailingPE")),
            "forward_pe": _number(summary.get("forwardPE")),
            "peg_ratio": _number(stats.get("pegRatio")),
            "price_to_book": _number(stats.get("priceToBook")),
            "profit_margin": _number(financial.get("profitMargins")),
            "operating_margin": _number(financial.get("operatingMargins")),
            "return_on_equity": _number(financial.get("returnOnEquity")),
            "revenue_growth": _number(financial.get("revenueGrowth")),
            "earnings_growth": _number(financial.get("earningsGrowth")),
            "debt_to_equity": _number(financial.get("debtToEquity")),
            "free_cashflow": _number(financial.get("freeCashflow")),
            "beta": _number(summary.get("beta")),
            "fifty_two_week_high": _number(summary.get("fiftyTwoWeekHigh")),
            "fifty_two_week_low": _number(summary.get("fiftyTwoWeekLow")),
            "analyst_target": _number(financial.get("targetMeanPrice")),
            "fundamentals_status": "YahooQuery fallback fundamentals",
            "source": self.name,
        }

    def daily_history(self, ticker: str) -> list[dict[str, Any]]:
        symbol = ticker.strip().upper()
        try:
            frame = self._ticker(symbol).history(period="2y", interval="1d")
        except Exception as exc:
            raise ProviderError(f"YahooQuery history failed for {symbol}: {exc}") from exc
        if frame is None or getattr(frame, "empty", True):
            raise ProviderError(f"YahooQuery returned no price history for {symbol}.")
        points = []
        try:
            for index, row in frame.iterrows():
                observed = index[-1] if isinstance(index, tuple) else index
                close = _number(row.get("adjclose", row.get("close")))
                if close is not None:
                    points.append({"date": str(observed)[:10], "close": close})
        except Exception as exc:
            raise ProviderError(f"YahooQuery history was invalid for {symbol}: {exc}") from exc
        if not points:
            raise ProviderError(f"YahooQuery returned no usable price history for {symbol}.")
        return sorted(points, key=lambda item: item["date"])

    def history(self, ticker: str) -> list[dict[str, Any]]:
        monthly: dict[str, dict[str, Any]] = {}
        for point in self.daily_history(ticker):
            monthly[point["date"][:7]] = point
        return list(monthly.values())[-61:]

    def news(self, ticker: str) -> list[dict[str, Any]]:
        symbol = ticker.strip().upper()
        try:
            items = self._ticker(symbol).news(count=10)
        except Exception:
            return []
        if isinstance(items, dict):
            items = items.get(symbol, [])
        return [{
            "title": item.get("title", ""), "summary": item.get("summary", ""),
            "url": item.get("link") or item.get("url", ""),
            "source": (item.get("publisher") or self.name),
            "published_at": item.get("providerPublishTime") or "", "sentiment": None,
        } for item in items or [] if isinstance(item, dict)]


def _number(value: Any) -> float | None:
    if isinstance(value, dict):
        value = value.get("raw")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
