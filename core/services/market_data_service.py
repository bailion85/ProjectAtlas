import yfinance as yf


class MarketDataService:

    def get_stock_info(self, ticker):

        stock = yf.Ticker(ticker)

        info = stock.info

        return {
    "symbol": ticker.upper(),
    "name": info.get("longName"),
    "price": info.get("currentPrice"),
    "market_cap": info.get("marketCap"),
    "pe_ratio": info.get("trailingPE"),
    "forward_pe": info.get("forwardPE"),
    "peg_ratio": info.get("pegRatio"),
    "beta": info.get("beta"),
    "sector": info.get("sector"),
    "industry": info.get("industry"),
    "dividend_yield": info.get("dividendYield"),
    "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
    "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
    "average_volume": info.get("averageVolume"),
    "recommendation": info.get("recommendationKey"),
    "target_price": info.get("targetMeanPrice"),
}