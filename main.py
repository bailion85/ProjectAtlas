from core.services.watchlist_service import WatchlistService
from core.services.market_data_service import MarketDataService
from core.services.scoring_service import ScoringService
from core.services.decision_service import DecisionService

from core.models.stock_analysis import StockAnalysis


def main():

    print("=" * 60)
    print("🚀 PROJECT ATLAS")
    print("=" * 60)

    watchlist = WatchlistService()
    market = MarketDataService()
    scoring = ScoringService()
    decision = DecisionService()

    analyses = []

    print("\nScanning Watchlist...\n")

    for ticker in watchlist.get_watchlist():

        stock = market.get_stock_info(ticker)

        score = scoring.score_stock(stock)

        analysis = StockAnalysis(stock, score)

        analyses.append(analysis)

    ranked = decision.rank(analyses)

    print("=" * 60)
    print("Today's Rankings")
    print("=" * 60)

    for i, analysis in enumerate(ranked, start=1):
        print(
            f"{i}. {analysis.symbol:<6} "
            f"Score: {analysis.score}"
        )

    recommendation = decision.recommend(analyses)

    print("\n" + "=" * 60)
    print("📈 Today's Recommendation")
    print("=" * 60)

    print(f"BUY: {recommendation.symbol}")
    print(f"Company: {recommendation.company}")
    print(f"Current Price: ${recommendation.price}")
    print(f"Score: {recommendation.score}/100")

    print("\n✅ Analysis Complete")


if __name__ == "__main__":
    main()