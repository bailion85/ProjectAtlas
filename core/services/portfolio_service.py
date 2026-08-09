import json
from pathlib import Path


class PortfolioService:

    def __init__(self):
        self.file_path = Path("data/portfolio.json")

        # If the file doesn't exist or is empty, initialize it.
        if (not self.file_path.exists()) or self.file_path.stat().st_size == 0:
            self.portfolio = {
                "cash": 1000.00,
                "holdings": []
            }
            self.save()
        else:
            with open(self.file_path, "r", encoding="utf-8") as file:
                self.portfolio = json.load(file)

    def get_cash(self):
        return self.portfolio["cash"]

    def get_holdings(self):
        return self.portfolio["holdings"]

    def buy_stock(self, ticker, shares, price):
        cost = shares * price

        if cost > self.portfolio["cash"]:
            raise ValueError("Not enough cash to complete purchase.")

        self.portfolio["cash"] -= cost

        self.portfolio["holdings"].append({
            "ticker": ticker,
            "shares": shares,
            "purchase_price": price
        })

        self.save()

    def save(self):
        with open(self.file_path, "w", encoding="utf-8") as file:
            json.dump(self.portfolio, file, indent=4)