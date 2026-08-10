from core.services.watchlist_service import WatchlistService
from core.services.market_data_service import MarketDataService
from core.analyzers.financial_analyzer import FinancialAnalyzer
from core.services.research_service import ResearchService

from core.engines.discovery_engine import DiscoveryEngine
from core.models.company_analysis import CompanyAnalysis


class Atlas:

    def __init__(self):

        self.watchlist = WatchlistService()
        self.market = MarketDataService()
        self.financial = FinancialAnalyzer()
        self.research = ResearchService()
        self.discovery = DiscoveryEngine()

    def run_watchlist(self):

        analyses = []

        print("\nAnalyzing watchlist...\n")

        for ticker in self.watchlist.get_watchlist():

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

        analyses.sort(
            key=lambda company: company.score,
            reverse=True
        )

        self._display_results(
            analyses,
            "TOP WATCHLIST OPPORTUNITIES"
        )

    def run_discovery(self):

        analyses = self.discovery.discover(

            self.watchlist.get_watchlist()

        )

        self._display_results(

            analyses,

            "TOP DISCOVERIES"

        )

    def _display_results(self, analyses, title):

        print("\n" + "=" * 70)
        print(title)
        print("=" * 70)

        for index, company in enumerate(analyses[:10], start=1):

            print(

                f"{index}. "

                f"{company.ticker:<6}"

                f"{company.score}/100"

            )

        print("\nGenerating AI reports...\n")

        for company in analyses[:5]:

            print("=" * 70)
            print(company.company)
            print("=" * 70)

            report = self.research.build_report(

                company.stock,

                company.financial

            )

            print(report)
            print()