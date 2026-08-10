import yfinance as yf


class MarketDataService:

    def get_stock_info(self, ticker):

        stock = yf.Ticker(ticker)

        info = stock.info

        return {

            # Basic Information
            "symbol": ticker.upper(),
            "name": info.get("longName"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),

            # Price
            "price": info.get("currentPrice"),
            "market_cap": info.get("marketCap"),

            # Valuation
            "pe_ratio": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "peg_ratio": info.get("pegRatio"),
            "price_to_book": info.get("priceToBook"),
            "enterprise_to_ebitda": info.get("enterpriseToEbitda"),

            # Profitability
            "profit_margin": info.get("profitMargins"),
            "operating_margin": info.get("operatingMargins"),
            "return_on_equity": info.get("returnOnEquity"),
            "return_on_assets": info.get("returnOnAssets"),

            # Growth
            "earnings_growth": info.get("earningsGrowth"),
            "revenue_growth": info.get("revenueGrowth"),

            # Financial Health
            "debt_to_equity": info.get("debtToEquity"),
            "current_ratio": info.get("currentRatio"),
            "quick_ratio": info.get("quickRatio"),

            # Cash Flow
            "free_cashflow": info.get("freeCashflow"),
            "operating_cashflow": info.get("operatingCashflow"),

            # Shareholder Returns
            "dividend_yield": info.get("dividendYield"),
            "payout_ratio": info.get("payoutRatio"),

            # Trading
            "beta": info.get("beta"),
            "average_volume": info.get("averageVolume"),

            # Price History
            "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
            "fifty_two_week_low": info.get("fiftyTwoWeekLow"),

            # Wall Street
            "recommendation": info.get("recommendationKey"),
            "target_price": info.get("targetMeanPrice"),
            "number_of_analysts": info.get("numberOfAnalystOpinions")
        }