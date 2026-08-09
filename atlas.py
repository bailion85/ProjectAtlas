from core.services.market_data_service import MarketDataService
from core.services.research_service import ResearchService


class Atlas:

    def __init__(self):
        self.market = MarketDataService()
        self.research = ResearchService()

    def analyze_stock(self, ticker):
        stock = self.market.get_stock_info(ticker)
        analysis = self.research.analyze_stock(stock)

        return stock, analysis