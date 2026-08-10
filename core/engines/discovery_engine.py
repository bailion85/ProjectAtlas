from core.services.discovery_service import DiscoveryService
from core.services.market_data_service import MarketDataService
from core.analyzers.financial_analyzer import FinancialAnalyzer
from core.models.company_analysis import CompanyAnalysis


class DiscoveryEngine:

    def __init__(self):

        self.discovery = DiscoveryService()
        self.market = MarketDataService()
        self.financial = FinancialAnalyzer()

    def discover(self, watchlist):

        candidates = self.discovery.get_candidates(watchlist)

        analyses = []

        print("\nScanning discovery universe...\n")

        for ticker in candidates:

            try:

                stock = self.market.get_stock_info(ticker)

                financial = self.financial.analyze(stock)

                analyses.append(

                    CompanyAnalysis(

                        ticker=stock["symbol"],

                        company=stock["name"],

                        stock=stock,

                        financial_analysis=financial

                    )

                )

                print(f"✓ {ticker}")

            except Exception as e:

                print(f"✗ {ticker}: {e}")

        analyses.sort(
            key=lambda company: company.score,
            reverse=True
        )

        return analyses