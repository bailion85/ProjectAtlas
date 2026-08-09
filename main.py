from core.services.portfolio_service import PortfolioService


def main():

    portfolio = PortfolioService()

    print("=" * 40)
    print("PROJECT ATLAS")
    print("=" * 40)

    print(f"Cash Before: ${portfolio.get_cash():,.2f}")

    if not portfolio.get_holdings():
        print("Buying 2 shares of AAPL...")
        portfolio.buy_stock("AAPL", 2, 313.33)

    print(f"Cash After: ${portfolio.get_cash():,.2f}")
    print()

    print("Current Holdings")
    for holding in portfolio.get_holdings():
        print(holding)


if __name__ == "__main__":
    main()